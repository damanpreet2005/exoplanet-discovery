const express = require("express");
const mlClient = require("../services/mlClient");

const router = express.Router();

/** Liveness: the gateway process is up. */
router.get("/health", (req, res) => {
  res.status(200).json({ status: "alive" });
});

/**
 * Readiness: gateway can serve requests. Reports the ML service dependency
 * status without making the gateway's own readiness fail purely because a
 * downstream dependency is temporarily degraded.
 */
router.get("/ready", async (req, res) => {
  const mlReady = await mlClient.checkReady();
  res.status(200).json({
    status: "ready",
    dependencies: { ml_service: mlReady ? "ready" : "unavailable" },
  });
});

module.exports = router;
