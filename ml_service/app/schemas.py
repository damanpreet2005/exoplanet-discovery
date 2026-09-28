"""
Pydantic request/response schemas for the ML inference service.

Feature naming note: the stored model artifacts (RandomForestClassifier and
RobustScaler inside model/hybrid_ensemble_model.pkl) were fit on a plain
numpy array -- `feature_names_in_` is None on both objects, and no
preprocessing/training source code exists anywhere in this repository.
The semantic names of the 17 features (e.g. what physical quantity each one
represents) are therefore NOT recoverable from the repository and are not
invented here. `feature_1` .. `feature_17` are positional placeholders that
MUST be supplied in the exact order the original model was trained on. If the
real feature names become available, update FEATURE_ORDER below (order must
stay identical) -- no other code needs to change.
"""
import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

N_FEATURES = 17
FEATURE_ORDER = [f"feature_{i}" for i in range(1, N_FEATURES + 1)]


class PredictionFeatures(BaseModel):
    """The 17 numerical inputs the trained model expects, in trained order."""

    model_config = ConfigDict(extra="forbid")

    feature_1: float
    feature_2: float
    feature_3: float
    feature_4: float
    feature_5: float
    feature_6: float
    feature_7: float
    feature_8: float
    feature_9: float
    feature_10: float
    feature_11: float
    feature_12: float
    feature_13: float
    feature_14: float
    feature_15: float
    feature_16: float
    feature_17: float

    @field_validator("*")
    @classmethod
    def reject_non_finite(cls, value: float, info) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be numeric, not boolean")
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"{info.field_name} must be a finite number (got {value})")
        return value

    def as_ordered_list(self) -> list[float]:
        return [getattr(self, name) for name in FEATURE_ORDER]


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: PredictionFeatures


class FusionWeights(BaseModel):
    random_forest: float
    cnn: float


class NotImplementedSection(BaseModel):
    """Explicit placeholder for functionality that does not exist yet in this
    repository. Never populated with fabricated results."""

    status: str = "not_implemented"
    message: str


class LightCurveDiagnostics(BaseModel):
    n_points_used: int
    n_points_dropped: int
    baseline_days: float
    bls_period_days: float
    bls_duration_hours: float
    bls_depth_ppm: float
    bls_transit_snr: float
    num_transits_observed: int


class CharacterisationResult(BaseModel):
    """Real, computed transit-signal vetting diagnostics -- not a placeholder,
    and not a physical planet characterisation (radius/mass/temperature would
    require stellar parameters, which this pipeline deliberately never asks
    for or assumes). Distinct from `physics_validation`, which is genuinely
    not implemented."""

    status: str = "computed"
    bls_period_days: float
    bls_duration_hours: float
    bls_depth_ppm: float
    bls_transit_snr: float
    num_transits_observed: int
    odd_even_depth_ratio: float = Field(
        description="Depth(even transits)/depth(odd transits); far from 1.0 suggests an eclipsing binary"
    )
    secondary_eclipse_depth_ppm: float = Field(
        description="Flux dip opposite the primary transit; a real secondary eclipse suggests an eclipsing binary, not a planet"
    )
    note: str = (
        "Computed entirely from the uploaded light curve via a best-effort "
        "transit search. This describes the transit signal's shape and "
        "consistency, not physical planet properties -- estimating radius, "
        "mass, or temperature would require stellar parameters, which this "
        "pipeline does not request or assume."
    )


class FeatureValueModel(BaseModel):
    """One of the model's 17 real KOI features, fully attributed: what the
    value is, where it came from, and whether it's a light-curve estimate,
    a formula-derived quantity, a catalog lookup, or genuinely unavailable.
    See app/feature_engine.py for how each of the 17 is produced."""
    value: float | None
    unit: str
    source: str
    status: str = Field(description="'estimated' | 'derived' | 'catalog' | 'unavailable'")
    note: str


