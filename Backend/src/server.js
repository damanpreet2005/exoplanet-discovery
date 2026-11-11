const { createApp } = require("./app");
const config = require("./config");
const { makeLogger } = require("./logger");
const mongo = require("./db/mongo");

const logger = makeLogger(config.logLevel);
const app = createApp();

// Connects in the background: the gateway serves the public ML workflow
// immediately, and account endpoints answer 503 until MongoDB is reachable.
mongo.connectWithRetry();

app.listen(config.port, () => {
  logger.info("gateway_started", { port: config.port, ml_service_url: config.mlServiceUrl });
});
