"""
CSV prediction endpoint -- routes to one of two completely different
pipelines depending on what was actually uploaded:

  - a LIGHT CURVE (columns: time, flux) -> the existing Box Least Squares
    transit-search pipeline (app/lightcurve_extraction.py), time/flux
    required, observation-baseline validation applies.
  - a TABULAR KEPLER dataset (koi_* catalog columns, e.g. an export of the
    NASA Kepler cumulative table) -> alias normalization + exact model
    feature extraction (app/feature_aliases.py), NO time/flux requirement,
    NO baseline validation -- those checks are specific to the light-curve
    path and must never run against tabular rows.

Routing is decided from the CSV header alone (see
app/feature_aliases.py: looks_like_light_curve_header /
looks_like_tabular_kepler_header) before either pipeline's parsing runs, so a
tabular file can never be misrouted into time-axis interpretation.

Both paths end at the same existing, unmodified prediction pipeline
(app/predictor.py: predict_with_cache -> scaler -> random_forest / cnn ->
weighted fusion).
"""
import asyncio
import csv
import logging
import time as time_module

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile

from app.errors import (
    CsvValidationHTTPError,
    FileTooLargeError,
    ModelUnavailableError,
)
from app.feature_aliases import (
    MODEL_FEATURE_ORDER,
    InvalidFeatureValueError,
    MissingFeatureError,
    extract_feature_vector,
    looks_like_light_curve_header,
    looks_like_tabular_kepler_header,
)
from app.lightcurve_extraction import (
    BEST_EFFORT_WARNING,
    LightCurveValidationError,
    LIGHTCURVE_FEATURE_NAMES,
    compute_feature_vector,
    parse_time_flux_csv,
    suggest_koi_parameters,
)
from app.predictor import predict_with_cache
from app.tabular_extraction import TabularValidationError, parse_tabular_csv
from app.schemas import (
    CharacterisationResult,
    FEATURE_ORDER,
    FusionWeights,
    LightCurveAnalysisResponse,
    LightCurveDiagnostics,
    NotImplementedSection,
    PredictionFeatures,
    TabularPredictionResponse,
    TabularRowResult,
)

router = APIRouter(tags=["prediction"])
logger = logging.getLogger("ml_service")

PHYSICS_VALIDATION_PLACEHOLDER = NotImplementedSection(
    message="Physics validation module — coming in a future implementation stage."
)


def _log_prediction_event(dataset_type: str, request_id: str, duration_ms: float, model_version: str) -> None:
    """Background job: records metadata only, never raw uploaded values."""
    logger.info(
        "csv_prediction_logged",
        extra={
            "dataset_type": dataset_type, "request_id": request_id,
            "duration_ms": duration_ms, "model_version": model_version,
        },
    )


def _peek_header(raw_bytes: bytes) -> list[str]:
    try:
        first_line = raw_bytes.decode("utf-8-sig").splitlines()[0]
    except (UnicodeDecodeError, IndexError) as exc:
        raise CsvValidationHTTPError(
            "The uploaded file is not valid UTF-8 text, or has no header row."
        ) from exc
    return next(csv.reader([first_line]))


@router.post("/predict/csv")
async def predict_csv_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Either a light-curve CSV (time, flux) or a tabular Kepler CSV (koi_* columns)"),
):
    registry = request.app.state.model_registry
    settings = request.app.state.settings
    request_id = request.headers.get("x-request-id", "unknown")

    if not registry.is_ready:
        raise ModelUnavailableError()

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.csv_max_file_size_bytes:
        raise FileTooLargeError(
            f"CSV file exceeds the {settings.csv_max_file_size_bytes} byte limit."
        )

    header = _peek_header(raw_bytes)

    if looks_like_light_curve_header(header):
        return await _handle_light_curve(request, background_tasks, file, raw_bytes, request_id)
    if looks_like_tabular_kepler_header(header):
        return await _handle_tabular(request, background_tasks, file, raw_bytes, request_id)

    raise CsvValidationHTTPError(
        "Unrecognized CSV format: expected either 'time' and 'flux' columns "
        "(a light curve) or recognized Kepler tabular columns (e.g. "
        f"koi_period, koi_duration, ...); got columns {header!r}."
    )


