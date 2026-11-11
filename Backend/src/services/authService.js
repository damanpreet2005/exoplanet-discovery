/**
 * Account and session logic. Route handlers stay thin; everything that
 * touches passwords, tokens or sessions lives here.
 */
const { AuthenticationError, ConflictError, ForbiddenError } = require("../errors");
const { hashPassword, verifyPassword, verifyAgainstDummy } = require("../auth/passwords");
const { validateRegistration, validateLogin } = require("../auth/validation");
const tokens = require("../auth/tokens");
const { newCsrfToken, safeEqual } = require("../auth/cookies");
const { makeUserRepository, toPublicUser, duplicateField } = require("../repositories/users");
const { makeSessionRepository } = require("../repositories/sessions");

const INVALID_CREDENTIALS = "Incorrect email/username or password.";

class RefreshRaceError extends AuthenticationError {
  constructor() {
    // Another tab rotated this token a moment ago; the browser already holds
    // the replacement cookie, so the client should simply retry once.
    super("Session was refreshed concurrently. Retry the request.", "REFRESH_RACE");
  }
}

function conflictFor(field) {
  if (field === "email") {
    return new ConflictError("EMAIL_TAKEN", "An account with this email address already exists.", {
      email: "An account with this email address already exists.",
    });
  }
  if (field === "username") {
    return new ConflictError("USERNAME_TAKEN", "This username is already taken.", {
      username: "This username is already taken.",
    });
  }
  return new ConflictError("ACCOUNT_EXISTS", "An account with these details already exists.");
}

