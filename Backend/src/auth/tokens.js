/**
 * Access tokens: short-lived EdDSA (Ed25519) JWTs carrying only
 *   sub -- the internal user id
 *   sid -- the session (refresh-token family) id, so revocation is checkable
 * plus the standard iss / aud / iat / exp. No names, emails or other personal
 * data are ever placed in a token.
 *
 * Refresh tokens: opaque `<session id>.<256-bit random secret>` strings. The
 * server stores only a SHA-256 hash of each one.
 */
const crypto = require("crypto");
const fs = require("fs");
const { SignJWT, jwtVerify } = require("jose");

const ALGORITHM = "EdDSA";

/**
 * Loads the Ed25519 signing key from configuration. Returns null when no key
 * is configured -- the caller disables account features rather than
 * inventing a key, because a key generated at startup would change on every
 * restart and silently sign everyone out.
 */
function loadSigningKeys(authConfig) {
  let pem = authConfig.jwtPrivateKey;
  if (!pem && authConfig.jwtPrivateKeyFile) pem = fs.readFileSync(authConfig.jwtPrivateKeyFile, "utf8");
  if (!pem) return null;
  return keysFromPem(pem.replace(/\\n/g, "\n"));
}

function keysFromPem(pem) {
  const privateKey = crypto.createPrivateKey(pem);
  if (privateKey.asymmetricKeyType !== "ed25519") {
    throw new Error("JWT signing key must be an Ed25519 private key.");
  }
  const publicKey = crypto.createPublicKey(privateKey);
  const spki = publicKey.export({ type: "spki", format: "der" });
  const kid = crypto.createHash("sha256").update(spki).digest("base64url").slice(0, 16);
  return { privateKey, publicKey, kid };
}

function generateSigningKeys() {
  const { privateKey } = crypto.generateKeyPairSync("ed25519");
  return keysFromPem(privateKey.export({ type: "pkcs8", format: "pem" }));
}

async function issueAccessToken({ userId, sessionId }, { keys, issuer, audience, ttlSeconds, now = new Date() }) {
  const iat = Math.floor(now.getTime() / 1000);
  const exp = iat + ttlSeconds;
  const token = await new SignJWT({ sid: sessionId })
    .setProtectedHeader({ alg: ALGORITHM, typ: "JWT", kid: keys.kid })
    .setSubject(userId)
    .setIssuer(issuer)
    .setAudience(audience)
    .setIssuedAt(iat)
    .setExpirationTime(exp)
    .sign(keys.privateKey);
  return { token, expiresAt: new Date(exp * 1000) };
}

/**
 * Verifies signature, algorithm (EdDSA only -- "none", HS* and RS* are all
 * rejected), issuer, audience, expiry and the presence of sub/sid. Throws on
 * any failure.
 */
async function verifyAccessToken(token, { keys, issuer, audience }) {
  const { payload } = await jwtVerify(token, keys.publicKey, {
    algorithms: [ALGORITHM],
    issuer,
    audience,
    typ: "JWT",
    requiredClaims: ["sub", "sid", "iat", "exp"],
    clockTolerance: 5,
  });
  if (typeof payload.sub !== "string" || typeof payload.sid !== "string") {
    throw new Error("Malformed token claims.");
  }
  return payload;
}

function newSessionId() {
  return crypto.randomBytes(16).toString("base64url");
}

function newRefreshToken(sessionId) {
  return `${sessionId}.${crypto.randomBytes(32).toString("base64url")}`;
}

/** Returns { sessionId } for a well-formed refresh token, else null. */
function parseRefreshToken(token) {
  if (typeof token !== "string" || token.length > 200) return null;
  const match = /^([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})$/.exec(token);
  return match ? { sessionId: match[1] } : null;
}

function hashToken(token) {
  return crypto.createHash("sha256").update(token).digest("hex");
}

module.exports = {
  ALGORITHM,
  loadSigningKeys,
  keysFromPem,
  generateSigningKeys,
  issueAccessToken,
  verifyAccessToken,
  newSessionId,
  newRefreshToken,
  parseRefreshToken,
  hashToken,
};
