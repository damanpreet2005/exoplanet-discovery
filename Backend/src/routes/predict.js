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

const MAX_OBJECT_ID_LENGTH = 64;

// Mirrors the ML service's own light-curve-vs-tabular routing decision
// (app/feature_aliases.py: looks_like_light_curve_header) just closely
// enough to know whether Object ID should be required here -- it is NOT a
// full CSV/ML validation (that stays entirely in the ML service); it only
// decides which validation rule applies at the gateway. A tabular Kepler-
// catalog upload (koi_* columns already present) never needs an Object ID,
// since each row already carries its own stellar parameters.
function looksLikeLightCurveHeader(buffer) {
  const firstLine = buffer.toString("utf8").split(/\r?\n/, 1)[0] || "";
  const columns = firstLine.split(",").map((c) => c.trim().toLowerCase());
  return columns.includes("time") && (columns.includes("flux") || columns.includes("brightness"));
}

// The Random Forest's 17 trained features genuinely include catalog-only
// stellar fields (koi_steff, koi_slogg, koi_srad, ra, dec, koi_kepmag,
// koi_score) that a light curve alone cannot supply -- see the ML service's
// app/feature_engine.py classification. Because of that, Object ID is a
// required field for a light-curve CSV prediction request, not an optional
// extra.
function validateObjectId(rawBody) {
  const value = rawBody && typeof rawBody.object_id === "string" ? rawBody.object_id.trim() : "";
  if (!value) {
    throw new ValidationError(
      "Object ID is required: enter the astronomical catalog identifier (e.g. 'KIC 11904151') " +
        "for the star/object this light curve belongs to, using the 'object_id' form field."
    );
  }
  if (value.length > MAX_OBJECT_ID_LENGTH) {
    throw new ValidationError(`object_id must be at most ${MAX_OBJECT_ID_LENGTH} characters.`);
  }
  return value;
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

    const objectId = looksLikeLightCurveHeader(req.file.buffer) ? validateObjectId(req.body) : undefined;

    const start = process.hrtime.bigint();
    const result = await mlClient.forwardCsvPrediction({
      buffer: req.file.buffer,
      filename: req.file.originalname,
      mimetype: req.file.mimetype,
      requestId,
      objectId,
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
