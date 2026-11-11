const { AuthenticationError, ForbiddenError, HttpError } = require("../errors");

/**
 * Protects a route. The user is derived solely from the verified Bearer
 * token (sub claim) and the live session it names -- never from an id in the
 * URL, query or body. Sets req.auth = { user, claims }.
 */
function makeRequireAuth(resolveService) {
  return async function requireAuth(req, res, next) {
    try {
      const service = resolveService();
      const header = req.get("authorization") || "";
      const match = /^Bearer ([A-Za-z0-9._~+/-]+=*)$/.exec(header);
      if (!match) throw new AuthenticationError();
      req.auth = await service.authenticate(match[1]);
      return next();
    } catch (err) {
      return next(err);
    }
  };
}

/**
 * Rejects browser requests whose Origin is neither one of the configured
 * trusted frontend origins nor this host itself. Defence in depth on top of
 * SameSite=Strict cookies and the CSRF token.
 */
function makeRequireTrustedOrigin(allowedOrigins) {
  const allowed = new Set(allowedOrigins);
  return function requireTrustedOrigin(req, res, next) {
    const origin = req.get("origin");
    if (!origin) return next();
    let host;
    try {
      host = new URL(origin).host;
    } catch {
      return next(new ForbiddenError("Request origin is not allowed.", "ORIGIN_REJECTED"));
    }
    if (allowed.has(origin) || host === req.get("host")) return next();
    return next(new ForbiddenError("Request origin is not allowed.", "ORIGIN_REJECTED"));
  };
}

/** Account endpoints accept JSON only, which also rules out cross-site HTML form posts. */
function requireJson(req, res, next) {
  if (req.is("application/json")) return next();
  return next(new HttpError(415, "UNSUPPORTED_MEDIA_TYPE", "Requests must be sent as application/json."));
}

module.exports = { makeRequireAuth, makeRequireTrustedOrigin, requireJson };
