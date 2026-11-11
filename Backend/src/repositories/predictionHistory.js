/**
 * `prediction_history` collection plus the `prediction_csvs` GridFS bucket.
 *
 * One history document per successful CSV prediction run by a signed-in
 * user. The uploaded CSV itself is never stored in the history document --
 * it lives in GridFS and the document holds only its file id. Every GridFS
 * file also carries the owner's id in `metadata.user_id`, so a file can be
 * attributed to its owner even without the history document.
 *
 *   { _id, user_id, request_id, created_at, updated_at, filename,
 *     dataset_type, object_id, prediction, weighted_probability,
 *     model_version, total_rows, csv_file_id, csv_size_bytes,
 *     parameters, parameters_source, manual_submissions,
 *     csv_sha256, object_key, name, default_name,
 *     last_run_at, run_count, runs }
 *
 * RE-RUNS: a run is "the same" as an earlier one when the same user uploads
 * a byte-identical CSV (`csv_sha256`) for the same Object ID (`object_key`,
 * trimmed and lower-cased). It then updates that record -- `last_run_at`,
 * `run_count`, a `runs` entry -- instead of adding a record and storing the
 * CSV again. A unique partial index on (user_id, csv_sha256, object_key)
 * makes this hold under concurrent uploads too.
 *
 * TIMESTAMPS: `created_at` is the first run; every run (upload or manual
 * parameter submission) appends { at, kind, request_id } to `runs` (most
 * recent MAX_RUNS kept) and sets `last_run_at`; `run_count` is the total.
 *
 * NAMES: `name` is the user's own name for the prediction (null until
 * renamed); `default_name` is derived at the first run from the resolved
 * catalogue object (Kepler name > KOI > Object ID > file name).
 *
 * `csv_file_id` holds the ObjectId GridFS assigned to the uploaded CSV, and
 * is the only key the download route accepts. It is null when the CSV could
 * not be stored (or the run had no CSV); readers must treat that as "CSV
 * unavailable" rather than an error.
 *
 * `parameters` are the exact named values the model was run on, as
 * [{ name, value }] (an array, so any submitted name is stored verbatim
 * without being used as a MongoDB field name). `parameters_source` is
 * "extracted" when /predict resolved all 17 automatically, or "manual" when
 * the user submitted them through /predict/manual. Each manual submission is
 * also appended to `manual_submissions` (most recent MAX_MANUAL_SUBMISSIONS
 * kept), and the top-level prediction fields always reflect the latest one.
 *
 * CSVs are small (capped by CSV_MAX_FILE_SIZE_BYTES), so they are written and
 * read in a single in-memory pass: the whole Buffer is handed to the upload
 * stream in one `end()` call, and downloads are collected into one Buffer
 * before being returned. Nothing is piped to or from an HTTP stream.
 */
const { createHash } = require("crypto");
const { GridFSBucket, ObjectId } = require("mongodb");
const { finished } = require("stream/promises");
const config = require("../config");
const { makeLogger } = require("../logger");

const logger = makeLogger(config.logLevel);

const COLLECTION = "prediction_history";
const BUCKET = "prediction_csvs";
const LIST_LIMIT = 100;
const FILE_ID_PATTERN = /^[0-9a-f]{24}$/i;
const HISTORY_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_MANUAL_SUBMISSIONS = 20;
const MAX_RUNS = 50;
const MAX_NAME_LENGTH = 80;

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

