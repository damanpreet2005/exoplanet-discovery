const { HttpError, structuredError } = require("../errors");
const { makeLogger } = require("../logger");
const config = require("../config");

const logger = makeLogger(config.logLevel);

/** Centralized error handler. Never leaks stack traces or internals to clients. */
// eslint-disable-next-line no-unused-vars
function errorHandler(err, req, res, next) {
  const requestId = req.requestId;

  if (err instanceof HttpError) {
    if (err.statusCode >= 500) {
      logger.error(err.message, { request_id: requestId, endpoint: req.path });
    } else {
      logger.warn(err.message, { request_id: requestId, endpoint: req.path });
    }
    if (err.statusCode === 401) res.setHeader("WWW-Authenticate", 'Bearer realm="exodiscovery"');
    return res.status(err.statusCode).json(structuredError(err.code, err.message, requestId, err.fields));
  }

  // body-parser: malformed JSON. Its message can quote request content, so a
  // fixed message is returned and logged instead.
  if (err && err.type === "entity.parse.failed") {
    logger.warn("malformed_json_body", { request_id: requestId, endpoint: req.path });
    return res.status(400).json(structuredError("MALFORMED_JSON", "The request body is not valid JSON.", requestId));
  }
  if (err && err.type === "entity.too.large") {
    logger.warn("request_body_too_large", { request_id: requestId, endpoint: req.path });
    return res.status(413).json(structuredError("PAYLOAD_TOO_LARGE", "The request body is too large.", requestId));
  }

  // Multer file-size errors surface as a plain Error with `code === "LIMIT_FILE_SIZE"`.
  if (err && err.code === "LIMIT_FILE_SIZE") {
    logger.warn("file_too_large", { request_id: requestId, endpoint: req.path });
    return res
      .status(400)
      .json(structuredError("FILE_TOO_LARGE", "Uploaded file exceeds the size limit.", requestId));
  }

  logger.error("unhandled_exception", {
    request_id: requestId,
    endpoint: req.path,
    error: err && err.message,
  });
  return res
    .status(500)
    .json(structuredError("INTERNAL_ERROR", "An unexpected error occurred while processing the request.", requestId));
}

function notFoundHandler(req, res) {
  return res.status(404).json(structuredError("NOT_FOUND", "The requested resource does not exist."));
}

module.exports = { errorHandler, notFoundHandler };
