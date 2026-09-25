const express = require("express");
const multer = require("multer");
const config = require("../config");
const { ValidationError } = require("../errors");
const mlClient = require("../services/mlClient");
const { makeLogger } = require("../logger");

const logger = makeLogger(config.logLevel);
const router = express.Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.csvMaxFileSizeBytes },
});

function logPredictionEvent(requestId, durationMs, statusCode) {
  // Background-style logging: fired after the response, records metadata
  // only (never raw CSV content).
  logger.info("gateway_prediction_logged", {
    request_id: requestId,
    duration_ms: durationMs,
    status_code: statusCode,
  });
}

router.post("/predict", upload.single("file"), async (req, res, next) => {
  const requestId = req.requestId;

  try {
    if (!req.file || !req.file.buffer || req.file.buffer.length === 0) {
      throw new ValidationError(
        "A non-empty light-curve CSV file (with 'time' and 'flux'/'brightness' columns) " +
          "must be uploaded using the 'file' form field."
      );
    }

    const start = process.hrtime.bigint();
    const result = await mlClient.forwardCsvPrediction({
      buffer: req.file.buffer,
      filename: req.file.originalname,
      mimetype: req.file.mimetype,
      requestId,
    });
    const durationMs = Number(process.hrtime.bigint() - start) / 1e6;

    result.request_id = requestId;
    setImmediate(() => logPredictionEvent(requestId, durationMs, 200));
    return res.status(200).json(result);
  } catch (err) {
    return next(err);
  }
});

// Mode B: manual entry of the 17 model parameters (named/aliased fields),
// forwarded as JSON to the ML service's POST /predict.
router.post("/predict/manual", express.json(), async (req, res, next) => {
  const requestId = req.requestId;

  try {
    if (!req.body || typeof req.body !== "object" || Array.isArray(req.body) || Object.keys(req.body).length === 0) {
      throw new ValidationError("A non-empty JSON object of named model parameters is required.");
    }

    const start = process.hrtime.bigint();
    const result = await mlClient.forwardNamedPrediction(req.body, requestId);
    const durationMs = Number(process.hrtime.bigint() - start) / 1e6;

    result.request_id = requestId;
    setImmediate(() => logPredictionEvent(requestId, durationMs, 200));
    return res.status(200).json(result);
  } catch (err) {
    return next(err);
  }
});

module.exports = router;
