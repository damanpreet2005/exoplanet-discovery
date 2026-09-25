const { randomUUID } = require("crypto");
const { makeLogger } = require("../logger");
const config = require("../config");

const logger = makeLogger(config.logLevel);

/** Assigns/propagates a request correlation ID and logs request timing. */
function requestContext(req, res, next) {
  const requestId = req.headers["x-request-id"] || randomUUID();
  req.requestId = requestId;
  res.setHeader("x-request-id", requestId);

  const start = process.hrtime.bigint();
  res.on("finish", () => {
    const durationMs = Number(process.hrtime.bigint() - start) / 1e6;
    logger.info("request_completed", {
      request_id: requestId,
      endpoint: req.path,
      duration_ms: durationMs,
      status_code: res.statusCode,
    });
  });

  next();
}

module.exports = { requestContext };
