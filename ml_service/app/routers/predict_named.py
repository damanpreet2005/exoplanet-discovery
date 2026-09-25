"""
Named-input prediction endpoint.

This is the "input-preprocessing/normalization layer" requested in front of
the existing prediction pipeline. It accepts a flat JSON object using KOI
column names or their recognized aliases (see app/feature_aliases.py),
normalizes/validates it, and maps it into the *exact same* PredictionFeatures
object the existing, unmodified /predict endpoint (and predict_with_cache /
the scaler / the random forest / the CNN / the weighted fusion) already uses.
Nothing about the model, scaler, or fusion logic is touched here.
"""
from fastapi import APIRouter, Request

from app.feature_aliases import MODEL_FEATURE_ORDER, extract_feature_vector
from app.errors import ModelUnavailableError
from app.predictor import predict_with_cache
from app.schemas import FEATURE_ORDER, PredictionFeatures, PredictionResponse

router = APIRouter(tags=["prediction"])


@router.post("/predict", response_model=PredictionResponse)
async def predict_named_endpoint(
    payload: dict,
    request: Request,
) -> PredictionResponse:
    registry = request.app.state.model_registry
    settings = request.app.state.settings
    cache = request.app.state.cache
    request_id = request.headers.get("x-request-id", "unknown")

    if not registry.is_ready:
        raise ModelUnavailableError()

    # ---- input-name normalization / alias handling -----------------------
    # Raises MissingFeatureError / InvalidFeatureValueError / a clear
    # FeatureOrderNotConfiguredError if MODEL_FEATURE_ORDER hasn't been set
    # (see app/feature_aliases.py for exactly why it currently isn't).
    ordered_values = extract_feature_vector(payload, MODEL_FEATURE_ORDER)

    # ---- exact same feature vector shape the existing pipeline expects ---
    features = PredictionFeatures(**dict(zip(FEATURE_ORDER, ordered_values)))

    # ---- existing, unmodified prediction pipeline -------------------------
    response, cache_hit, _ = await predict_with_cache(
        registry.bundle, cache, features, settings.rf_weight, settings.cnn_weight,
        settings.model_version,
    )
    response.request_id = request_id
    return response
