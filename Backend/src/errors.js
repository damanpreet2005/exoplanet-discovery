/**
 * Typed error classes for centralized error handling, mirroring the
 * structure used in ml_service/app/errors.py: {"error": {code, message}}.
 * Never expose stack traces, file paths, or internals in responses.
 */

class HttpError extends Error {
  constructor(statusCode, code, message) {
    super(message);
    this.statusCode = statusCode;
    this.code = code;
  }
}

class ValidationError extends HttpError {
  constructor(message) {
    super(422, "VALIDATION_ERROR", message);
  }
}

class FileTooLargeError extends HttpError {
  constructor(message) {
    super(400, "FILE_TOO_LARGE", message);
  }
}

class MLServiceUnavailableError extends HttpError {
  constructor(message = "Prediction service is currently unavailable.") {
    super(503, "ML_SERVICE_UNAVAILABLE", message);
  }
}

class MLServiceTimeoutError extends HttpError {
  constructor(message = "Prediction service did not respond in time.") {
    super(504, "ML_SERVICE_TIMEOUT", message);
  }
}

/** Wraps a deterministic 4xx passed through verbatim from the ML service. */
class UpstreamValidationError extends HttpError {
  constructor(statusCode, upstreamBody) {
    const message =
      upstreamBody?.error?.message ||
      "One or more input values were rejected by the prediction service.";
    super(statusCode, upstreamBody?.error?.code || "VALIDATION_ERROR", message);
    this.upstreamBody = upstreamBody;
  }
}

function structuredError(code, message, requestId) {
  const body = { error: { code, message } };
  if (requestId) body.error.request_id = requestId;
  return body;
}

module.exports = {
  HttpError,
  ValidationError,
  FileTooLargeError,
  MLServiceUnavailableError,
  MLServiceTimeoutError,
  UpstreamValidationError,
  structuredError,
};
