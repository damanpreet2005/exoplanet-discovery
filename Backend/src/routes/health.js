const express = require("express");
const mlClient = require("../services/mlClient");
const mongo = require("../db/mongo");

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
  const [mlReady, dbReady] = await Promise.all([mlClient.checkReady(), mongo.ping()]);
  res.status(200).json({
    status: "ready",
    dependencies: {
      ml_service: mlReady ? "ready" : "unavailable",
      // Account database (sign-in only; the public ML workflow never needs it).
      database: !mongo.isConfigured() ? "not_configured" : dbReady ? "ready" : "unavailable",
    },
  });
});

module.exports = router;
