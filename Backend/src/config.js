/**
 * Centralized configuration for the API gateway, sourced from environment
 * variables. Mirrors the config approach used in ml_service/app/config.py.
 */
require("dotenv").config();

function num(name, fallback) {
  const raw = process.env[name];
  return raw === undefined || raw === "" ? fallback : Number(raw);
}

const config = {
  appEnv: process.env.APP_ENV || "development",
  port: num("PORT", 8000),

  mlServiceUrl: process.env.ML_SERVICE_URL || "http://localhost:8001",
  mlServiceTimeoutMs: num("ML_SERVICE_TIMEOUT", 15) * 1000,
  mlServiceMaxRetries: num("ML_SERVICE_MAX_RETRIES", 2),
  mlServiceRetryBackoffMs: num("ML_SERVICE_RETRY_BACKOFF_SECONDS", 0.5) * 1000,

  csvMaxFileSizeBytes: num("CSV_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024),

  logLevel: process.env.LOG_LEVEL || "info",

  corsAllowOrigins: (process.env.CORS_ALLOW_ORIGINS || "http://localhost:5173,http://localhost:5500")
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean),
};

module.exports = config;
