const express = require("express");
const { ValidationError } = require("../errors");
const mlClient = require("../services/mlClient");
const { makeLogger } = require("../logger");
const config = require("../config");

const logger = makeLogger(config.logLevel);
const router = express.Router();

// Planet characterization recomputation (expert overrides / changed
// assumptions). Forwards the report's `inputs` snapshot plus overrides to the
// ML service's /characterization/recompute endpoint and returns its report
// unmodified -- the gateway never computes or alters characterization
// results itself. The snapshot is a few tens of kB, hence the larger limit.
router.post("/characterization/recompute", express.json({ limit: "1mb" }), async (req, res, next) => {
  const requestId = req.requestId;

  try {
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body) || !body.inputs || typeof body.inputs !== "object") {
      throw new ValidationError("A JSON object with the characterization report's 'inputs' snapshot is required.");
    }
    for (const key of ["overrides", "config", "model_feature_edits"]) {
      if (body[key] !== undefined && (body[key] === null || typeof body[key] !== "object" || Array.isArray(body[key]))) {
        throw new ValidationError(`'${key}' must be a JSON object when provided.`);
      }
    }

    const result = await mlClient.forwardCharacterizationRecompute(body, requestId);
    result.request_id = requestId;
    logger.info("characterization_recompute_logged", { request_id: requestId, status: result.status });
    return res.status(200).json(result);
  } catch (err) {
    return next(err);
  }
});

module.exports = router;
