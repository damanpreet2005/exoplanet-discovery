/**
 * Account system tests against a real (in-memory) MongoDB, so unique
 * indexes, the $jsonSchema validator and atomic rotation are exercised for
 * real rather than mocked.
 */
jest.mock("../src/services/mlClient");
const crypto = require("crypto");
const request = require("supertest");
const { MongoMemoryServer } = require("mongodb-memory-server");
const { MongoClient } = require("mongodb");
const { SignJWT } = require("jose");
const { createApp } = require("../src/app");
const config = require("../src/config");
const { initSchema } = require("../src/db/mongo");
const tokens = require("../src/auth/tokens");
const { makeUserRepository } = require("../src/repositories/users");

jest.setTimeout(60000);

let mongod;
let client;
let db;
const keys = tokens.generateSigningKeys();

const PASSWORD = "Nebula-Drift-42";
const BASE_USER = {
  name: "Ada Lovelace",
  username: "ada_l",
  email: "ada@example.com",
  password: PASSWORD,
  confirm_password: PASSWORD,
};

beforeAll(async () => {
  mongod = await MongoMemoryServer.create();
  client = await MongoClient.connect(mongod.getUri());
  db = client.db("exodiscovery_test");
  await initSchema(db);
}, 120000);

afterAll(async () => {
  if (client) await client.close();
  if (mongod) await mongod.stop();
});

beforeEach(async () => {
  await db.collection("users").deleteMany({});
  await db.collection("sessions").deleteMany({});
});

let logSpy;
beforeEach(() => {
  logSpy = jest.spyOn(console, "log").mockImplementation(() => {});
});
afterEach(() => logSpy.mockRestore());

function makeApp({ settings = {}, clock, getKeys, getDb } = {}) {
  return createApp({
    auth: {
      getDb: getDb || (() => db),
      getKeys: getKeys || (() => keys),
      settings: { ...config.auth, cookieSecure: false, ...settings },
      clock,
    },
  });
}

/** Parses Set-Cookie headers into { name: { value, attrs } }. */
function parseSetCookies(res) {
  const out = {};
  for (const raw of res.headers["set-cookie"] || []) {
    const [pair, ...attrs] = raw.split(";").map((s) => s.trim());
    const eq = pair.indexOf("=");
    out[pair.slice(0, eq)] = { value: decodeURIComponent(pair.slice(eq + 1)), attrs: attrs.map((a) => a.toLowerCase()), raw };
  }
  return out;
}

function sessionFrom(res) {
  const cookies = parseSetCookies(res);
  return {
    refresh: cookies.exo_refresh?.value,
    csrf: cookies.exo_csrf?.value,
    accessToken: res.body.access_token,
  };
}

function cookieHeader(session) {
  return `exo_refresh=${session.refresh}; exo_csrf=${session.csrf}`;
}

function register(app, overrides = {}) {
  return request(app).post("/api/v1/auth/register").send({ ...BASE_USER, ...overrides });
}

function login(app, identifier = BASE_USER.email, password = PASSWORD) {
  return request(app).post("/api/v1/auth/login").send({ identifier, password });
}

function refresh(app, session) {
  return request(app).post("/api/v1/auth/refresh").set("Cookie", cookieHeader(session)).set("X-CSRF-Token", session.csrf);
}

function me(app, accessToken) {
  return request(app).get("/api/v1/auth/me").set("Authorization", `Bearer ${accessToken}`);
}

function expectNoSecrets(body) {
  const text = JSON.stringify(body);
  expect(text).not.toMatch(/password_hash/);
  expect(text).not.toMatch(/\$argon2/);
  expect(text).not.toContain(PASSWORD);
}

// ---------------------------------------------------------------- registration

