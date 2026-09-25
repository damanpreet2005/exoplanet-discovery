"""
Generic, positional (feature_1..feature_17) prediction endpoint.

This is the low-level entry point the light-curve and tabular pipelines both
ultimately build a PredictionFeatures object for. Kept at /predict/raw for
direct/internal use; POST /predict itself is the human-readable, named-
parameter endpoint (see routers/predict_named.py).
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Request

from app.errors import ModelUnavailableError
from app.predictor import predict_with_cache
from app.schemas import PredictionRequest, PredictionResponse

router = APIRouter(tags=["prediction"])
logger = logging.getLogger("ml_service")


def _log_prediction_event(request_id: str, duration_ms: float, cache_hit: bool,
                           model_version: str) -> None:
    """Background job: records prediction metadata (never raw feature values)."""
    logger.info(
        "prediction_logged",
        extra={
            "request_id": request_id,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "model_version": model_version,
        },
    )


@router.post("/predict/raw", response_model=PredictionResponse)
async def predict_endpoint(
    payload: PredictionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> PredictionResponse:
    registry = request.app.state.model_registry
    settings = request.app.state.settings
    cache = request.app.state.cache
    request_id = request.headers.get("x-request-id", "unknown")

    if not registry.is_ready:
        raise ModelUnavailableError()

    response, cache_hit, duration = await predict_with_cache(
        registry.bundle, cache, payload.features, settings.rf_weight, settings.cnn_weight,
        settings.model_version,
    )
    response.request_id = request_id
    duration_ms = duration * 1000
    background_tasks.add_task(
        _log_prediction_event, request_id, duration_ms, cache_hit, settings.model_version
    )
    logger.info(
        "prediction_served",
        extra={
            "request_id": request_id,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "model_version": settings.model_version,
        },
    )
    return response