function createAuthService({ db, keys, settings, clock = () => new Date() }) {
  const users = makeUserRepository(db);
  const sessions = makeSessionRepository(db);
  const tokenOptions = {
    keys,
    issuer: settings.jwtIssuer,
    audience: settings.jwtAudience,
  };

  async function startSession(user) {
    const now = clock();
    const sessionId = tokens.newSessionId();
    const refreshToken = tokens.newRefreshToken(sessionId);
    const csrfToken = newCsrfToken();
    const session = await sessions.create({
      id: sessionId,
      userId: user._id,
      tokenHash: tokens.hashToken(refreshToken),
      csrfHash: tokens.hashToken(csrfToken),
      now,
      refreshTtlMs: settings.refreshTokenTtlSeconds * 1000,
      maxAgeMs: settings.sessionMaxAgeSeconds * 1000,
    });
    const access = await tokens.issueAccessToken(
      { userId: user._id, sessionId },
      { ...tokenOptions, ttlSeconds: settings.accessTokenTtlSeconds, now }
    );
    return { user, access, refreshToken, csrfToken, expiresAt: session.expires_at };
  }

  return {
    async register(body) {
      const input = validateRegistration(body);
      // Friendly pre-check for clear field errors; the unique indexes remain
      // the real guarantee (a concurrent insert still hits E11000 below).
      const taken = await users.existing(input);
      if (taken.email) throw conflictFor("email");
      if (taken.username) throw conflictFor("username");

      const passwordHash = await hashPassword(input.password);
      let user;
      try {
        user = await users.create({
          name: input.name,
          username: input.username,
          email: input.email,
          passwordHash,
          now: clock(),
        });
      } catch (err) {
        const field = duplicateField(err);
        if (field) throw conflictFor(field);
        throw err;
      }
      return startSession(user);
    },

    async login(body) {
      const { identifier, password, isEmail } = validateLogin(body);
      const user = isEmail ? await users.findByEmail(identifier) : await users.findByUsername(identifier);
      if (!user) {
        await verifyAgainstDummy(password);
        throw new AuthenticationError(INVALID_CREDENTIALS, "INVALID_CREDENTIALS");
      }
      const valid = await verifyPassword(user.password_hash, password);
      // Inactive accounts get the same generic answer as a wrong password.
      if (!valid || !user.is_active) {
        throw new AuthenticationError(INVALID_CREDENTIALS, "INVALID_CREDENTIALS");
      }
      return startSession(user);
    },

    /**
     * Rotates a refresh token. Errors carry `clearCookies` when the client's
     * cookies are definitely dead and should be removed.
     */
    async refresh({ refreshToken, csrfCookie, csrfHeader }) {
      const parsed = tokens.parseRefreshToken(refreshToken);
      if (!parsed) throw Object.assign(new AuthenticationError("Session expired. Please sign in again."), { clearCookies: true });

      const session = await sessions.findById(parsed.sessionId);
      if (!session) throw Object.assign(new AuthenticationError("Session expired. Please sign in again."), { clearCookies: true });

      if (!safeEqual(csrfHeader, csrfCookie) || tokens.hashToken(csrfHeader) !== session.csrf_hash) {
        throw new ForbiddenError("Missing or invalid CSRF token.", "CSRF_FAILED");
      }

      const now = clock();
      const presentedHash = tokens.hashToken(refreshToken);
      const newRefreshToken = tokens.newRefreshToken(session._id);
      const rotated = await sessions.rotate({
        id: session._id,
        presentedHash,
        newHash: tokens.hashToken(newRefreshToken),
        now,
        refreshTtlMs: settings.refreshTokenTtlSeconds * 1000,
      });

      if (!rotated) {
        const expired = session.revoked_at || session.expires_at.getTime() <= now.getTime();
        if (!expired && session.token_hash !== presentedHash) {
          const withinGrace =
            session.prev_token_hash === presentedHash &&
            session.rotated_at &&
            now.getTime() - session.rotated_at.getTime() <= settings.refreshReuseGraceSeconds * 1000;
          if (withinGrace) throw new RefreshRaceError();
          if ((session.retired_hashes || []).includes(presentedHash)) {
            // A token that was already exchanged is being replayed: assume it
            // was stolen and kill the whole token family.
            await sessions.revoke(session._id, "refresh_token_reuse", now);
            throw Object.assign(new AuthenticationError("Session revoked. Please sign in again.", "SESSION_REVOKED"), {
              clearCookies: true,
              reuseDetected: true,
            });
          }
        }
        throw Object.assign(new AuthenticationError("Session expired. Please sign in again."), { clearCookies: true });
      }

      const user = await users.findById(rotated.user_id);
      if (!user || !user.is_active) {
        await sessions.revoke(rotated._id, "account_inactive", now);
        throw Object.assign(new AuthenticationError("Session expired. Please sign in again."), { clearCookies: true });
      }

      const access = await tokens.issueAccessToken(
        { userId: user._id, sessionId: rotated._id },
        { ...tokenOptions, ttlSeconds: settings.accessTokenTtlSeconds, now }
      );
      return { user, access, refreshToken: newRefreshToken, csrfToken: csrfCookie, expiresAt: rotated.expires_at };
    },

    /** Revokes the session the refresh cookie belongs to. Idempotent. */
    async logout({ refreshToken, csrfCookie, csrfHeader }) {
      const parsed = tokens.parseRefreshToken(refreshToken);
      if (!parsed) return;
      const session = await sessions.findById(parsed.sessionId);
      if (!session || session.revoked_at) return;
      if (!safeEqual(csrfHeader, csrfCookie) || tokens.hashToken(csrfHeader) !== session.csrf_hash) {
        throw new ForbiddenError("Missing or invalid CSRF token.", "CSRF_FAILED");
      }
      const presentedHash = tokens.hashToken(refreshToken);
      if (session.token_hash === presentedHash || (session.retired_hashes || []).includes(presentedHash)) {
        await sessions.revoke(session._id, "logout", clock());
      }
    },

    /**
     * Resolves a Bearer token to its user. The session is checked on every
     * call, so logout (or reuse-triggered revocation) takes effect
     * immediately instead of when the access token expires.
     */
    async authenticate(accessToken) {
      let claims;
      try {
        claims = await tokens.verifyAccessToken(accessToken, tokenOptions);
      } catch {
        throw new AuthenticationError("Invalid or expired access token.", "INVALID_TOKEN");
      }
      const active = await sessions.isActive(claims.sid, claims.sub, clock());
      if (!active) throw new AuthenticationError("Session is no longer active.", "INVALID_TOKEN");
      const user = await users.findById(claims.sub);
      if (!user || !user.is_active) throw new AuthenticationError("Invalid or expired access token.", "INVALID_TOKEN");
      return { user, claims };
    },

    toPublicUser,
  };
}

module.exports = { createAuthService, INVALID_CREDENTIALS };
