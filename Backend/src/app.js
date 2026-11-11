const express = require("express");
const cors = require("cors");
const cookieParser = require("cookie-parser");
const config = require("./config");
const { makeLogger } = require("./logger");
const { requestContext } = require("./middleware/requestId");
const { errorHandler, notFoundHandler } = require("./middleware/errorHandler");
const mongo = require("./db/mongo");
const { loadSigningKeys } = require("./auth/tokens");
const healthRouter = require("./routes/health");
const predictRouter = require("./routes/predict");
const schemaRouter = require("./routes/schema");
const physicsRouter = require("./routes/physics");
const characterizationRouter = require("./routes/characterization");
const { createAuth } = require("./routes/auth");
const { createPredictionHistory } = require("./routes/history");

const logger = makeLogger(config.logLevel);

/** Loads the JWT signing key once. A bad/missing key disables accounts, not the gateway. */
function loadKeysOrNull() {
  try {
    const keys = loadSigningKeys(config.auth);
    if (!keys) logger.warn("jwt_key_not_configured", { detail: "Account features are disabled." });
    return keys;
  } catch (err) {
    logger.error("jwt_key_invalid", { error: err.message });
    return null;
  }
}

/**
 * @param {object} [options]
 * @param {object} [options.auth] overrides for the account subsystem (tests):
 *   { getDb, getKeys, settings, clock, service }
 * @param {object} [options.history] overrides for prediction history (tests): { getDb }
 */
function createApp(options = {}) {
  const app = express();
  app.set("trust proxy", config.trustProxy);
  app.disable("x-powered-by");

  const authOptions = options.auth || {};
  let defaultKeys;
  const getKeys =
    authOptions.getKeys ||
    (() => {
      if (defaultKeys === undefined) defaultKeys = loadKeysOrNull();
      return defaultKeys;
    });

  app.use(
    cors({
      origin: config.corsAllowOrigins,
      // Lets the dev frontend (a different port) send the refresh cookie.
      // Only the explicit allow-list above is ever granted credentials.
      credentials: true,
    })
  );
  app.use(requestContext);
  app.use(cookieParser());

  const auth = createAuth({
    getDb: authOptions.getDb || mongo.getDb,
    getKeys,
    settings: authOptions.settings || config.auth,
    allowedOrigins: config.corsAllowOrigins,
    logLevel: config.logLevel,
    clock: authOptions.clock,
    service: authOptions.service,
  });
  app.locals.requireAuth = auth.requireAuth;

  const history = createPredictionHistory({
    getDb: (options.history && options.history.getDb) || mongo.getDb,
    logLevel: config.logLevel,
  });
  app.locals.recordPredictionRun = history.recordRun;
  app.locals.recordManualPredictionRun = history.recordManualRun;

  // Running an analysis requires a signed-in user. Enforced here, on the
  // gateway, so calling the API directly cannot bypass the frontend's login
  // gate. Health/readiness and the account endpoints stay public.
  app.use(
    [
      "/api/v1/predict",
      "/api/v1/physics-validation",
      "/api/v1/characterization",
      "/api/v1/feature-schema",
      "/api/v1/history",
    ],
    auth.requireAuth
  );

  app.use("/api/v1", healthRouter);
  app.use("/api/v1", predictRouter);
  app.use("/api/v1", schemaRouter);
  app.use("/api/v1", physicsRouter);
  app.use("/api/v1", characterizationRouter);
  app.use("/api/v1", history.router);
  app.use("/api/v1", auth.router);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

module.exports = { createApp };