describe("registration", () => {
  test("creates an account, signs the user in, and returns only public fields", async () => {
    const app = makeApp();
    const res = await register(app, { email: "  Ada@Example.COM ", username: "Ada_L", name: "  Ada   Lovelace " });
    expect(res.status).toBe(201);
    expect(res.body.user).toEqual({
      id: expect.any(String),
      name: "Ada Lovelace",
      username: "ada_l",
      email: "ada@example.com",
      profile_picture: null,
      created_at: expect.any(String),
      updated_at: expect.any(String),
      is_active: true,
    });
    expect(res.body.token_type).toBe("Bearer");
    expect(typeof res.body.access_token).toBe("string");
    expectNoSecrets(res.body);

    const cookies = parseSetCookies(res);
    expect(cookies.exo_refresh.attrs).toEqual(expect.arrayContaining(["httponly", "samesite=strict", "path=/api/v1/auth"]));
    expect(cookies.exo_csrf.attrs).not.toContain("httponly");
    expect(res.headers["cache-control"]).toBe("no-store");
  });

  test("stores an Argon2id hash, never the plaintext password", async () => {
    await register(makeApp());
    const doc = await db.collection("users").findOne({ email: "ada@example.com" });
    expect(doc.password_hash).toMatch(/^\$argon2id\$v=19\$/);
    const params = Object.fromEntries(doc.password_hash.split("$")[3].split(",").map((kv) => kv.split("=")));
    expect(params).toEqual({ m: "19456", t: "2", p: "1" });
    expect(JSON.stringify(doc)).not.toContain(PASSWORD);
  });

  test("rejects a duplicate email, case-insensitively", async () => {
    const app = makeApp();
    await register(app);
    const res = await register(app, { username: "someone_else", email: "ADA@example.com" });
    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("EMAIL_TAKEN");
    expect(res.body.error.fields.email).toBeDefined();
  });

  test("rejects a duplicate username, case-insensitively", async () => {
    const app = makeApp();
    await register(app);
    const res = await register(app, { username: "ADA_L", email: "other@example.com" });
    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("USERNAME_TAKEN");
  });

  test("uniqueness holds under concurrent sign-ups (enforced by the database index)", async () => {
    const app = makeApp();
    const results = await Promise.all([
      register(app, { username: "racer_one" }),
      register(app, { username: "racer_two" }),
      register(app, { username: "racer_three" }),
    ]);
    const statuses = results.map((r) => r.status).sort();
    expect(statuses).toEqual([201, 409, 409]);
    expect(await db.collection("users").countDocuments({ email: "ada@example.com" })).toBe(1);
  });

  test("the database itself rejects duplicates and non-Argon2id password hashes", async () => {
    const users = makeUserRepository(db);
    const hash = "$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHQ$aGFzaGhhc2g";
    await users.create({ name: "A", username: "dup_user", email: "dup@example.com", passwordHash: hash });
    await expect(
      users.create({ name: "B", username: "dup_user", email: "dup2@example.com", passwordHash: hash })
    ).rejects.toMatchObject({ code: 11000 });
    await expect(
      users.create({ name: "C", username: "plain_user", email: "plain@example.com", passwordHash: "hunter2hunter2" })
    ).rejects.toMatchObject({ code: 121 }); // DocumentValidationFailure
  });

  test.each([
    ["missing everything", {}, ["name", "username", "email", "password"]],
    ["bad email", { email: "not-an-email" }, ["email"]],
    ["bad username", { username: "a b" }, ["username"]],
    ["short password", { password: "Short1", confirm_password: "Short1" }, ["password"]],
    ["password without digits", { password: "OnlyLettersHere", confirm_password: "OnlyLettersHere" }, ["password"]],
    ["password containing username", { password: "ada_l-2024-xyz", confirm_password: "ada_l-2024-xyz" }, ["password"]],
    ["mismatched confirmation", { confirm_password: "Different-Pass-99" }, ["confirm_password"]],
    ["non-string types", { name: 42, username: ["x"], email: { $ne: "" } }, ["name", "username", "email"]],
  ])("rejects invalid input: %s", async (_label, overrides, expectedFields) => {
    const body = Object.keys(overrides).length === 0 ? {} : { ...BASE_USER, ...overrides };
    const res = await request(makeApp()).post("/api/v1/auth/register").send(body);
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("VALIDATION_ERROR");
    for (const field of expectedFields) expect(res.body.error.fields[field]).toBeDefined();
    expect(JSON.stringify(res.body)).not.toContain(body.password || "\u0000");
    expect(await db.collection("users").countDocuments()).toBe(0);
  });

  test("rejects non-JSON bodies", async () => {
    const res = await request(makeApp()).post("/api/v1/auth/register").type("form").send(BASE_USER);
    expect(res.status).toBe(415);
  });

  test("never logs the password", async () => {
    const app = makeApp();
    await register(app);
    await login(app, BASE_USER.email, "Wrong-Password-1");
    await login(app);
    const logged = logSpy.mock.calls.map((c) => c.join(" ")).join("\n");
    expect(logged).not.toContain(PASSWORD);
    expect(logged).not.toContain("Wrong-Password-1");
  });
});

