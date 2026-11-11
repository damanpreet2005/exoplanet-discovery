import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCurrentUser,
  hasSessionHint,
  loginAccount,
  logoutSession,
  refreshSession,
  registerAccount,
} from "../api/auth";
import { setAuthTokenProvider } from "../api/client";

/**
 * Session state for the whole app.
 *
 * status: "loading" (restoring a session on page load) | "authenticated" |
 * "anonymous". The access token is held in a ref -- memory only, so it never
 * survives a reload and is never written to web storage. A reload restores
 * the session through the HttpOnly refresh cookie instead (POST
 * /auth/refresh), and the token is refreshed again shortly before it expires.
 */
const AuthContext = createContext(null);

// Refresh this long before the access token's expiry.
const REFRESH_LEAD_MS = 60 * 1000;
const CHANNEL_NAME = "exo-auth";

function openChannel() {
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL_NAME);
}

export function AuthProvider({ children }) {
  const [state, setState] = useState(() => ({
    status: hasSessionHint() ? "loading" : "anonymous",
    user: null,
  }));
  const tokenRef = useRef(null);
  const timerRef = useRef(null);
  const inFlightRef = useRef(null);
  const channelRef = useRef(null);
  const refreshRef = useRef(null);

  const clearLocal = useCallback(() => {
    tokenRef.current = null;
    clearTimeout(timerRef.current);
    setState({ status: "anonymous", user: null });
  }, []);

  const applySession = useCallback((body) => {
    const expiresAt = Date.parse(body.access_token_expires_at) || Date.now() + body.expires_in * 1000;
    tokenRef.current = { token: body.access_token, expiresAt };
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(
      () => refreshRef.current?.().catch(() => {}),
      Math.max(5000, expiresAt - Date.now() - REFRESH_LEAD_MS)
    );
    setState({ status: "authenticated", user: body.user });
  }, []);

  /** Rotates the refresh cookie for a new access token. Concurrent callers share one request. */
  const refresh = useCallback(() => {
    if (inFlightRef.current) return inFlightRef.current;
    const run = async () => {
      try {
        let body;
        try {
          body = await refreshSession();
        } catch (err) {
          // Another tab rotated the cookie a moment ago; the browser already
          // holds the new one, so one retry succeeds.
          if (err.code !== "REFRESH_RACE") throw err;
          await new Promise((resolve) => setTimeout(resolve, 250));
          body = await refreshSession();
        }
        applySession(body);
        return body.access_token;
      } catch (err) {
        if (err.status === 401 || err.status === 403) clearLocal();
        else setState((prev) => (prev.status === "loading" ? { status: "anonymous", user: null } : prev));
        throw err;
      } finally {
        inFlightRef.current = null;
      }
    };
    inFlightRef.current = run();
    return inFlightRef.current;
  }, [applySession, clearLocal]);
  refreshRef.current = refresh;

  // Restore the session on page load / reload.
  useEffect(() => {
    if (hasSessionHint()) refresh().catch(() => {});
    return () => clearTimeout(timerRef.current);
  }, [refresh]);

  // Keep other tabs in step: logging out in one signs out all of them.
  useEffect(() => {
    const channel = openChannel();
    channelRef.current = channel;
    if (!channel) return undefined;
    channel.onmessage = (event) => {
      if (event.data === "logout") clearLocal();
      if (event.data === "login") refreshRef.current?.().catch(() => {});
    };
    return () => channel.close();
  }, [clearLocal]);

  const login = useCallback(
    async (credentials) => {
      const body = await loginAccount(credentials);
      applySession(body);
      channelRef.current?.postMessage("login");
      return body.user;
    },
    [applySession]
  );

  const register = useCallback(
    async (details) => {
      const body = await registerAccount(details);
      applySession(body);
      channelRef.current?.postMessage("login");
      return body.user;
    },
    [applySession]
  );

  const logout = useCallback(async () => {
    try {
      await logoutSession();
    } catch {
      // The local session is dropped regardless; the server session also
      // expires on its own.
    } finally {
      clearLocal();
      channelRef.current?.postMessage("logout");
    }
  }, [clearLocal]);

  /** Returns a valid access token, refreshing first if it is missing or about to expire. */
  const getAccessToken = useCallback(async () => {
    const current = tokenRef.current;
    if (current && current.expiresAt - Date.now() > 10 * 1000) return current.token;
    return refresh();
  }, [refresh]);

  // Lets the analysis API client attach the access token to its requests.
  useEffect(() => {
    setAuthTokenProvider({
      peek: () => {
        const current = tokenRef.current;
        return current && current.expiresAt - Date.now() > 30 * 1000 ? current.token : null;
      },
      get: getAccessToken,
      // A 401 from an analysis call: try to renew the session; if that fails
      // the user is signed out and the route guard sends them to Log In.
      onUnauthorized: () => refreshRef.current?.().catch(() => {}),
    });
    return () => setAuthTokenProvider(null);
  }, [getAccessToken]);

  /** Loads the signed-in user's profile from the protected endpoint. */
  const loadProfile = useCallback(async () => {
    let token = await getAccessToken();
    let body;
    try {
      body = await fetchCurrentUser(token);
    } catch (err) {
      if (err.status !== 401) throw err;
      token = await refresh();
      body = await fetchCurrentUser(token);
    }
    setState((prev) => (prev.status === "authenticated" ? { ...prev, user: body.user } : prev));
    return body.user;
  }, [getAccessToken, refresh]);

  const value = useMemo(
    () => ({ ...state, login, register, logout, loadProfile, getAccessToken }),
    [state, login, register, logout, loadProfile, getAccessToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>.");
  return ctx;
}
