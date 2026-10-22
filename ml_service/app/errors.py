"""Centralized error handling. Never leaks stack traces, file paths, or config to clients."""
import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("ml_service")


def structured_error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class ModelUnavailableError(Exception):
    """Raised when the model has not finished loading / failed to load."""


class CsvValidationHTTPError(Exception):
    """Raised for file-level CSV problems (empty file, wrong column count, etc.)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class CharacterizationRequestError(Exception):
    """Malformed characterization recompute request (bad snapshot, invalid
    or unphysical expert override, unknown config option)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class FileTooLargeError(Exception):
    """Raised when an uploaded CSV exceeds the configured size limit."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("validation_error", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=structured_error(
            "VALIDATION_ERROR",
            "One or more input features are missing, invalid, or out of the expected type.",
        ),
    )


async def model_unavailable_handler(request: Request, exc: ModelUnavailableError):
    logger.error("model_unavailable", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=structured_error(
            "MODEL_UNAVAILABLE", "The prediction model is not currently available."
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=structured_error(
            "INTERNAL_ERROR", "An unexpected error occurred while processing the request."
        ),
    )


async def csv_validation_handler(request: Request, exc: CsvValidationHTTPError):
    logger.warning("csv_validation_error", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=structured_error("CSV_VALIDATION_ERROR", exc.message),
    )


async def characterization_request_handler(request: Request, exc: CharacterizationRequestError):
    logger.warning("characterization_request_error", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=structured_error("CHARACTERIZATION_VALIDATION_ERROR", exc.message),
    )


async def file_too_large_handler(request: Request, exc: FileTooLargeError):
    logger.warning("file_too_large", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=structured_error("FILE_TOO_LARGE", exc.message),
    )


async def missing_feature_handler(request: Request, exc: "MissingFeatureError"):
    logger.warning("missing_feature", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=structured_error("MISSING_FEATURE", str(exc)),
    )


async def invalid_feature_value_handler(request: Request, exc: "InvalidFeatureValueError"):
    logger.warning("invalid_feature_value", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=structured_error("INVALID_FEATURE_VALUE", str(exc)),
    )


async def feature_order_not_configured_handler(request: Request, exc: "FeatureOrderNotConfiguredError"):
    logger.error("feature_order_not_configured", extra={"endpoint": str(request.url.path)})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=structured_error("FEATURE_ORDER_NOT_CONFIGURED", str(exc)),
    )


async def rf_feature_contract_handler(request: Request, exc: "RfFeatureContractError"):
    """This is never a user-input problem -- app/feature_engine.py only ever
    calls the RF once `ready_for_prediction` is true (all 17 real values
    resolved), so reaching this handler means the vector about to be fed to
    the trained model failed its own internal name/order/finiteness
    contract check (app/feature_aliases.assert_valid_rf_feature_vector).
    Treated as a controlled internal error, never a silently-wrong
    prediction."""
    logger.error("rf_feature_contract_violation", extra={"endpoint": str(request.url.path), "detail": str(exc)})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=structured_error(
            "RF_FEATURE_UNAVAILABLE",
            "Unable to construct the required RF feature vector. The prediction was not run.",
        ),
    )


async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=structured_error("NOT_FOUND", "The requested resource does not exist."),
    )