// ---------------------------------------------------------------- login

describe("login", () => {
  test("succeeds with email or (case-insensitive) username", async () => {
    const app = makeApp();
    await register(app);
    const byEmail = await login(app, "ADA@example.com");
    expect(byEmail.status).toBe(200);
    expect(byEmail.body.user.username).toBe("ada_l");
    expectNoSecrets(byEmail.body);

    const byUsername = await login(app, "Ada_L");
    expect(byUsername.status).toBe(200);
  });

  test("issues a short-lived EdDSA access token with a minimal payload", async () => {
    const app = makeApp();
    const res = await register(app);
    const [headerB64, payloadB64] = res.body.access_token.split(".");
    const header = JSON.parse(Buffer.from(headerB64, "base64url").toString());
    const payload = JSON.parse(Buffer.from(payloadB64, "base64url").toString());
    expect(header.alg).toBe("EdDSA");
    expect(Object.keys(payload).sort()).toEqual(["aud", "exp", "iat", "iss", "sid", "sub"]);
    expect(payload.sub).toBe(res.body.user.id);
    expect(payload.exp - payload.iat).toBe(600);
    expect(res.body.expires_in).toBe(600);
  });

  test("wrong password and unknown account produce the identical generic error", async () => {
    const app = makeApp();
    await register(app);
    const wrong = await login(app, BASE_USER.email, "Wrong-Password-1");
    const unknown = await login(app, "nobody@example.com", "Wrong-Password-1");
    const unknownUser = await login(app, "nobody", "Wrong-Password-1");
    for (const res of [wrong, unknown, unknownUser]) {
      expect(res.status).toBe(401);
      expect(res.body.error.code).toBe("INVALID_CREDENTIALS");
      expect(res.headers["set-cookie"]).toBeUndefined();
    }
    expect(wrong.body.error.message).toBe(unknown.body.error.message);
    expect(unknown.body.error.message).toBe(unknownUser.body.error.message);
  });

  test("an inactive account cannot sign in and gets the same generic error", async () => {
    const app = makeApp();
    await register(app);
    await db.collection("users").updateOne({ username: "ada_l" }, { $set: { is_active: false } });
    const res = await login(app);
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("INVALID_CREDENTIALS");
  });

  test("rejects malformed login bodies", async () => {
    const res = await request(makeApp()).post("/api/v1/auth/login").send({ identifier: { $gt: "" }, password: 1 });
    expect(res.status).toBe(422);
  });

  test("rate-limits repeated failures against one account, even with the right password afterwards", async () => {
    const app = makeApp({ settings: { loginRateLimit: { windowMs: 60000, maxPerIp: 100, maxFailuresPerAccount: 3 } } });
    await register(app);
    for (let i = 0; i < 3; i += 1) {
      expect((await login(app, BASE_USER.email, "Wrong-Password-1")).status).toBe(401);
    }
    const blocked = await login(app);
    expect(blocked.status).toBe(429);
    expect(blocked.body.error.code).toBe("RATE_LIMITED");
    expect(Number(blocked.headers["retry-after"])).toBeGreaterThan(0);
    // Another account from the same client is unaffected.
    expect((await login(app, "someone@example.com", "Wrong-Password-1")).status).toBe(401);
  });

  test("rate-limits login attempts per client IP", async () => {
    const app = makeApp({ settings: { loginRateLimit: { windowMs: 60000, maxPerIp: 2, maxFailuresPerAccount: 100 } } });
    expect((await login(app, "a@example.com", "x")).status).toBe(401);
    expect((await login(app, "b@example.com", "x")).status).toBe(401);
    expect((await login(app, "c@example.com", "x")).status).toBe(429);
  });

  test("rate-limits registration per client IP", async () => {
    const app = makeApp({ settings: { registerRateLimit: { windowMs: 60000, maxPerIp: 1 } } });
    expect((await register(app)).status).toBe(201);
    expect((await register(app, { username: "second", email: "second@example.com" })).status).toBe(429);
  });
});

// ---------------------------------------------------------------- tokens

