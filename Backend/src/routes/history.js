/**
 * Prediction history, mounted under /api/v1 behind requireAuth:
 *
 *   GET   /history               -- the signed-in user's predictions, most recently run first
 *   GET   /history/csv/:fileId   -- download a run's stored CSV (GridFS)
 *   PATCH /history/:id           -- rename a prediction ({ "name": "..." }; "" restores the default)
 *
 * Ownership is always checked against req.auth.user, never against an id in
 * the request: a CSV is only served when a history record owned by the
 * caller references that GridFS file id. Anything else is a plain 404, so a
 * file id belonging to another user is indistinguishable from a missing one.
 *
 * `recordRun` is called by POST /predict after a successful prediction (a
 * re-run of the same CSV + Object ID updates the existing record instead of
 * adding one, see repositories/predictionHistory.js);
 * `recordManualRun` by POST /predict/manual, to save the exact parameters
 * the user submitted on the run they belong to.
 */
const express = require("express");
const { randomUUID } = require("crypto");
const { HistoryUnavailableError, NotFoundError, ValidationError } = require("../errors");
const { makeLogger } = require("../logger");
const {
  defaultName,
  makePredictionHistoryRepository,
  normalizeName,
  objectKey,
  sha256,
  toPublicRecord,
  parseFileId,
  parseHistoryId,
  toParameterList,
  safeCsvFilename,
  summarizePrediction,
  summarizeResult,
} = require("../repositories/predictionHistory");

/**
 * @param {object} deps
 * @param {() => import("mongodb").Db|null} deps.getDb
 * @param {string} deps.logLevel
 */
