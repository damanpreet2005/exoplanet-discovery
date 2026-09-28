import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cache import InMemoryTTLCache
from app.config import get_settings
from app.errors import (
    CsvValidationHTTPError,
    FileTooLargeError,
    ModelUnavailableError,
    csv_validation_handler,
    feature_order_not_configured_handler,
    file_too_large_handler,
    invalid_feature_value_handler,
    missing_feature_handler,
    model_unavailable_handler,
    not_found_handler,
    rf_feature_contract_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.feature_aliases import (
    FeatureOrderNotConfiguredError,
    InvalidFeatureValueError,
    MissingFeatureError,
    RfFeatureContractError,
)
from app.logging_config import configure_logging
from app.model_loader import ModelRegistry
from app.routers import health, predict, predict_csv, predict_named, schema

logger = logging.getLogger("ml_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.model_registry = ModelRegistry(settings.model_path)
    app.state.cache = InMemoryTTLCache(settings.cache_max_size, settings.cache_ttl_seconds)
    try:
        app.state.model_registry.load()
    except Exception:
        logger.error("startup_model_load_failed")
    yield


app = FastAPI(
    title="Exoplanet ML Inference Service",
    description=(
        "Independent inference service that loads the existing, immutable "
        "Random Forest + 2D CNN ensemble (model/hybrid_ensemble_model.pkl) "
        "and returns weighted-fusion predictions. Not exposed directly to "
        "the browser; called only by the main backend API gateway."
    ),
    version="1.0",
    lifespan=lifespan,
)

settings_for_cors = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_for_cors.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ModelUnavailableError, model_unavailable_handler)
app.add_exception_handler(CsvValidationHTTPError, csv_validation_handler)
app.add_exception_handler(FileTooLargeError, file_too_large_handler)
app.add_exception_handler(MissingFeatureError, missing_feature_handler)
app.add_exception_handler(InvalidFeatureValueError, invalid_feature_value_handler)
app.add_exception_handler(FeatureOrderNotConfiguredError, feature_order_not_configured_handler)
app.add_exception_handler(RfFeatureContractError, rf_feature_contract_handler)
app.add_exception_handler(404, not_found_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router)
app.include_router(predict.router)
app.include_router(predict_csv.router)
app.include_router(predict_named.router)
app.include_router(schema.router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "unknown")
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response