describe("access-token validation", () => {
  let app;
  let session;
  beforeEach(async () => {
    app = makeApp();
    session = sessionFrom(await register(app));
  });

  async function forge(claims, { key = keys.privateKey, alg = "EdDSA", header = {} } = {}) {
    const now = Math.floor(Date.now() / 1000);
    const decoded = JSON.parse(Buffer.from(session.accessToken.split(".")[1], "base64url").toString());
    return new SignJWT({ sid: decoded.sid, ...claims })
      .setProtectedHeader({ alg, typ: "JWT", ...header })
      .setSubject(claims.sub || decoded.sub)
      .setIssuer(claims.iss || config.auth.jwtIssuer)
      .setAudience(claims.aud || config.auth.jwtAudience)
      .setIssuedAt(now)
      .setExpirationTime(claims.exp || now + 600)
      .sign(key);
  }

  test("a valid token reaches the protected endpoint", async () => {
    expect((await me(app, session.accessToken)).status).toBe(200);
    expect((await me(app, await forge({}))).status).toBe(200);
  });

  test("missing or malformed Authorization is rejected", async () => {
    expect((await request(app).get("/api/v1/auth/me")).status).toBe(401);
    expect((await request(app).get("/api/v1/auth/me").set("Authorization", "Basic abc")).status).toBe(401);
    expect((await me(app, "not.a.jwt")).status).toBe(401);
    const res = await request(app).get("/api/v1/auth/me");
    expect(res.headers["www-authenticate"]).toMatch(/^Bearer/);
  });

  test("an expired token is rejected", async () => {
    const past = new Date(Date.now() - 30 * 60 * 1000);
    const pastApp = makeApp({ clock: () => past });
    const old = sessionFrom(await login(pastApp));
    const res = await me(app, old.accessToken);
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("INVALID_TOKEN");
  });

  test("a token signed with a different key is rejected", async () => {
    const other = tokens.generateSigningKeys();
    expect((await me(app, await forge({}, { key: other.privateKey }))).status).toBe(401);
  });

  test("wrong issuer or audience is rejected", async () => {
    expect((await me(app, await forge({ iss: "https://evil.example" }))).status).toBe(401);
    expect((await me(app, await forge({ aud: "some-other-app" }))).status).toBe(401);
  });

  test("non-EdDSA algorithms (HS256, none) are rejected", async () => {
    const hs = await forge({}, { key: new TextEncoder().encode("x".repeat(32)), alg: "HS256" });
    expect((await me(app, hs)).status).toBe(401);
    const [, payload] = session.accessToken.split(".");
    const none = `${Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url")}.${payload}.`;
    expect((await me(app, none)).status).toBe(401);
  });

  test("a tampered payload is rejected", async () => {
    const [h, p, s] = session.accessToken.split(".");
    const claims = JSON.parse(Buffer.from(p, "base64url").toString());
    claims.sub = crypto.randomUUID();
    const tampered = `${h}.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.${s}`;
    expect((await me(app, tampered)).status).toBe(401);
  });

  test("auth endpoints answer 503 (not 500) when the database or key is unavailable", async () => {
    expect((await login(makeApp({ getDb: () => null }))).status).toBe(503);
    const res = await login(makeApp({ getKeys: () => null }));
    expect(res.status).toBe(503);
    expect(res.body.error.code).toBe("AUTH_UNAVAILABLE");
  });
});

// ---------------------------------------------------------------- refresh & logout

