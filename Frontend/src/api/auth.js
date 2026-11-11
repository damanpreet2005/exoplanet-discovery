/**
 * Account API calls (Express gateway, /api/v1/auth/*).
 *
 * Credentials model: the short-lived access token lives only in memory (see
 * AuthContext) -- never in localStorage/sessionStorage. The refresh token is
 * an HttpOnly cookie this code cannot read; it only ever reads the
 * non-HttpOnly CSRF cookie to echo it back in the X-CSRF-Token header.
 */
import { API_BASE_URL, generateRequestId } from "./client";

// `__Host-` prefixed in production (Secure cookies), plain name in local dev.
const CSRF_COOKIE_NAMES = ["__Host-exo_csrf", "exo_csrf"];

export function readCsrfToken() {
  if (typeof document === "undefined") return null;
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  for (const name of CSRF_COOKIE_NAMES) {
    const match = cookies.find((c) => c.startsWith(`${name}=`));
    if (match) return decodeURIComponent(match.slice(name.length + 1));
  }
  return null;
}

/** A CSRF cookie exists only while a session might be alive -- lets a cold
 * page load skip a pointless refresh call when nobody is signed in. */
export function hasSessionHint() {
  return Boolean(readCsrfToken());
}

async function send(path, { method = "GET", body, accessToken, csrf = false } = {}) {
  const headers = { "X-Request-Id": generateRequestId() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (csrf) {
    const token = readCsrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw { status: 0, code: "NETWORK_ERROR", message: "Could not reach the server. Check your connection and try again." };
  }
  if (response.status === 204) return null;
  const parsed = await response.json().catch(() => null);
  if (!response.ok) {
    const error = parsed?.error || {};
    throw {
      status: response.status,
      code: error.code || "UNKNOWN_ERROR",
      message: error.message || "The request failed.",
      fields: error.fields || null,
    };
  }
  return parsed;
}

export function registerAccount({ name, username, email, password, confirmPassword }) {
  return send("/api/v1/auth/register", {
    method: "POST",
    body: { name, username, email, password, confirm_password: confirmPassword },
  });
}

export function loginAccount({ identifier, password }) {
  return send("/api/v1/auth/login", { method: "POST", body: { identifier, password } });
}

export function refreshSession() {
  return send("/api/v1/auth/refresh", { method: "POST", csrf: true });
}

export function logoutSession() {
  return send("/api/v1/auth/logout", { method: "POST", csrf: true });
}

export function fetchCurrentUser(accessToken) {
  return send("/api/v1/auth/me", { accessToken });
}
