/**
 * MongoDB connection for user accounts. The gateway is the only process that
 * talks to MongoDB -- the browser never does, and the ML service has no
 * access to it. Connecting is retried in the background so the gateway (and
 * the public ML workflow) keeps serving while the database is still starting;
 * account endpoints answer 503 until it is ready.
 */
const { MongoClient } = require("mongodb");
const config = require("../config");
const { makeLogger } = require("../logger");
const { ensureUserCollection } = require("../repositories/users");
const { ensureSessionCollection } = require("../repositories/sessions");
const { ensurePredictionHistoryCollection } = require("../repositories/predictionHistory");

const logger = makeLogger(config.logLevel);

let client = null;
let db = null;

function isConfigured(mongoConfig = config.mongo) {
  return Boolean(mongoConfig.uri);
}

/** Creates collections, validators and indexes (idempotent). */
async function initSchema(database) {
  await ensureUserCollection(database);
  await ensureSessionCollection(database);
  await ensurePredictionHistoryCollection(database);
}

async function connect(mongoConfig = config.mongo) {
  const options = { serverSelectionTimeoutMS: 5000, appName: "exodiscovery-gateway" };
  if (mongoConfig.username) {
    options.auth = { username: mongoConfig.username, password: mongoConfig.password };
    if (mongoConfig.authSource) options.authSource = mongoConfig.authSource;
  }
  const nextClient = new MongoClient(mongoConfig.uri, options);
  await nextClient.connect();
  const nextDb = nextClient.db(mongoConfig.dbName);
  await initSchema(nextDb);
  client = nextClient;
  db = nextDb;
  return db;
}

/** Background connect with capped exponential backoff. Never throws. */
function connectWithRetry(mongoConfig = config.mongo) {
  if (!isConfigured(mongoConfig)) {
    logger.warn("mongodb_not_configured", { detail: "MONGODB_URI is unset; account features are disabled." });
    return Promise.resolve(null);
  }
  let delayMs = 1000;
  const attempt = async () => {
    try {
      await connect(mongoConfig);
      logger.info("mongodb_connected", { db: mongoConfig.dbName });
      return db;
    } catch (err) {
      // err.message from the driver never contains the password: credentials
      // are passed via options, not embedded in the URI.
      logger.error("mongodb_connect_failed", { error: err.message, retry_in_ms: delayMs });
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      delayMs = Math.min(delayMs * 2, 30000);
      return attempt();
    }
  };
  return attempt();
}

function getDb() {
  return db;
}

/** Test hook: use an already-connected database. */
function setDb(database) {
  db = database;
}

async function ping() {
  if (!db) return false;
  try {
    await db.command({ ping: 1 });
    return true;
  } catch {
    return false;
  }
}

async function close() {
  if (client) await client.close();
  client = null;
  db = null;
}

module.exports = { connect, connectWithRetry, getDb, setDb, ping, close, isConfigured, initSchema };
