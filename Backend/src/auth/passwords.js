/**
 * Argon2id password hashing. Parameters follow the OWASP Password Storage
 * Cheat Sheet baseline (m = 19 MiB, t = 2, p = 1). The salt and parameters
 * are embedded in the PHC-format hash string, so they can be raised later
 * without invalidating existing hashes.
 *
 * Uses @node-rs/argon2 (per-platform prebuilt binaries) rather than the
 * `argon2` package, whose prebuilds fail to load in the node:20-slim image
 * and fall back to a source build that needs Python/g++.
 */
const crypto = require("crypto");
const argon2 = require("@node-rs/argon2");

// @node-rs/argon2's Algorithm is a TypeScript const enum (not present at
// runtime): Argon2d = 0, Argon2i = 1, Argon2id = 2.
const ARGON2ID = 2;

const HASH_OPTIONS = {
  algorithm: ARGON2ID,
  memoryCost: 19456,
  timeCost: 2,
  parallelism: 1,
};

function hashPassword(password) {
  return argon2.hash(password, HASH_OPTIONS);
}

async function verifyPassword(hash, password) {
  try {
    return await argon2.verify(hash, password);
  } catch {
    // A malformed stored hash must fail closed, never throw a 500 that
    // distinguishes it from a wrong password.
    return false;
  }
}

// A real Argon2id hash of a random throwaway value, computed once. Logging in
// with an unknown account still runs one full verification against it, so
// response time does not reveal whether the account exists.
let dummyHashPromise = null;
function dummyHash() {
  if (!dummyHashPromise) dummyHashPromise = hashPassword(crypto.randomBytes(32).toString("hex"));
  return dummyHashPromise;
}

async function verifyAgainstDummy(password) {
  await verifyPassword(await dummyHash(), password);
  return false;
}

module.exports = { hashPassword, verifyPassword, verifyAgainstDummy, HASH_OPTIONS };