describe("refresh-token rotation and session persistence", () => {
  test("a page reload (cookies only, no access token in memory) restores the session", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    // Simulated reload: the in-memory access token is gone; only cookies remain.
    const refreshed = await refresh(app, session);
    expect(refreshed.status).toBe(200);
    expectNoSecrets(refreshed.body);
    const profile = await me(app, refreshed.body.access_token);
    expect(profile.status).toBe(200);
    expect(profile.body.user.email).toBe("ada@example.com");
  });

  test("each refresh rotates the refresh token", async () => {
    const app = makeApp();
    const first = sessionFrom(await register(app));
    const res = await refresh(app, first);
    const second = { ...first, ...sessionFrom(res), csrf: first.csrf };
    expect(second.refresh).toBeDefined();
    expect(second.refresh).not.toBe(first.refresh);
    expect((await refresh(app, second)).status).toBe(200);
  });

  test("reusing a rotated refresh token revokes the whole session", async () => {
    let now = Date.now();
    const app = makeApp({ clock: () => new Date(now) });
    const first = sessionFrom(await register(app));
    const second = { ...sessionFrom(await refresh(app, first)), csrf: first.csrf };
    const secondAccess = (await refresh(app, second)).body.access_token; // rotates again -> third

    now += 60 * 1000; // past the concurrent-refresh grace window
    const replay = await refresh(app, first);
    expect(replay.status).toBe(401);
    expect(replay.body.error.code).toBe("SESSION_REVOKED");
    expect(parseSetCookies(replay).exo_refresh.raw).toMatch(/Expires=Thu, 01 Jan 1970/);

    const sessionDoc = await db.collection("sessions").findOne({});
    expect(sessionDoc.revoked_reason).toBe("refresh_token_reuse");
    // Every token in the family is now dead, including access tokens.
    expect((await me(app, secondAccess)).status).toBe(401);
  });

  test("a concurrent refresh with the just-rotated token is retryable, not treated as theft", async () => {
    const app = makeApp();
    const first = sessionFrom(await register(app));
    expect((await refresh(app, first)).status).toBe(200);
    const raced = await refresh(app, first);
    expect(raced.status).toBe(401);
    expect(raced.body.error.code).toBe("REFRESH_RACE");
    expect(raced.headers["set-cookie"]).toBeUndefined(); // must not wipe the winner's new cookie
    expect((await db.collection("sessions").findOne({})).revoked_at).toBeNull();
  });

  test("refresh requires the session's CSRF token", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    const noHeader = await request(app).post("/api/v1/auth/refresh").set("Cookie", cookieHeader(session));
    expect(noHeader.status).toBe(403);
    expect(noHeader.body.error.code).toBe("CSRF_FAILED");

    // A matching cookie+header pair the server never issued is also refused.
    const forged = crypto.randomBytes(32).toString("base64url");
    const res = await request(app)
      .post("/api/v1/auth/refresh")
      .set("Cookie", `exo_refresh=${session.refresh}; exo_csrf=${forged}`)
      .set("X-CSRF-Token", forged);
    expect(res.status).toBe(403);
  });

  test("refresh rejects requests from an untrusted Origin", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    const res = await refresh(app, session).set("Origin", "https://evil.example");
    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe("ORIGIN_REJECTED");
  });

  test("refresh without a cookie is a 401", async () => {
    expect((await request(makeApp()).post("/api/v1/auth/refresh")).status).toBe(401);
  });

  test("an expired session cannot be refreshed", async () => {
    let now = Date.now();
    const app = makeApp({ clock: () => new Date(now), settings: { refreshTokenTtlSeconds: 60 } });
    const session = sessionFrom(await register(app));
    now += 2 * 60 * 1000;
    expect((await refresh(app, session)).status).toBe(401);
  });

  test("logout revokes the session, clears cookies, and kills the access token immediately", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    expect((await me(app, session.accessToken)).status).toBe(200);

    const out = await request(app)
      .post("/api/v1/auth/logout")
      .set("Cookie", cookieHeader(session))
      .set("X-CSRF-Token", session.csrf);
    expect(out.status).toBe(204);
    const cleared = parseSetCookies(out);
    expect(cleared.exo_refresh.raw).toMatch(/Expires=Thu, 01 Jan 1970/);
    expect(cleared.exo_csrf.raw).toMatch(/Expires=Thu, 01 Jan 1970/);

    expect((await db.collection("sessions").findOne({})).revoked_reason).toBe("logout");
    expect((await refresh(app, session)).status).toBe(401);
    // The access token has not expired yet, but its session is gone.
    expect((await me(app, session.accessToken)).status).toBe(401);
  });

  test("logout only affects its own session", async () => {
    const app = makeApp();
    const a = sessionFrom(await register(app));
    const b = sessionFrom(await login(app));
    await request(app).post("/api/v1/auth/logout").set("Cookie", cookieHeader(a)).set("X-CSRF-Token", a.csrf);
    expect((await me(app, a.accessToken)).status).toBe(401);
    expect((await me(app, b.accessToken)).status).toBe(200);
  });

  test("logout without a session is a harmless 204", async () => {
    expect((await request(makeApp()).post("/api/v1/auth/logout")).status).toBe(204);
  });

  test("logout with a valid cookie but no CSRF token is refused", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    const res = await request(app).post("/api/v1/auth/logout").set("Cookie", cookieHeader(session));
    expect(res.status).toBe(403);
    expect((await me(app, session.accessToken)).status).toBe(200);
  });
});