class PredictionResponse(BaseModel):
    prediction: int = Field(description="Predicted class label (0 or 1). Class semantics "
                                         "(e.g. which label means 'candidate') are not "
                                         "recorded in the stored model artifacts.")
    weighted_probability: float
    random_forest_probability: float
    cnn_probability: float
    weights: FusionWeights
    model_version: str
    request_id: str | None = None
    cache_hit: bool = False


class CatalogResolutionModel(BaseModel):
    requested_identifier: str | None
    identifier_type: str = Field(
        description="'kic' | 'koi_name' | 'kepler_name' | 'tic' | 'unrecognized' | 'none'"
    )
    match_status: str = Field(
        description="'not_provided' | 'not_found' | 'unsupported_identifier_type' | 'lookup_error' | "
                    "'matched_koi' | 'matched_star'"
    )
    matched_kepid: int | None = None
    matched_kepoi_name: str | None = None
    matched_kepler_name: str | None = None
    n_candidate_rows: int = 0
    note: str = ""


class LightCurveAnalysisResponse(BaseModel):
    """Light-curve analysis, automatic 17-feature extraction, and -- only
    when every one of the 17 model features could legitimately be resolved
    -- the actual trained-model prediction, from a CSV upload plus the
    required Object ID.

    The trained model's 17 features (koi_score, koi_period, ...) are real
    KOI catalog/tabular values; a light curve alone can only ever supply
    some of them (see `features` below for exactly which, and why, on this
    request). Running the actual scaler/RF/CNN on a partially-guessed
    vector would silently misuse the trained model's input space, so this
    endpoint only ever calls the model when `ready_for_prediction` is true.
    Otherwise `prediction` stays null and `missing_features` lists exactly
    what's needed -- for the user to complete on the (now much shorter)
    manual-parameter step, see routers/predict_named.py, unchanged.

    `extracted_features` and `suggested_parameters` are preserved from the
    original light-curve-only analysis for backward compatibility; `features`
    is the new, fully-attributed report covering all 17 real model inputs.
    """
    dataset_type: str = "light_curve"
    filename: str
    diagnostics: LightCurveDiagnostics
    extracted_features: dict[str, float]
    suggested_parameters: dict[str, float] = Field(
        description="Best-effort estimates for the subset of the 17 model features "
                     "derivable from a light curve (koi_period, koi_time0bk, "
                     "koi_duration, koi_depth, koi_model_snr) -- for review, not final."
    )
    characterisation: CharacterisationResult
    physics_validation: NotImplementedSection
    warnings: list[str] = []
    request_id: str | None = None

    object_id: str = Field(
        description="The required astronomical catalog Object ID (KIC/KOI/Kepler name) supplied with the upload, echoed back."
    )
    features: dict[str, FeatureValueModel] = Field(
        default_factory=dict,
        description="All 17 real model features (see app/feature_aliases.MODEL_FEATURE_ORDER), "
                     "each fully attributed with value/unit/source/status/note.",
    )
    catalog_resolution: CatalogResolutionModel | None = Field(
        default=None, description="What the Object ID resolved to in the live NASA Exoplanet Archive lookup."
    )
    missing_features: list[str] = Field(
        default_factory=list,
        description="Canonical names of the 17 features that remain unavailable on this request.",
    )
    ready_for_prediction: bool = Field(
        default=False, description="True only when all 17 features were resolved and `prediction` was run."
    )
    prediction: PredictionResponse | None = Field(
        default=None, description="The actual trained-model prediction, present only when ready_for_prediction is true.",
    )


class TabularRowResult(BaseModel):
    row_index: int
    status: str  # "ok" | "error"
    prediction: int | None = None
    weighted_probability: float | None = None
    random_forest_probability: float | None = None
    cnn_probability: float | None = None
    error: str | None = None
    cache_hit: bool = False


class TabularPredictionResponse(BaseModel):
    dataset_type: str = "tabular_kepler"
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    weights: FusionWeights
    model_version: str
    request_id: str | None = None
    results: list[TabularRowResult]
