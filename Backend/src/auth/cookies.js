/**
 * Authentication cookies.
 *
 *  refresh -- HttpOnly, SameSite=Strict, scoped to /api/v1/auth so it is only
 *             ever sent to the refresh/logout endpoints, never to the ML
 *             routes. Secure (and `__Secure-` prefixed) in production.
 *  csrf    -- readable by the frontend's JS (it must copy it into the
 *             X-CSRF-Token header), SameSite=Strict, `__Host-` prefixed in
 *             production so a sibling subdomain cannot plant one.
 *
 * The access token is never put in a cookie: the frontend keeps it in memory
 * and sends it as a Bearer header.
 */
const crypto = require("crypto");

const REFRESH_COOKIE_PATH = "/api/v1/auth";

function cookieNames(secure) {
  return {
    refresh: secure ? "__Secure-exo_refresh" : "exo_refresh",
    csrf: secure ? "__Host-exo_csrf" : "exo_csrf",
  };
}

function baseOptions(secure) {
  return { secure, sameSite: "strict" };
}

function setSessionCookies(res, { refreshToken, csrfToken, expiresAt }, { secure }) {
  const names = cookieNames(secure);
  const maxAge = Math.max(0, expiresAt.getTime() - Date.now());
  res.cookie(names.refresh, refreshToken, {
    ...baseOptions(secure),
    httpOnly: true,
    path: REFRESH_COOKIE_PATH,
    maxAge,
  });
  res.cookie(names.csrf, csrfToken, { ...baseOptions(secure), httpOnly: false, path: "/", maxAge });
}

function clearSessionCookies(res, { secure }) {
  const names = cookieNames(secure);
  res.clearCookie(names.refresh, { ...baseOptions(secure), httpOnly: true, path: REFRESH_COOKIE_PATH });
  res.clearCookie(names.csrf, { ...baseOptions(secure), httpOnly: false, path: "/" });
}

function readCookies(req, { secure }) {
  const names = cookieNames(secure);
  const cookies = req.cookies || {};
  return { refreshToken: cookies[names.refresh], csrfToken: cookies[names.csrf] };
}

function newCsrfToken() {
  return crypto.randomBytes(32).toString("base64url");
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  return bufA.length === bufB.length && crypto.timingSafeEqual(bufA, bufB);
}

module.exports = {
  REFRESH_COOKIE_PATH,
  cookieNames,
  setSessionCookies,
  clearSessionCookies,
  readCookies,
  newCsrfToken,
  safeEqual,
};
