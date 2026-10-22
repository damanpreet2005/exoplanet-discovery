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

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile

from app.errors import (
    CsvValidationHTTPError,
    FileTooLargeError,
    ModelUnavailableError,
)
from app.feature_aliases import (
    MODEL_FEATURE_ORDER,
    InvalidFeatureValueError,
    MissingFeatureError,
    RfFeatureContractError,
    assert_valid_rf_feature_vector,
    extract_feature_vector,
    looks_like_light_curve_header,
    looks_like_tabular_kepler_header,
)
from app.characterization import characterize_light_curve
from app.config import get_settings
from app.feature_engine import apply_fitted_impact_parameter, extract_features
from app.stellar_catalog_service import MAX_OBJECT_ID_LENGTH
from app.lightcurve_extraction import (
    BEST_EFFORT_WARNING,
    LightCurveValidationError,
    LIGHTCURVE_FEATURE_NAMES,
    parse_time_flux_csv,
    suggest_koi_parameters,
)
from app.predictor import predict_with_cache
from app.tabular_extraction import TabularValidationError, parse_tabular_csv
from app.schemas import (
    CatalogResolutionModel,
    CharacterisationResult,
    FEATURE_ORDER,
    FeatureValueModel,
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


def _validate_object_id_for_light_curve(object_id: str | None) -> str:
    """The RF's 17 trained features genuinely include catalog-only fields
    (koi_steff, koi_slogg, koi_srad, ra, dec, koi_kepmag, koi_score) that a
    light curve alone cannot supply -- see app/feature_engine.py's
    classification. Because of that, Object ID is a required field for the
    light-curve upload path, not an optional extra. This raises a clear,
    specific validation error rather than relying on FastAPI's generic
    "missing field" message. (The tabular Kepler-catalog CSV path is
    unaffected -- those rows already carry their own koi_* columns.)"""
    if object_id is None or not object_id.strip():
        raise CsvValidationHTTPError(
            "Object ID is required: enter the astronomical catalog identifier (e.g. 'KIC 11904151') "
            "for the star/object this light curve belongs to, alongside the CSV upload."
        )
    if not isinstance(object_id, str):
        raise CsvValidationHTTPError("Object ID must be a string.")
    if len(object_id.strip()) > MAX_OBJECT_ID_LENGTH:
        raise CsvValidationHTTPError(f"Object ID must be at most {MAX_OBJECT_ID_LENGTH} characters.")
    return object_id.strip()


@router.post("/predict/csv")
async def predict_csv_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Either a light-curve CSV (time, flux) or a tabular Kepler CSV (koi_* columns)"),
    object_id: str | None = Form(
        None,
        description="Required for a light-curve upload: the KIC ID / KOI name / Kepler planet "
                     "name for the star/object this light curve belongs to, used to resolve "
                     "catalog-only stellar fields (koi_steff, koi_slogg, koi_srad, ra, dec, "
                     "koi_kepmag, koi_score) from the local NASA Exoplanet Archive KOI catalogue. Not used for a "
                     "tabular Kepler-catalog CSV upload, which already carries its own koi_* columns.",
    ),
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
        validated_object_id = _validate_object_id_for_light_curve(object_id)
        return await _handle_light_curve(request, background_tasks, file, raw_bytes, request_id, validated_object_id)
    if looks_like_tabular_kepler_header(header):
        return await _handle_tabular(request, background_tasks, file, raw_bytes, request_id)

    raise CsvValidationHTTPError(
        "Unrecognized CSV format: expected either 'time' and 'flux' columns "
        "(a light curve) or recognized Kepler tabular columns (e.g. "
        f"koi_period, koi_duration, ...); got columns {header!r}."
    )


async def _handle_light_curve(request: Request, background_tasks: BackgroundTasks,
                               file: UploadFile, raw_bytes: bytes, request_id: str,
                               object_id: str,
                               ) -> LightCurveAnalysisResponse:
    """Primary workflow: CSV upload + Object ID -> automatic 17-feature
    extraction (app/feature_engine.py, which itself calls the isolated
    app/stellar_catalog_service.py for the catalog lookup) -> feature
    validation -> ML prediction (only once every one of the 17 real model
    features is resolved) -> response.

    A light curve alone can only ever supply some of the model's 17 real
    KOI features -- the rest (stellar/catalog fields, koi_score) require the
    Object ID to resolve from the local NASA Exoplanet Archive KOI catalogue. When they can't
    be resolved (unknown/mistyped Object ID, or a catalog record missing a
    field), this deliberately does NOT call the trained model on a
    partially-guessed vector (that would silently misuse the trained
    model's input space); `prediction` stays null and `missing_features`
    tells the caller exactly what's needed. The frontend then only asks the
    user for those specific remaining fields, not all 17, on the (existing,
    unmodified) manual-parameter step."""
    registry = request.app.state.model_registry
    settings = request.app.state.settings
    cache = request.app.state.cache

    def _extract():
        time_arr, flux_arr, n_dropped = parse_time_flux_csv(raw_bytes)
        features = extract_features(time_arr, flux_arr, object_id)
        characterization = _characterize(time_arr, flux_arr, features, object_id, request_id)
        apply_fitted_impact_parameter(features, characterization)
        return features, n_dropped, characterization

    try:
        # CPU-bound (CSV parsing + the transit search + transit-model fit) --
        # run off the event loop so a slow/large upload can't block
        # concurrent requests.
        result, n_dropped, characterization = await asyncio.to_thread(_extract)
    except LightCurveValidationError as exc:
        raise CsvValidationHTTPError(str(exc)) from exc

    extraction = result.extraction
    feature_models = {
        canonical: FeatureValueModel(
            value=fv.value, unit=fv.unit, source=fv.source, status=fv.status, note=fv.note,
        )
        for canonical, fv in result.features.items()
    }

    prediction_response = None
    if result.ready_for_prediction:
        ordered_names = list(MODEL_FEATURE_ORDER)
        ordered_values = [result.features[c].value for c in ordered_names]
        # Explicit, defense-in-depth contract check (never expected to fail
        # in practice -- `ready_for_prediction` already guarantees all 17
        # values are present/finite -- this is what catches a future
        # accidental reordering/renaming bug before it can reach the model).
        assert_valid_rf_feature_vector(
            ordered_names, ordered_values, random_forest=registry.bundle.random_forest,
        )
        prediction_features = PredictionFeatures(**dict(zip(FEATURE_ORDER, ordered_values)))
        logger.info("rf_feature_vector_constructed", extra={"request_id": request_id})
        prediction_response, _cache_hit, _duration = await predict_with_cache(
            registry.bundle, cache, prediction_features, settings.rf_weight, settings.cnn_weight,
            settings.model_version,
        )
        prediction_response.request_id = request_id
        logger.info(
            "rf_cnn_ensemble_prediction_generated",
            extra={"request_id": request_id, "prediction": prediction_response.prediction},
        )

    background_tasks.add_task(
        _log_prediction_event, "light_curve", request_id, 0.0, settings.model_version
    )
    logger.info(
        "lightcurve_analysis_served",
        extra={
            "request_id": request_id, "model_version": settings.model_version,
            "ready_for_prediction": result.ready_for_prediction,
            "missing_features": result.missing_features,
        },
    )

    warnings = [BEST_EFFORT_WARNING, *result.warnings]

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
            bls_noise_ppm=extraction.bls.noise_ppm,
            bls_n_in_transit=extraction.bls.n_in_transit,
            bls_sde=extraction.bls.sde,
            num_transits_observed=extraction.characterisation["num_transits_observed"],
        ),
        extracted_features=dict(zip(LIGHTCURVE_FEATURE_NAMES, extraction.features)),
        suggested_parameters=suggest_koi_parameters(extraction),
        characterisation=CharacterisationResult(
            bls_period_days=extraction.characterisation["bls_period_days"],
            bls_duration_hours=extraction.characterisation["bls_duration_hours"],
            bls_depth_ppm=extraction.characterisation["bls_depth_ppm"],
            bls_transit_snr=extraction.characterisation["bls_transit_snr"],
            bls_noise_ppm=extraction.characterisation["bls_noise_ppm"],
            bls_n_in_transit=extraction.characterisation["bls_n_in_transit"],
            bls_sde=extraction.characterisation["bls_sde"],
            num_transits_observed=extraction.characterisation["num_transits_observed"],
            odd_even_depth_ratio=extraction.characterisation["odd_even_depth_ratio"],
            secondary_eclipse_depth_ppm=extraction.characterisation["secondary_eclipse_depth_ppm"],
        ),
        physics_validation=PHYSICS_VALIDATION_PLACEHOLDER,
        warnings=warnings,
        request_id=request_id,
        object_id=object_id,
        features=feature_models,
        catalog_resolution=CatalogResolutionModel(
            requested_identifier=result.catalog.requested_identifier,
            identifier_type=result.catalog.identifier_type,
            match_status=result.catalog.match_status,
            matched_kepid=result.catalog.matched_kepid,
            matched_kepoi_name=result.catalog.matched_kepoi_name,
            matched_kepler_name=result.catalog.matched_kepler_name,
            n_candidate_rows=result.catalog.n_candidate_rows,
            note=result.catalog.note,
        ),
        missing_features=result.missing_features,
        ready_for_prediction=result.ready_for_prediction,
        prediction=prediction_response,
        characterization=characterization,
    )


def _characterize(time_arr, flux_arr, features, object_id: str, request_id: str) -> dict:
    """Planet characterization (app/characterization) for this light curve.
    Runs after -- and entirely independently of -- the 17-feature ML
    extraction; a characterization failure never fails the upload, it is
    reported as an explicit 'failed' status instead."""
    try:
        return characterize_light_curve(time_arr, flux_arr, features.extraction.bls, features.catalog, object_id,
                                        archive_lookup=get_settings().characterization_archive_lookup)
    except Exception as exc:  # noqa: BLE001
        logger.exception("characterization_failed", extra={"request_id": request_id})
        return {"status": "failed", "status_message": f"Planet characterization could not be computed: {exc}",
                "parameters": {}, "sections": [], "classifications": [], "warnings": [], "missing_inputs": []}


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
