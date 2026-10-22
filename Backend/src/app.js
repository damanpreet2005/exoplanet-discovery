const express = require("express");
const cors = require("cors");
const config = require("./config");
const { requestContext } = require("./middleware/requestId");
const { errorHandler, notFoundHandler } = require("./middleware/errorHandler");
const healthRouter = require("./routes/health");
const predictRouter = require("./routes/predict");
const schemaRouter = require("./routes/schema");
const physicsRouter = require("./routes/physics");
const characterizationRouter = require("./routes/characterization");

function createApp() {
  const app = express();

  app.use(
    cors({
      origin: config.corsAllowOrigins,
    })
  );
  app.use(requestContext);

  app.use("/api/v1", healthRouter);
  app.use("/api/v1", predictRouter);
  app.use("/api/v1", schemaRouter);
  app.use("/api/v1", physicsRouter);
  app.use("/api/v1", characterizationRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

module.exports = { createApp };
