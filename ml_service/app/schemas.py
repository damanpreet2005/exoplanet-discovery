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


class LightCurvePredictionResponse(BaseModel):
    dataset_type: str = "light_curve"
    filename: str
    diagnostics: LightCurveDiagnostics
    extracted_features: dict[str, float]
    prediction: int
    weighted_probability: float
    random_forest_probability: float
    cnn_probability: float
    weights: FusionWeights
    model_version: str
    request_id: str | None = None
    cache_hit: bool = False
    characterisation: CharacterisationResult
    physics_validation: NotImplementedSection
    warnings: list[str] = []


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
