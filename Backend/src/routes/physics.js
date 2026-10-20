const express = require("express");
const { ValidationError } = require("../errors");
const mlClient = require("../services/mlClient");
const { makeLogger } = require("../logger");
const config = require("../config");

const logger = makeLogger(config.logLevel);
const router = express.Router();

// Stage 2: Physics Validation. Forwards the candidate's named KOI parameters
// to the ML service's /physics-validation endpoint and returns its report
// unmodified -- the gateway never computes or alters physics results itself.
router.post("/physics-validation", express.json(), async (req, res, next) => {
  const requestId = req.requestId;

  try {
    if (!req.body || typeof req.body !== "object" || Array.isArray(req.body) || Object.keys(req.body).length === 0) {
      throw new ValidationError("A non-empty JSON object of named candidate parameters is required.");
    }

    const result = await mlClient.forwardPhysicsValidation(req.body, requestId);
    result.request_id = requestId;
    logger.info("physics_validation_logged", { request_id: requestId, overall_status: result.overall_status });
    return res.status(200).json(result);
  } catch (err) {
    return next(err);
  }
});

module.exports = router;
