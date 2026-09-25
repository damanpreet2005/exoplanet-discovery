from fastapi import APIRouter, Request, Response, status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is up and able to respond."""
    return {"status": "alive"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    """Readiness: the model has finished loading and can serve predictions."""
    registry = request.app.state.model_registry
    if not registry.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": "model not loaded"}
    return {"status": "ready", "model_version": request.app.state.settings.model_version}
