/**
 * Centralized configuration for the API gateway, sourced from environment
 * variables. Mirrors the config approach used in ml_service/app/config.py.
 */
require("dotenv").config();

function num(name, fallback) {
  const raw = process.env[name];
  return raw === undefined || raw === "" ? fallback : Number(raw);
}

function bool(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
}

const appEnv = process.env.APP_ENV || "development";
const isProduction = appEnv === "production";

/**
 * Express `trust proxy` setting. Defaults to trusting only private/loopback
 * hops (the nginx and cloudflared containers on the Docker network), so
 * req.ip -- used as the rate-limit key -- is the real client address rather
 * than a header any client could forge.
 */
function trustProxy() {
  const raw = process.env.TRUST_PROXY;
  if (raw === undefined || raw === "") return "loopback, linklocal, uniquelocal";
  if (/^\d+$/.test(raw)) return Number(raw);
  if (raw === "true" || raw === "false") return raw === "true";
  return raw;
}

const config = {
  appEnv,
  isProduction,
  port: num("PORT", 8000),

  mlServiceUrl: process.env.ML_SERVICE_URL || "http://localhost:8001",
  mlServiceTimeoutMs: num("ML_SERVICE_TIMEOUT", 15) * 1000,
  // Light-curve analysis (transit search, transit-model fits, profile
  // likelihood, catalogue lookups) is CPU-bound and legitimately takes far
  // longer than a single prediction, so it has its own budget.
  mlServiceAnalysisTimeoutMs: num("ML_SERVICE_ANALYSIS_TIMEOUT", 60) * 1000,
  mlServiceMaxRetries: num("ML_SERVICE_MAX_RETRIES", 2),
  mlServiceRetryBackoffMs: num("ML_SERVICE_RETRY_BACKOFF_SECONDS", 0.5) * 1000,

  csvMaxFileSizeBytes: num("CSV_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024),

  logLevel: process.env.LOG_LEVEL || "info",

  corsAllowOrigins: (process.env.CORS_ALLOW_ORIGINS || "http://localhost:5173,http://localhost:5500")
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean),

  trustProxy: trustProxy(),

  // ---- User accounts (MongoDB) ----
  // Credentials are supplied separately from the URI so a password with
  // URL-special characters never needs escaping, and so the URI itself can
  // be logged safely.
  mongo: {
    uri: process.env.MONGODB_URI || "",
    dbName: process.env.MONGODB_DB_NAME || "exodiscovery",
    username: process.env.MONGODB_USERNAME || "",
    password: process.env.MONGODB_PASSWORD || "",
    authSource: process.env.MONGODB_AUTH_SOURCE || "",
  },

  // ---- Authentication ----
  auth: {
    // Ed25519 private key (PKCS#8 PEM). Either inline (literal "\n" escapes
    // allowed so it fits on one .env line) or a path to a mounted file. Never
    // generated at startup: a regenerated key would silently invalidate
    // every issued token on each restart.
    jwtPrivateKey: process.env.JWT_PRIVATE_KEY || "",
    jwtPrivateKeyFile: process.env.JWT_PRIVATE_KEY_FILE || "",
    jwtIssuer: process.env.JWT_ISSUER || "https://exodiscovery.online",
    jwtAudience: process.env.JWT_AUDIENCE || "exodiscovery-web",
    accessTokenTtlSeconds: num("ACCESS_TOKEN_TTL_SECONDS", 600),
    // Sliding refresh lifetime (extended on each rotation), capped by an
    // absolute session lifetime after which the user must sign in again.
    refreshTokenTtlSeconds: num("REFRESH_TOKEN_TTL_SECONDS", 7 * 24 * 3600),
    sessionMaxAgeSeconds: num("SESSION_MAX_AGE_SECONDS", 30 * 24 * 3600),
    // Window in which presenting the just-rotated refresh token (e.g. two
    // tabs refreshing at once) is answered with a retryable 401 instead of
    // being treated as token theft.
    refreshReuseGraceSeconds: num("REFRESH_REUSE_GRACE_SECONDS", 10),
    cookieSecure: bool("COOKIE_SECURE", isProduction),

    loginRateLimit: {
      windowMs: num("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 15 * 60) * 1000,
      maxPerIp: num("LOGIN_RATE_LIMIT_MAX_PER_IP", 20),
      maxFailuresPerAccount: num("LOGIN_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT", 5),
    },
    registerRateLimit: {
      windowMs: num("REGISTER_RATE_LIMIT_WINDOW_SECONDS", 60 * 60) * 1000,
      maxPerIp: num("REGISTER_RATE_LIMIT_MAX_PER_IP", 10),
    },
    refreshRateLimit: {
      windowMs: num("REFRESH_RATE_LIMIT_WINDOW_SECONDS", 15 * 60) * 1000,
      maxPerIp: num("REFRESH_RATE_LIMIT_MAX_PER_IP", 120),
    },
  },
};

module.exports = config;
