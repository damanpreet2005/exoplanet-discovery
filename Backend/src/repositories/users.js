/**
 * `users` collection. Uniqueness of username and (normalized) email is
 * enforced by unique indexes, not just by a check-then-insert in code, so two
 * concurrent sign-ups can never both succeed. A $jsonSchema validator rejects
 * documents missing required fields at the database level too.
 *
 * Document shape (`_id` is the internal user id, exposed as `id`):
 *   { _id, name, username, email, password_hash, profile_picture,
 *     created_at, updated_at, is_active }
 */
const { randomUUID } = require("crypto");

const COLLECTION = "users";

const USER_VALIDATOR = {
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "name", "username", "email", "password_hash", "created_at", "updated_at", "is_active"],
    properties: {
      _id: { bsonType: "string" },
      name: { bsonType: "string", minLength: 1, maxLength: 100 },
      username: { bsonType: "string", minLength: 3, maxLength: 30 },
      email: { bsonType: "string", minLength: 3, maxLength: 254 },
      // Argon2id PHC string -- never a plaintext password.
      password_hash: { bsonType: "string", pattern: "^\\$argon2id\\$" },
      profile_picture: { bsonType: ["string", "null"] },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" },
      is_active: { bsonType: "bool" },
    },
  },
};

async function ensureUserCollection(db) {
  const existing = await db.listCollections({ name: COLLECTION }, { nameOnly: true }).toArray();
  if (existing.length === 0) {
    await db.createCollection(COLLECTION, { validator: USER_VALIDATOR, validationLevel: "strict" });
  }
  const users = db.collection(COLLECTION);
  // Values are stored already normalized (lowercased), so plain unique
  // indexes are sufficient for case-insensitive uniqueness.
  await users.createIndex({ username: 1 }, { unique: true, name: "uniq_username" });
  await users.createIndex({ email: 1 }, { unique: true, name: "uniq_email" });
}

/** Maps a duplicate-key error to the field that collided, or null. */
function duplicateField(err) {
  if (!err || err.code !== 11000) return null;
  const key = err.keyPattern ? Object.keys(err.keyPattern)[0] : "";
  if (key === "username" || /uniq_username/.test(err.message || "")) return "username";
  if (key === "email" || /uniq_email/.test(err.message || "")) return "email";
  return "unknown";
}

function makeUserRepository(db) {
  const users = db.collection(COLLECTION);

  return {
    /** Inserts a user. Throws the driver's duplicate-key error on collision. */
    async create({ name, username, email, passwordHash, now = new Date() }) {
      const doc = {
        _id: randomUUID(),
        name,
        username,
        email,
        password_hash: passwordHash,
        profile_picture: null,
        created_at: now,
        updated_at: now,
        is_active: true,
      };
      await users.insertOne(doc);
      return doc;
    },

    findById(id) {
      return users.findOne({ _id: id });
    },

    findByEmail(email) {
      return users.findOne({ email });
    },

    findByUsername(username) {
      return users.findOne({ username });
    },

    async existing({ username, email }) {
      const docs = await users
        .find({ $or: [{ username }, { email }] }, { projection: { username: 1, email: 1 } })
        .toArray();
      return {
        username: docs.some((d) => d.username === username),
        email: docs.some((d) => d.email === email),
      };
    },
  };
}

/**
 * The only shape a user document ever leaves the backend in. An explicit
 * allow-list, so a field added to the collection later (or password_hash)
 * can never leak through an API response by accident.
 */
function toPublicUser(doc) {
  return {
    id: doc._id,
    name: doc.name,
    username: doc.username,
    email: doc.email,
    profile_picture: doc.profile_picture || null,
    created_at: doc.created_at instanceof Date ? doc.created_at.toISOString() : doc.created_at,
    updated_at: doc.updated_at instanceof Date ? doc.updated_at.toISOString() : doc.updated_at,
    is_active: doc.is_active,
  };
}

module.exports = { COLLECTION, ensureUserCollection, makeUserRepository, toPublicUser, duplicateField };
