const { createApp } = require("./app");
const config = require("./config");
const { makeLogger } = require("./logger");

const logger = makeLogger(config.logLevel);
const app = createApp();

app.listen(config.port, () => {
  logger.info("gateway_started", { port: config.port, ml_service_url: config.mlServiceUrl });
});
