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

/**
 * Field-level validation failure for account forms. `fields` maps a field
 * name to a user-facing message; it never echoes the submitted value back.
 */
class FieldValidationError extends HttpError {
  constructor(fields, message = "Some fields need attention.") {
    super(422, "VALIDATION_ERROR", message);
    this.fields = fields;
  }
}

/** 401 -- deliberately generic so it never reveals which check failed. */
class AuthenticationError extends HttpError {
  constructor(message = "Authentication required.", code = "UNAUTHENTICATED") {
    super(401, code, message);
  }
}

class ForbiddenError extends HttpError {
  constructor(message = "This request was rejected.", code = "FORBIDDEN") {
    super(403, code, message);
  }
}

class ConflictError extends HttpError {
  constructor(code, message, fields) {
    super(409, code, message);
    this.fields = fields;
  }
}

class AuthUnavailableError extends HttpError {
  constructor(message = "Account services are temporarily unavailable.") {
    super(503, "AUTH_UNAVAILABLE", message);
  }
}

class NotFoundError extends HttpError {
  constructor(message = "The requested resource does not exist.", code = "NOT_FOUND") {
    super(404, code, message);
  }
}

class HistoryUnavailableError extends HttpError {
  constructor(message = "Prediction history is temporarily unavailable.") {
    super(503, "HISTORY_UNAVAILABLE", message);
  }
}

function structuredError(code, message, requestId, fields) {
  const body = { error: { code, message } };
  if (fields) body.error.fields = fields;
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
  FieldValidationError,
  AuthenticationError,
  ForbiddenError,
  ConflictError,
  AuthUnavailableError,
  NotFoundError,
  HistoryUnavailableError,
  structuredError,
};