/** Object IDs differing only in case or spacing name the same object. */
function objectKey(objectId) {
  return String(objectId || "").trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * One-time backfill for records saved before re-run detection and run
 * timestamps existed: gives each a run timeline from its own timestamps and,
 * where its CSV is stored, the CSV fingerprint. When several old records hold
 * the same CSV + Object ID, only the oldest is keyed (the others stay as
 * separate rows) so the unique index can be built.
 */
async function backfillLegacyRecords(db) {
  const history = db.collection(COLLECTION);
  const bucket = new GridFSBucket(db, { bucketName: BUCKET });
  const legacy = await history.find({ last_run_at: { $exists: false } }).sort({ created_at: 1 }).toArray();
  for (const doc of legacy) {
    const runs = [{ at: doc.created_at, kind: doc.dataset_type === "manual" ? "manual" : "upload",
                    request_id: doc.request_id || null }];
    for (const s of doc.manual_submissions || []) {
      if (doc.dataset_type !== "manual") runs.push({ at: s.created_at, kind: "manual", request_id: s.request_id || null });
    }
    const set = { last_run_at: runs[runs.length - 1].at, run_count: runs.length, runs: runs.slice(-MAX_RUNS),
                  object_key: objectKey(doc.object_id) };
    if (doc.csv_file_id) {
      try {
        const chunks = [];
        for await (const chunk of bucket.openDownloadStream(doc.csv_file_id)) chunks.push(chunk);
        const digest = sha256(Buffer.concat(chunks));
        const taken = await history.findOne({ user_id: doc.user_id, csv_sha256: digest, object_key: set.object_key });
        if (!taken) set.csv_sha256 = digest;
      } catch (err) {
        logger.warn("history_backfill_csv_unreadable", { history_id: doc._id, error: err.message });
      }
    }
    await history.updateOne({ _id: doc._id }, { $set: set });
  }
  if (legacy.length) logger.info("history_backfill_completed", { records: legacy.length });
}

async function ensurePredictionHistoryCollection(db) {
  const history = db.collection(COLLECTION);
  await history.createIndex({ user_id: 1, created_at: -1 }, { name: "by_user_recent" });
  await history.createIndex({ user_id: 1, last_run_at: -1 }, { name: "by_user_last_run" });
  await history.createIndex({ csv_file_id: 1 }, { name: "by_csv_file" });
  await backfillLegacyRecords(db);
  try {
    await history.createIndex(
      { user_id: 1, csv_sha256: 1, object_key: 1 },
      { name: "uniq_user_csv_object", unique: true, partialFilterExpression: { csv_sha256: { $type: "string" } } }
    );
  } catch (err) {
    // Never block the gateway (and sign-in) on this: re-run detection still
    // works through the lookup, only concurrent duplicate uploads could slip through.
    logger.error("history_unique_index_failed", { error: err.message });
  }
}

/** Validates a user-supplied prediction name: trimmed, single-spaced, no
 * control characters. Returns "" to reset to the default name, or null if invalid. */
function normalizeName(raw) {
  if (typeof raw !== "string") return null;
  const name = raw.replace(/[\u0000-\u001f\u007f]/g, "").trim().replace(/\s+/g, " ");
  return name.length <= MAX_NAME_LENGTH ? name : null;
}

/** Name shown before the user renames a prediction. */
function defaultName(result, filename) {
  const cat = (result && result.catalog_resolution) || {};
  const base = filename ? String(filename).replace(/\.csv$/i, "") : "";
  return (cat.matched_kepler_name || cat.matched_kepoi_name || (result && result.object_id) || base || "Prediction")
    .slice(0, MAX_NAME_LENGTH);
}

/** Parses a GridFS file id from user input, or returns null if malformed. */
function parseFileId(raw) {
  return typeof raw === "string" && FILE_ID_PATTERN.test(raw) ? new ObjectId(raw) : null;
}

/** Validates a history record id (a UUID) from user input, or returns null. */
function parseHistoryId(raw) {
  return typeof raw === "string" && HISTORY_ID_PATTERN.test(raw) ? raw.toLowerCase() : null;
}

/** Stores named parameter values verbatim, in submission order. */
function toParameterList(named) {
  return Object.entries(named).map(([name, value]) => ({ name, value }));
}

/** Reduces an uploaded filename to a safe `.csv` name for storage and Content-Disposition. */
function safeCsvFilename(raw) {
  const base = String(raw || "")
    .replace(/\.csv$/i, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^[._]+/, "")
    .slice(0, 100);
  return `${base || "prediction"}.csv`;
}

/** The listed fields of a model prediction (a PredictionResponse body). */
function summarizePrediction(prediction) {
  return {
    prediction: prediction && Number.isInteger(prediction.prediction) ? prediction.prediction : null,
    weighted_probability:
      prediction && typeof prediction.weighted_probability === "number" ? prediction.weighted_probability : null,
    model_version: (prediction && prediction.model_version) || null,
  };
}

/** The fields of a /predict response worth listing; never the CSV or full report. */
function summarizeResult(result) {
  const prediction = result && result.prediction;
  const summary = {
    dataset_type: (result && result.dataset_type) || null,
    object_id: (result && result.object_id) || null,
    ...summarizePrediction(prediction),
    total_rows: result && Number.isInteger(result.total_rows) ? result.total_rows : null,
    parameters: null,
    parameters_source: null,
  };
  if (!summary.model_version && result && result.model_version) summary.model_version = result.model_version;
  // Only a light-curve run that actually reached the model has a parameter
  // set: the 17 resolved feature values it was run on.
  if (prediction && result.ready_for_prediction && result.features) {
    const named = {};
    for (const [name, feature] of Object.entries(result.features)) named[name] = feature ? feature.value : null;
    summary.parameters = toParameterList(named);
    summary.parameters_source = "extracted";
  }
  return summary;
}

function toPublicRecord(doc) {
  const fallbackName = doc.dataset_type === "manual" ? "Manual parameters"
    : (doc.object_id || (doc.filename || "").replace(/\.csv$/i, "") || "Prediction");
  return {
    id: doc._id,
    name: doc.name || doc.default_name || fallbackName,
    name_is_custom: Boolean(doc.name),
    created_at: doc.created_at,
    first_run_at: doc.created_at,
    last_run_at: doc.last_run_at || doc.created_at,
    run_count: doc.run_count || 1,
    runs: (doc.runs || []).map((r) => ({ at: r.at, kind: r.kind })),
    filename: doc.filename,
    dataset_type: doc.dataset_type ?? null,
    object_id: doc.object_id ?? null,
    prediction: doc.prediction ?? null,
    weighted_probability: doc.weighted_probability ?? null,
    model_version: doc.model_version ?? null,
    total_rows: doc.total_rows ?? null,
    csv_file_id: doc.csv_file_id ? doc.csv_file_id.toHexString() : null,
    csv_size_bytes: doc.csv_size_bytes ?? null,
    parameters: doc.parameters ?? null,
    parameters_source: doc.parameters_source ?? null,
    manual_submission_count: Array.isArray(doc.manual_submissions) ? doc.manual_submissions.length : 0,
  };
}

function makePredictionHistoryRepository(db) {
  const history = db.collection(COLLECTION);
  const bucket = new GridFSBucket(db, { bucketName: BUCKET });

  return {
    /** Writes the whole CSV buffer to GridFS in one call and returns its file id. */
    async uploadCsv({ buffer, filename, userId, historyId, requestId }) {
      const upload = bucket.openUploadStream(filename, {
        metadata: { user_id: userId, history_id: historyId, request_id: requestId || null, contentType: "text/csv" },
      });
      try {
        upload.end(buffer);
        await finished(upload);
      } catch (err) {
        // Removes any chunks already written so a failed upload leaves no partial file.
        await upload.abort().catch(() => {});
        throw err;
      }
      return upload.id;
    },

    deleteCsv(fileId) {
      return bucket.delete(fileId);
    },

    async insert(doc) {
      await history.insertOne(doc);
      return doc;
    },

    /**
     * Records a re-run on the caller's existing run with this CSV and Object
     * ID, if there is one. Returns the updated record, or null.
     */
    findRerunAndRecord({ userId, csvSha256, objectKey: key, set, run }) {
      return history.findOneAndUpdate(
        { user_id: userId, csv_sha256: csvSha256, object_key: key },
        { $set: { ...set, last_run_at: run.at }, $inc: { run_count: 1 },
          $push: { runs: { $each: [run], $slice: -MAX_RUNS } } },
        { returnDocument: "after" }
      );
    },

    async attachCsv(historyId, fileId, size) {
      await history.updateOne({ _id: historyId }, { $set: { csv_file_id: fileId, csv_size_bytes: size } });
    },

    /** Renames the caller's own run; "" restores the default name. Returns the record, or null. */
    rename(historyId, userId, name) {
      return history.findOneAndUpdate(
        { _id: historyId, user_id: userId },
        { $set: { name: name || null, updated_at: new Date() } },
        { returnDocument: "after" }
      );
    },

    /**
     * Applies a manual prediction to the caller's own run `historyId`.
     * Returns false when no such run belongs to `userId`.
     */
    async addManualSubmission(historyId, userId, submission) {
      const { matchedCount } = await history.updateOne(
        { _id: historyId, user_id: userId },
        {
          $set: {
            prediction: submission.prediction,
            weighted_probability: submission.weighted_probability,
            model_version: submission.model_version,
            parameters: submission.parameters,
            parameters_source: "manual",
            updated_at: submission.created_at,
            last_run_at: submission.created_at,
          },
          $inc: { run_count: 1 },
          $push: {
            manual_submissions: { $each: [submission], $slice: -MAX_MANUAL_SUBMISSIONS },
            runs: { $each: [{ at: submission.created_at, kind: "manual", request_id: submission.request_id }],
                    $slice: -MAX_RUNS },
          },
        }
      );
      return matchedCount === 1;
    },

    async listForUser(userId, limit = LIST_LIMIT) {
      const docs = await history.find({ user_id: userId }).sort({ last_run_at: -1, created_at: -1 }).limit(limit).toArray();
      return docs.map(toPublicRecord);
    },

    /** The history record owning `fileId`, only if it belongs to `userId`. */
    findByCsvFileForUser(fileId, userId) {
      return history.findOne({ csv_file_id: fileId, user_id: userId });
    },

    /** Reads the whole GridFS file into one Buffer, or returns null if it no longer exists. */
    async readCsv(fileId) {
      const files = await bucket.find({ _id: fileId }, { limit: 1 }).toArray();
      if (files.length === 0) return null;
      const chunks = [];
      for await (const chunk of bucket.openDownloadStream(fileId)) chunks.push(chunk);
      return Buffer.concat(chunks);
    },
  };
}

module.exports = {
  ensurePredictionHistoryCollection,
  makePredictionHistoryRepository,
  toPublicRecord,
  sha256,
  objectKey,
  normalizeName,
  defaultName,
  parseFileId,
  parseHistoryId,
  toParameterList,
  safeCsvFilename,
  summarizePrediction,
  summarizeResult,
};
