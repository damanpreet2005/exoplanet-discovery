/**
 * Account endpoints, mounted under /api/v1:
 *
 *   POST /auth/register  -- create account and sign in
 *   POST /auth/login     -- sign in with email or username + password
 *   POST /auth/refresh   -- rotate refresh cookie, get a new access token
 *   POST /auth/logout    -- revoke the session, clear cookies
 *   GET  /auth/me        -- the signed-in user's own profile (protected)
 *
 * Passwords and tokens are never logged: the request logger records only
 * path/status/timing, and no handler here logs a body.
 */
const express = require("express");
const { rateLimit } = require("express-rate-limit");
const { AuthUnavailableError, structuredError } = require("../errors");
const { makeLogger } = require("../logger");
const { makeRequireAuth, makeRequireTrustedOrigin, requireJson } = require("../middleware/auth");
const { setSessionCookies, clearSessionCookies, readCookies } = require("../auth/cookies");
const { createAuthService } = require("../services/authService");

function rateLimitHandler(req, res, next, options) {
  const retryAfter = req.rateLimit?.resetTime
    ? Math.max(1, Math.ceil((req.rateLimit.resetTime.getTime() - Date.now()) / 1000))
    : Math.ceil(options.windowMs / 1000);
  res.setHeader("Retry-After", String(retryAfter));
  res.status(429).json(
    structuredError("RATE_LIMITED", "Too many attempts. Please wait a few minutes and try again.", req.requestId)
  );
}

function limiter({ windowMs, limit, ...rest }) {
  return rateLimit({
    windowMs,
    limit,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    handler: rateLimitHandler,
    ...rest,
  });
}

/**
 * @param {object} deps
 * @param {() => import("mongodb").Db|null} deps.getDb
 * @param {() => object|null} deps.getKeys  signing keys, or null if unconfigured
 * @param {object} deps.settings            config.auth
 * @param {string[]} deps.allowedOrigins    trusted frontend origins
 * @param {object} deps.logLevel
 */
function createAuth({ getDb, getKeys, settings, allowedOrigins, logLevel, clock, service: injectedService }) {
  const logger = makeLogger(logLevel);
  const router = express.Router();

  let cached = { db: null, keys: null, service: null };
  function resolveService() {
    // Tests of non-account routes inject a stand-in service instead of a database.
    if (injectedService) return injectedService;
    const db = getDb();
    const keys = getKeys();
    if (!db || !keys) throw new AuthUnavailableError();
    if (cached.db !== db || cached.keys !== keys) {
      cached = { db, keys, service: createAuthService({ db, keys, settings, clock }) };
    }
    return cached.service;
  }

  const requireAuth = makeRequireAuth(resolveService);
  const trustedOrigin = makeRequireTrustedOrigin(allowedOrigins);
  const json = express.json({ limit: "10kb" });
  const cookieOpts = { secure: settings.cookieSecure };

  function noStore(req, res, next) {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Pragma", "no-cache");
    next();
  }

  function sessionResponse(res, status, result) {
    setSessionCookies(res, result, cookieOpts);
    return res.status(status).json({
      user: resolveService().toPublicUser(result.user),
      access_token: result.access.token,
      token_type: "Bearer",
      expires_in: settings.accessTokenTtlSeconds,
      access_token_expires_at: result.access.expiresAt.toISOString(),
    });
  }

  const loginIpLimiter = limiter({
    windowMs: settings.loginRateLimit.windowMs,
    limit: settings.loginRateLimit.maxPerIp,
  });
  // Counts only failed attempts per targeted account, so a distributed
  // guesser rotating IPs is still capped against any single account.
  const loginAccountLimiter = limiter({
    windowMs: settings.loginRateLimit.windowMs,
    limit: settings.loginRateLimit.maxFailuresPerAccount,
    skipSuccessfulRequests: true,
    keyGenerator: (req) => {
      const raw = typeof req.body?.identifier === "string" ? req.body.identifier : "";
      return `acct:${raw.normalize("NFKC").trim().toLowerCase().slice(0, 254)}`;
    },
  });
  const registerLimiter = limiter({
    windowMs: settings.registerRateLimit.windowMs,
    limit: settings.registerRateLimit.maxPerIp,
  });
  const refreshLimiter = limiter({
    windowMs: settings.refreshRateLimit.windowMs,
    limit: settings.refreshRateLimit.maxPerIp,
  });

  router.use("/auth", noStore);

  router.post("/auth/register", trustedOrigin, requireJson, json, registerLimiter, async (req, res, next) => {
    try {
      const result = await resolveService().register(req.body);
      logger.info("account_registered", { request_id: req.requestId, user_id: result.user._id });
      return sessionResponse(res, 201, result);
    } catch (err) {
      return next(err);
    }
  });

  router.post(
    "/auth/login",
    trustedOrigin,
    requireJson,
    json,
    loginIpLimiter,
    loginAccountLimiter,
    async (req, res, next) => {
      try {
        const result = await resolveService().login(req.body);
        logger.info("login_succeeded", { request_id: req.requestId, user_id: result.user._id });
        return sessionResponse(res, 200, result);
      } catch (err) {
        return next(err);
      }
    }
  );

  router.post("/auth/refresh", trustedOrigin, refreshLimiter, async (req, res, next) => {
    try {
      const { refreshToken, csrfToken } = readCookies(req, cookieOpts);
      const result = await resolveService().refresh({
        refreshToken,
        csrfCookie: csrfToken,
        csrfHeader: req.get("x-csrf-token"),
      });
      return sessionResponse(res, 200, result);
    } catch (err) {
      if (err.clearCookies) clearSessionCookies(res, cookieOpts);
      if (err.reuseDetected) logger.warn("refresh_token_reuse_detected", { request_id: req.requestId });
      return next(err);
    }
  });

  router.post("/auth/logout", trustedOrigin, async (req, res, next) => {
    try {
      const { refreshToken, csrfToken } = readCookies(req, cookieOpts);
      await resolveService().logout({ refreshToken, csrfCookie: csrfToken, csrfHeader: req.get("x-csrf-token") });
      clearSessionCookies(res, cookieOpts);
      return res.status(204).end();
    } catch (err) {
      return next(err);
    }
  });

  router.get("/auth/me", requireAuth, (req, res) => {
    res.status(200).json({ user: resolveService().toPublicUser(req.auth.user) });
  });

  return { router, requireAuth };
}

module.exports = { createAuth };
