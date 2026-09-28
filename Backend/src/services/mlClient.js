/**
 * HTTP client for calling the independent Python FastAPI ML inference
 * service. Applies a request timeout so a hung ML service can never hang the
 * gateway, and a small bounded retry policy for transient failures only
 * (network errors, timeouts, and 502/503/504 upstream errors). Deterministic
 * 4xx errors (validation failures) are never retried.
 *
 * Uses Node's built-in fetch/FormData/Blob (Node >= 18) -- no HTTP client
 * dependency needed.
 */
const config = require("../config");
const { MLServiceTimeoutError, MLServiceUnavailableError, UpstreamValidationError } = require("../errors");
const { makeLogger } = require("../logger");

const logger = makeLogger(config.logLevel);

const RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Forwards an uploaded CSV plus (for a light-curve upload) its required
 * Object ID to the ML service's /predict/csv endpoint and returns its
 * parsed JSON body. Throws a typed error on failure. `objectId` is the
 * KIC/KOI/Kepler-name identifier used to resolve catalog-only stellar
 * fields the RF's trained features need (the route handler validates it is
 * present for a light-curve upload before this is ever called; it is
 * `undefined` for a tabular Kepler-catalog upload, which doesn't use it).
 */
async function forwardCsvPrediction({ buffer, filename, mimetype, requestId, objectId }) {
  const maxAttempts = config.mlServiceMaxRetries + 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const form = new FormData();
    form.append("file", new Blob([buffer], { type: mimetype || "text/csv" }), filename);
    if (objectId !== undefined) {
      form.append("object_id", objectId);
    }

    let response;
    try {
      response = await fetchWithTimeout(
        `${config.mlServiceUrl}/predict/csv`,
        { method: "POST", body: form, headers: { "X-Request-Id": requestId } },
        config.mlServiceTimeoutMs
      );
    } catch (err) {
      const isAbort = err.name === "AbortError";
      if (attempt >= maxAttempts) {
        logger.error(isAbort ? "ml_service_timeout" : "ml_service_unreachable", { request_id: requestId });
        throw isAbort ? new MLServiceTimeoutError() : new MLServiceUnavailableError();
      }
      await sleep(config.mlServiceRetryBackoffMs * 2 ** (attempt - 1));
      continue;
    }

    if (response.ok) {
      return response.json();
    }

    if (response.status === 422 || response.status === 400) {
      const body = await response.json().catch(() => null);
      throw new UpstreamValidationError(response.status, body);
    }

    if (RETRYABLE_STATUS_CODES.has(response.status) && attempt < maxAttempts) {
      await sleep(config.mlServiceRetryBackoffMs * 2 ** (attempt - 1));
      continue;
    }

    logger.error("ml_service_error", { request_id: requestId, status_code: response.status });
    throw new MLServiceUnavailableError();
  }

  throw new MLServiceUnavailableError();
}

/**
 * Forwards a named 17-parameter JSON body (human-readable/KOI names) to the
 * ML service's POST /predict endpoint and returns its parsed JSON body.
 * Same timeout/retry policy as forwardCsvPrediction.
 */
async function forwardNamedPrediction(namedParams, requestId) {
  const maxAttempts = config.mlServiceMaxRetries + 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let response;
    try {
      response = await fetchWithTimeout(
        `${config.mlServiceUrl}/predict`,
        {
          method: "POST",
          body: JSON.stringify(namedParams),
          headers: { "Content-Type": "application/json", "X-Request-Id": requestId },
        },
        config.mlServiceTimeoutMs
      );
    } catch (err) {
      const isAbort = err.name === "AbortError";
      if (attempt >= maxAttempts) {
        logger.error(isAbort ? "ml_service_timeout" : "ml_service_unreachable", { request_id: requestId });
        throw isAbort ? new MLServiceTimeoutError() : new MLServiceUnavailableError();
      }
      await sleep(config.mlServiceRetryBackoffMs * 2 ** (attempt - 1));
      continue;
    }

    if (response.ok) {
      return response.json();
    }

    if (response.status === 422 || response.status === 400 || response.status === 503) {
      const body = await response.json().catch(() => null);
      throw new UpstreamValidationError(response.status, body);
    }

    if (RETRYABLE_STATUS_CODES.has(response.status) && attempt < maxAttempts) {
      await sleep(config.mlServiceRetryBackoffMs * 2 ** (attempt - 1));
      continue;
    }

    logger.error("ml_service_error", { request_id: requestId, status_code: response.status });
    throw new MLServiceUnavailableError();
  }

  throw new MLServiceUnavailableError();
}

async function fetchFeatureSchema() {
  const response = await fetchWithTimeout(`${config.mlServiceUrl}/feature-schema`, { method: "GET" }, 5000);
  if (!response.ok) {
    throw new MLServiceUnavailableError();
  }
  return response.json();
}

async function checkReady() {
  try {
    const response = await fetchWithTimeout(`${config.mlServiceUrl}/ready`, { method: "GET" }, 3000);
    return response.ok;
  } catch {
    return false;
  }
}

module.exports = { forwardCsvPrediction, forwardNamedPrediction, fetchFeatureSchema, checkReady };
