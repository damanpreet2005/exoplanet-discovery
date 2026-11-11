/**
 * `sessions` collection: one document per sign-in (a refresh-token family).
 *
 * Only a SHA-256 hash of each refresh token is stored. Every refresh rotates
 * the token; the hashes it replaced are kept in `retired_hashes` so that a
 * replayed old token is recognised as reuse (a sign the token was stolen) and
 * the whole session is revoked. A TTL index purges sessions once they expire.
 *
 * `csrf_hash` binds the session's CSRF token to it (double-submit cookie
 * whose value must also match what the server issued for this session).
 *
 *   { _id, user_id, token_hash, prev_token_hash, rotated_at, retired_hashes,
 *     csrf_hash, created_at, last_used_at, expires_at, absolute_expires_at,
 *     revoked_at, revoked_reason }
 */
const COLLECTION = "sessions";
const MAX_RETIRED_HASHES = 100;

async function ensureSessionCollection(db) {
  const sessions = db.collection(COLLECTION);
  await sessions.createIndex({ user_id: 1 }, { name: "by_user" });
  await sessions.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0, name: "ttl_expires_at" });
}

function minDate(a, b) {
  return a.getTime() <= b.getTime() ? a : b;
}

function makeSessionRepository(db) {
  const sessions = db.collection(COLLECTION);

  return {
    async create({ id, userId, tokenHash, csrfHash, now, refreshTtlMs, maxAgeMs }) {
      const absoluteExpiresAt = new Date(now.getTime() + maxAgeMs);
      const doc = {
        _id: id,
        user_id: userId,
        token_hash: tokenHash,
        prev_token_hash: null,
        rotated_at: null,
        retired_hashes: [],
        csrf_hash: csrfHash,
        created_at: now,
        last_used_at: now,
        expires_at: minDate(new Date(now.getTime() + refreshTtlMs), absoluteExpiresAt),
        absolute_expires_at: absoluteExpiresAt,
        revoked_at: null,
        revoked_reason: null,
      };
      await sessions.insertOne(doc);
      return doc;
    },

    findById(id) {
      return sessions.findOne({ _id: id });
    },

    /** True only for a session that exists, belongs to `userId`, and is live. */
    async isActive(id, userId, now = new Date()) {
      const doc = await sessions.findOne(
        { _id: id, user_id: userId, revoked_at: null, expires_at: { $gt: now } },
        { projection: { _id: 1 } }
      );
      return Boolean(doc);
    },

    /**
     * Atomically swaps the current token hash for a new one. Matching on the
     * presented hash makes this a compare-and-swap: of two concurrent
     * refreshes with the same token, exactly one wins. Returns the updated
     * session, or null if the presented token is not the current one.
     */
    async rotate({ id, presentedHash, newHash, now, refreshTtlMs }) {
      const current = await sessions.findOne({ _id: id }, { projection: { absolute_expires_at: 1 } });
      if (!current) return null;
      const expiresAt = minDate(new Date(now.getTime() + refreshTtlMs), current.absolute_expires_at);
      return sessions.findOneAndUpdate(
        { _id: id, token_hash: presentedHash, revoked_at: null, expires_at: { $gt: now } },
        {
          $set: {
            token_hash: newHash,
            prev_token_hash: presentedHash,
            rotated_at: now,
            last_used_at: now,
            expires_at: expiresAt,
          },
          $push: { retired_hashes: { $each: [presentedHash], $slice: -MAX_RETIRED_HASHES } },
        },
        { returnDocument: "after" }
      );
    },

    async revoke(id, reason, now = new Date()) {
      await sessions.updateOne(
        { _id: id, revoked_at: null },
        { $set: { revoked_at: now, revoked_reason: reason } }
      );
    },
  };
}

module.exports = { COLLECTION, ensureSessionCollection, makeSessionRepository };