function createPredictionHistory({ getDb, logLevel }) {
  const logger = makeLogger(logLevel);
  const router = express.Router();

  let cached = { db: null, repo: null };
  function resolveRepo() {
    const db = getDb();
    if (!db) return null;
    if (cached.db !== db) cached = { db, repo: makePredictionHistoryRepository(db) };
    return cached.repo;
  }

  function requireRepo() {
    const repo = resolveRepo();
    if (!repo) throw new HistoryUnavailableError();
    return repo;
  }

  function noStore(req, res, next) {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Pragma", "no-cache");
    next();
  }

  /**
   * Saves one run and returns { id, rerun }, or null. Never throws: history
   * is a side record, so a storage failure is logged and the prediction
   * response is still returned.
   *
   * A re-run (same user, byte-identical CSV, same Object ID) only updates the
   * existing record: run timestamp, and the prediction when this run reached
   * the model (otherwise the earlier result and parameters are kept). No new
   * record and no second copy of the CSV.
   *
   * A first run: GridFS upload, then the history document. If the upload
   * fails the run is still recorded with csv_file_id null (shown as "CSV
   * unavailable"). If the document insert fails, the just-uploaded file is
   * deleted so no orphaned GridFS file is left behind.
   */
  async function recordRun({ userId, requestId, file, result }) {
    const repo = resolveRepo();
    if (!repo || !userId) return null;

    const now = new Date();
    const run = { at: now, kind: "upload", request_id: requestId || null };
    const csvSha256 = sha256(file.buffer);
    const key = objectKey(result && result.object_id);
    const summary = summarizeResult(result);
    const filename = safeCsvFilename(file.originalname);

    async function recordRerun() {
      const set = { dataset_type: summary.dataset_type, object_id: summary.object_id, total_rows: summary.total_rows,
                    updated_at: now };
      if (summary.prediction !== null || summary.total_rows !== null) {
        Object.assign(set, { prediction: summary.prediction, weighted_probability: summary.weighted_probability,
                             model_version: summary.model_version, parameters: summary.parameters,
                             parameters_source: summary.parameters_source });
      }
      const existing = await repo.findRerunAndRecord({ userId, csvSha256, objectKey: key, set, run });
      if (existing && !existing.csv_file_id) {
        // The first run could not store its CSV; this identical upload can.
        const fileId = await repo.uploadCsv({ buffer: file.buffer, filename, userId, historyId: existing._id, requestId })
          .catch((err) => logger.error("history_csv_upload_failed", { request_id: requestId, error: err.message }));
        if (fileId) await repo.attachCsv(existing._id, fileId, file.buffer.length);
      }
      return existing;
    }

    try {
      const existing = await recordRerun();
      if (existing) return { id: existing._id, rerun: true };
    } catch (err) {
      logger.error("history_rerun_lookup_failed", { request_id: requestId, error: err.message });
      return null;
    }

    const historyId = randomUUID();
    let csvFileId = null;
    try {
      csvFileId = await repo.uploadCsv({ buffer: file.buffer, filename, userId, historyId, requestId });
    } catch (err) {
      logger.error("history_csv_upload_failed", { request_id: requestId, error: err.message });
    }

    try {
      await repo.insert({
        _id: historyId,
        user_id: userId,
        request_id: requestId || null,
        created_at: now,
        filename,
        ...summary,
        csv_file_id: csvFileId,
        csv_size_bytes: csvFileId ? file.buffer.length : null,
        csv_sha256: csvSha256,
        object_key: key,
        name: null,
        default_name: defaultName(result, filename),
        last_run_at: now,
        run_count: 1,
        runs: [run],
      });
      return { id: historyId, rerun: false };
    } catch (err) {
      if (csvFileId) {
        await repo.deleteCsv(csvFileId).catch((deleteErr) => {
          logger.error("history_csv_orphaned", {
            request_id: requestId,
            file_id: csvFileId.toHexString(),
            error: deleteErr.message,
          });
        });
      }
      // Lost a race with an identical concurrent upload: count this as its re-run.
      if (err && err.code === 11000) {
        const existing = await recordRerun().catch(() => null);
        if (existing) return { id: existing._id, rerun: true };
      }
      logger.error("history_record_insert_failed", { request_id: requestId, error: err.message });
      return null;
    }
  }

  /**
   * Saves a manual prediction's exact parameters. Never throws.
   *
   * `historyId` (from the X-History-Id header) names the CSV run the
   * parameters were entered for; it is only applied when that run belongs to
   * `userId`. Without a matching run, the submission is saved as its own
   * record with no CSV, so it is never attached to someone else's run.
   */
  async function recordManualRun({ userId, historyId, requestId, parameters, result }) {
    const repo = resolveRepo();
    if (!repo || !userId) return null;

    const now = new Date();
    const submission = {
      request_id: requestId || null,
      created_at: now,
      parameters: toParameterList(parameters),
      ...summarizePrediction(result),
    };
    try {
      const runId = parseHistoryId(historyId);
      if (runId && (await repo.addManualSubmission(runId, userId, submission))) return runId;

      const id = randomUUID();
      await repo.insert({
        _id: id,
        user_id: userId,
        request_id: requestId || null,
        created_at: now,
        filename: null,
        dataset_type: "manual",
        object_id: null,
        object_key: "",
        name: null,
        default_name: "Manual parameters",
        last_run_at: now,
        run_count: 1,
        runs: [{ at: now, kind: "manual", request_id: requestId || null }],
        ...summarizePrediction(result),
        total_rows: null,
        csv_file_id: null,
        csv_size_bytes: null,
        parameters: submission.parameters,
        parameters_source: "manual",
        manual_submissions: [submission],
      });
      return id;
    } catch (err) {
      logger.error("history_manual_record_failed", { request_id: requestId, error: err.message });
      return null;
    }
  }

  router.get("/history", noStore, async (req, res, next) => {
    try {
      const repo = requireRepo();
      const runs = await repo.listForUser(req.auth.user._id);
      return res.status(200).json({ runs });
    } catch (err) {
      return next(err);
    }
  });

  router.patch("/history/:id", noStore, express.json({ limit: "2kb" }), async (req, res, next) => {
    try {
      const id = parseHistoryId(req.params.id);
      if (!id) throw new ValidationError("The prediction id is malformed.");
      const name = normalizeName(req.body && req.body.name);
      if (name === null) {
        throw new ValidationError("'name' must be a string of at most 80 characters (empty restores the default name).");
      }
      const repo = requireRepo();
      const doc = await repo.rename(id, req.auth.user._id, name);
      if (!doc) throw new NotFoundError("No such prediction in your history.", "PREDICTION_NOT_FOUND");
      return res.status(200).json({ run: toPublicRecord(doc) });
    } catch (err) {
      return next(err);
    }
  });

  router.get("/history/csv/:fileId", noStore, async (req, res, next) => {
    try {
      const fileId = parseFileId(req.params.fileId);
      if (!fileId) throw new ValidationError("The CSV file id is malformed.");

      const repo = requireRepo();
      const record = await repo.findByCsvFileForUser(fileId, req.auth.user._id);
      if (!record) throw new NotFoundError("No saved CSV was found for this prediction.", "CSV_NOT_FOUND");

      const csv = await repo.readCsv(fileId);
      if (!csv) {
        logger.warn("history_csv_missing", { request_id: req.requestId, file_id: req.params.fileId });
        throw new NotFoundError("The saved CSV for this prediction is no longer available.", "CSV_NOT_FOUND");
      }

      res.setHeader("Content-Type", "text/csv; charset=utf-8");
      res.setHeader("Content-Disposition", `attachment; filename="${safeCsvFilename(record.filename)}"`);
      res.setHeader("X-Content-Type-Options", "nosniff");
      return res.status(200).send(csv);
    } catch (err) {
      return next(err);
    }
  });

  return { router, recordRun, recordManualRun };
}

module.exports = { createPredictionHistory };