// ---------------------------------------------------------------- authorization

describe("authorization", () => {
  test("a user cannot read another user's account by manipulating request parameters", async () => {
    const app = makeApp();
    const alice = await register(app);
    const bob = await register(app, { name: "Bob", username: "bob", email: "bob@example.com" });
    const aliceToken = alice.body.access_token;
    const bobId = bob.body.user.id;

    for (const path of [`/api/v1/auth/me?id=${bobId}`, `/api/v1/auth/me?user_id=${bobId}&sub=${bobId}`]) {
      const r =await request(app).get(path).set("Authorization", `Bearer ${aliceToken}`).set("X-User-Id", bobId);
      expect(r.status).toBe(200);
      expect(r.body.user.id).toBe(alice.body.user.id);
      expect(r.body.user.email).toBe("ada@example.com");
    }
    expect((await request(app).get(`/api/v1/auth/me/${bobId}`).set("Authorization", `Bearer ${aliceToken}`)).status).toBe(404);
    expect((await request(app).get(`/api/v1/auth/users/${bobId}`).set("Authorization", `Bearer ${aliceToken}`)).status).toBe(404);
  });

  test("a token whose session belongs to a different user is rejected", async () => {
    const app = makeApp();
    const alice = await register(app);
    const bob = await register(app, { name: "Bob", username: "bob", email: "bob@example.com" });
    const aliceSid = JSON.parse(Buffer.from(alice.body.access_token.split(".")[1], "base64url").toString()).sid;
    const { token } = await tokens.issueAccessToken(
      { userId: bob.body.user.id, sessionId: aliceSid },
      { keys, issuer: config.auth.jwtIssuer, audience: config.auth.jwtAudience, ttlSeconds: 600 }
    );
    expect((await me(app, token)).status).toBe(401);
  });

  test("the profile endpoint returns no sensitive fields", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    const res = await me(app, session.accessToken);
    expect(Object.keys(res.body.user).sort()).toEqual(
      ["created_at", "email", "id", "is_active", "name", "profile_picture", "updated_at", "username"].sort()
    );
    expectNoSecrets(res.body);
  });

  test("health and readiness stay public", async () => {
    expect((await request(makeApp()).get("/api/v1/health")).status).toBe(200);
  });
});

// ---------------------------------------------------------------- analysis requires login

describe("analysis routes require a signed-in user", () => {
  const mlClient = require("../src/services/mlClient");
  const ROUTES = [
    ["post", "/api/v1/predict"],
    ["post", "/api/v1/predict/manual"],
    ["post", "/api/v1/physics-validation"],
    ["post", "/api/v1/characterization/recompute"],
    ["get", "/api/v1/feature-schema"],
  ];

  test.each(ROUTES)("%s %s rejects requests without a token, before reaching the ML service", async (method, path) => {
    const res = await request(makeApp())[method](path).send({});
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("UNAUTHENTICATED");
    for (const fn of ["forwardCsvPrediction", "forwardNamedPrediction", "forwardPhysicsValidation", "forwardCharacterizationRecompute", "fetchFeatureSchema"]) {
      expect(mlClient[fn]).not.toHaveBeenCalled();
    }
  });

  test("an invalid or revoked token is rejected too", async () => {
    const app = makeApp();
    const session = sessionFrom(await register(app));
    expect((await request(app).get("/api/v1/feature-schema").set("Authorization", "Bearer forged.token.value")).status).toBe(401);
    await request(app).post("/api/v1/auth/logout").set("Cookie", cookieHeader(session)).set("X-CSRF-Token", session.csrf);
    expect((await request(app).get("/api/v1/feature-schema").set("Authorization", `Bearer ${session.accessToken}`)).status).toBe(401);
  });

  test("a signed-in user can reach them", async () => {
    mlClient.fetchFeatureSchema.mockResolvedValue({ features: [] });
    const app = makeApp();
    const session = sessionFrom(await register(app));
    const res = await request(app).get("/api/v1/feature-schema").set("Authorization", `Bearer ${session.accessToken}`);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ features: [] });
    mlClient.fetchFeatureSchema.mockReset();
  });
});