async def _handle_light_curve(request: Request, background_tasks: BackgroundTasks,
                               file: UploadFile, raw_bytes: bytes, request_id: str
                               ) -> LightCurveAnalysisResponse:
    """Stage-1 analysis only -- deliberately does NOT call the trained model.
    See LightCurveAnalysisResponse's docstring for why: the model's real 17
    features are KOI catalog values, most of which a light curve cannot
    provide, so running scaler/RF/CNN on a light-curve-only substitute here
    would silently misuse the trained model. The real prediction happens
    later, once, from the completed 17-parameter form (routers/
    predict_named.py) -- see the combined workflow in the frontend."""
    settings = request.app.state.settings

    def _extract() -> tuple:
        time_arr, flux_arr, n_dropped = parse_time_flux_csv(raw_bytes)
        return compute_feature_vector(time_arr, flux_arr), n_dropped

    try:
        # CPU-bound (CSV parsing + the transit search) -- run off the event
        # loop so a slow/large upload can't block concurrent requests.
        extraction, n_dropped = await asyncio.to_thread(_extract)
    except LightCurveValidationError as exc:
        raise CsvValidationHTTPError(str(exc)) from exc

    background_tasks.add_task(
        _log_prediction_event, "light_curve", request_id, 0.0, settings.model_version
    )
    logger.info(
        "lightcurve_analysis_served",
        extra={"request_id": request_id, "model_version": settings.model_version},
    )

    return LightCurveAnalysisResponse(
        filename=file.filename or "lightcurve.csv",
        diagnostics=LightCurveDiagnostics(
            n_points_used=extraction.n_points_used,
            n_points_dropped=n_dropped,
            baseline_days=extraction.baseline_days,
            bls_period_days=extraction.bls.period_days,
            bls_duration_hours=extraction.bls.duration_hours,
            bls_depth_ppm=extraction.bls.depth_ppm,
            bls_transit_snr=extraction.bls.snr,
            num_transits_observed=extraction.characterisation["num_transits_observed"],
        ),
        extracted_features=dict(zip(LIGHTCURVE_FEATURE_NAMES, extraction.features)),
        suggested_parameters=suggest_koi_parameters(extraction),
        characterisation=CharacterisationResult(
            bls_period_days=extraction.characterisation["bls_period_days"],
            bls_duration_hours=extraction.characterisation["bls_duration_hours"],
            bls_depth_ppm=extraction.characterisation["bls_depth_ppm"],
            bls_transit_snr=extraction.characterisation["bls_transit_snr"],
            num_transits_observed=extraction.characterisation["num_transits_observed"],
            odd_even_depth_ratio=extraction.characterisation["odd_even_depth_ratio"],
            secondary_eclipse_depth_ppm=extraction.characterisation["secondary_eclipse_depth_ppm"],
        ),
        physics_validation=PHYSICS_VALIDATION_PLACEHOLDER,
        warnings=[BEST_EFFORT_WARNING],
        request_id=request_id,
    )


async def _handle_tabular(request: Request, background_tasks: BackgroundTasks,
                           file: UploadFile, raw_bytes: bytes, request_id: str
                           ) -> TabularPredictionResponse:
    """Tabular Kepler catalog path. Deliberately does NOT touch time, flux,
    or any observation-baseline concept -- those are light-curve-only. Each
    row is one candidate; alias-normalized and mapped to the model's exact
    feature vector via app/feature_aliases.py (never guessed, never
    defaulted)."""
    registry = request.app.state.model_registry
    settings = request.app.state.settings
    cache = request.app.state.cache

    try:
        _header, rows = await asyncio.to_thread(parse_tabular_csv, raw_bytes)
    except TabularValidationError as exc:
        raise CsvValidationHTTPError(str(exc)) from exc

    start = time_module.perf_counter()
    results: list[TabularRowResult] = []
    valid_rows = 0

    for row_index, row in enumerate(rows):
        try:
            ordered_values = extract_feature_vector(row, MODEL_FEATURE_ORDER)
        except (MissingFeatureError, InvalidFeatureValueError) as exc:
            results.append(TabularRowResult(row_index=row_index, status="error", error=str(exc)))
            continue

        features = PredictionFeatures(**dict(zip(FEATURE_ORDER, ordered_values)))
        response, cache_hit, _ = await predict_with_cache(
            registry.bundle, cache, features, settings.rf_weight, settings.cnn_weight,
            settings.model_version,
        )
        valid_rows += 1
        results.append(TabularRowResult(
            row_index=row_index, status="ok", prediction=response.prediction,
            weighted_probability=response.weighted_probability,
            random_forest_probability=response.random_forest_probability,
            cnn_probability=response.cnn_probability, cache_hit=cache_hit,
        ))

    duration_ms = (time_module.perf_counter() - start) * 1000
    background_tasks.add_task(
        _log_prediction_event, "tabular_kepler", request_id, duration_ms, settings.model_version
    )
    logger.info(
        "tabular_prediction_served",
        extra={"request_id": request_id, "duration_ms": duration_ms, "model_version": settings.model_version},
    )

    return TabularPredictionResponse(
        filename=file.filename or "tabular.csv",
        total_rows=len(rows),
        valid_rows=valid_rows,
        invalid_rows=len(rows) - valid_rows,
        weights=FusionWeights(random_forest=settings.rf_weight, cnn=settings.cnn_weight),
        model_version=settings.model_version,
        request_id=request_id,
        results=results,
    )
