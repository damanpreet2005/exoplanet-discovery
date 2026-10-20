import { createContext, useContext, useState, useCallback } from "react";
import { uploadCsvForAnalysis, submitManualParameters, runPhysicsValidation as runPhysicsValidationApi } from "../api/client";

const AnalysisContext = createContext(null);

// Explicit states -- no fake "loading forever" or silently-invented data.
export const STATUS = {
  EMPTY: "empty",
  UPLOADING: "uploading",
  ANALYZING: "analyzing",
  SUCCESS: "success",
  ERROR: "error",
};

// The combined-prediction step (Page 2 -> Page 3) has its own small status
// machine, separate from the light-curve upload step's `STATUS` above.
export const FINAL_STATUS = {
  IDLE: "idle",
  SUBMITTING: "submitting",
  SUCCESS: "success",
  ERROR: "error",
};

// Stage 2 (Physics Validation) has its own status machine, keyed to a
// specific candidate's parameters (see `candidateKeyFromParams` below) so a
// stale report from a *previous* candidate is never shown as if it were
// current.
export const PHYSICS_STATUS = {
  IDLE: "idle",
  RUNNING: "running",
  SUCCESS: "success",
  ERROR: "error",
};

const SESSION_STORAGE_KEY = "exoplanet_prediction_session_v1";

/** Stable identity for "which candidate was this physics report computed
 * for" -- derived from the exact 17 submitted parameters (what the backend
 * actually validated), not from the object_id alone, since object_id is
 * optional/absent for a tabular-only session. */
function candidateKeyFromParams(params) {
  if (!params || typeof params !== "object") return null;
  return JSON.stringify(params, Object.keys(params).sort());
}

/**
 * Persists only the two *completed-stage* outputs (light-curve analysis,
 * final combined prediction) across a page refresh -- not in-progress form
 * typing, which is fine to lose on refresh. This is what prevents "refresh
 * silently loses which CSV is attached" (the actual bug this session model
 * fixes): as long as `lightCurveResult` survives, the manual-parameter and
 * results pages can always tell whether a light curve is genuinely attached.
 */
function loadPersistedSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function persistSession(partial) {
  try {
    const current = loadPersistedSession();
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ ...current, ...partial }));
  } catch {
    // Best-effort only (e.g. private browsing may block storage) -- the
    // in-memory React state below still works for the current page load.
  }
}

function clearPersistedSession() {
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function AnalysisProvider({ children }) {
  const persisted = loadPersistedSession();

  // ---- Page 1: light-curve upload/analysis ----
  const [status, setStatus] = useState(persisted.lightCurveResult ? STATUS.SUCCESS : STATUS.EMPTY);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(persisted.lightCurveResult || null);
  const [error, setError] = useState(null);
  const [filename, setFilename] = useState(persisted.lightCurveResult?.filename || null);

  // ---- Page 2 -> Page 3: combined prediction (CSV analysis + 17 params) ----
  const [manualParameters, setManualParameters] = useState(persisted.manualParameters || null);
  const [finalStatus, setFinalStatus] = useState(persisted.finalResult ? FINAL_STATUS.SUCCESS : FINAL_STATUS.IDLE);
  const [finalResult, setFinalResult] = useState(persisted.finalResult || null);
  const [finalError, setFinalError] = useState(null);

  // ---- Stage 2: Physics Validation ----
  const [physicsStatus, setPhysicsStatus] = useState(persisted.physicsResult ? PHYSICS_STATUS.SUCCESS : PHYSICS_STATUS.IDLE);
  const [physicsResult, setPhysicsResult] = useState(persisted.physicsResult || null);
  const [physicsError, setPhysicsError] = useState(null);
  const [physicsCandidateKey, setPhysicsCandidateKey] = useState(persisted.physicsCandidateKey || null);

  const analyze = useCallback(async (file, objectId) => {
    setStatus(STATUS.UPLOADING);
    setProgress(0);
    setError(null);
    setFilename(file.name);

    // A new light curve starts a new prediction session -- any previous
    // combined result was computed against a *different* CSV and must not
    // be carried forward as if it still applies (this is what prevents a
    // stale manual-only/previous-CSV result from silently reappearing).
    setManualParameters(null);
    setFinalStatus(FINAL_STATUS.IDLE);
    setFinalResult(null);
    setFinalError(null);
    setPhysicsStatus(PHYSICS_STATUS.IDLE);
    setPhysicsResult(null);
    setPhysicsError(null);
    setPhysicsCandidateKey(null);
    clearPersistedSession();

    try {
      const body = await uploadCsvForAnalysis(file, {
        objectId,
        onProgress: (pct) => {
          setProgress(pct);
          if (pct >= 100) setStatus(STATUS.ANALYZING);
        },
      });
      setResult(body);
      setStatus(STATUS.SUCCESS);
      persistSession({ lightCurveResult: body });
    } catch (err) {
      setError(err);
      setStatus(STATUS.ERROR);
    }
  }, []);

  const submitCombinedPrediction = useCallback(async (values) => {
    setFinalStatus(FINAL_STATUS.SUBMITTING);
    setFinalError(null);
    try {
      const body = await submitManualParameters(values);
      setManualParameters(values);
      setFinalResult(body);
      setFinalStatus(FINAL_STATUS.SUCCESS);
      // A new combined prediction is a new candidate -- any previous physics
      // report was computed against *different* parameters and must not be
      // shown as if it still applies.
      setPhysicsStatus(PHYSICS_STATUS.IDLE);
      setPhysicsResult(null);
      setPhysicsError(null);
      setPhysicsCandidateKey(null);
      persistSession({ manualParameters: values, finalResult: body, physicsResult: null, physicsCandidateKey: null });
    } catch (err) {
      setFinalError(err);
      setFinalStatus(FINAL_STATUS.ERROR);
    }
  }, []);

  /**
   * Used only when the CSV-upload response already reached
   * ready_for_prediction with a real trained-model `prediction` attached
   * (every one of the 17 features resolved automatically) -- records that
   * result directly instead of re-submitting the same 17 values to
   * POST /predict/manual as a redundant second network call.
   */
  const acceptExtractedPrediction = useCallback((values, predictionBody) => {
    setManualParameters(values);
    setFinalResult(predictionBody);
    setFinalStatus(FINAL_STATUS.SUCCESS);
    setPhysicsStatus(PHYSICS_STATUS.IDLE);
    setPhysicsResult(null);
    setPhysicsError(null);
    setPhysicsCandidateKey(null);
    persistSession({ manualParameters: values, finalResult: predictionBody, physicsResult: null, physicsCandidateKey: null });
  }, []);

  /**
   * Runs Stage 2 Physics Validation for the *current* candidate (the exact
   * 17 parameters that produced `finalResult`). Safe to call repeatedly --
   * if a matching report for this same candidate already succeeded (or is
   * currently running), it is reused instead of firing a redundant request.
   */
  const startPhysicsValidation = useCallback(async (force = false) => {
    if (!manualParameters) return;
    const key = candidateKeyFromParams(manualParameters);
    if (!force && key === physicsCandidateKey && (physicsStatus === PHYSICS_STATUS.SUCCESS || physicsStatus === PHYSICS_STATUS.RUNNING)) {
      return;
    }
    setPhysicsCandidateKey(key);
    setPhysicsStatus(PHYSICS_STATUS.RUNNING);
    setPhysicsError(null);
    try {
      const body = await runPhysicsValidationApi(manualParameters, result?.object_id);
      setPhysicsResult(body);
      setPhysicsStatus(PHYSICS_STATUS.SUCCESS);
      persistSession({ physicsResult: body, physicsCandidateKey: key });
    } catch (err) {
      setPhysicsError(err);
      setPhysicsStatus(PHYSICS_STATUS.ERROR);
    }
  }, [manualParameters, result, physicsCandidateKey, physicsStatus]);

  const reset = useCallback(() => {
    setStatus(STATUS.EMPTY);
    setProgress(0);
    setResult(null);
    setError(null);
    setFilename(null);
    setManualParameters(null);
    setFinalStatus(FINAL_STATUS.IDLE);
    setFinalResult(null);
    setFinalError(null);
    setPhysicsStatus(PHYSICS_STATUS.IDLE);
    setPhysicsResult(null);
    setPhysicsError(null);
    setPhysicsCandidateKey(null);
    clearPersistedSession();
  }, []);

  // True only when physicsResult was actually computed for the candidate
  // currently shown on the results page -- false after a new prediction
  // replaces manualParameters, even if an older report is still in state
  // for an instant during the transition.
  const physicsResultIsCurrent = physicsCandidateKey !== null
    && physicsCandidateKey === candidateKeyFromParams(manualParameters);

  return (
    <AnalysisContext.Provider
      value={{
        status, progress, result, error, filename, analyze, reset,
        manualParameters, finalStatus, finalResult, finalError, submitCombinedPrediction,
        acceptExtractedPrediction,
        physicsStatus, physicsResult, physicsError, startPhysicsValidation,
        physicsResultIsCurrent,
      }}
    >
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be used within an AnalysisProvider");
  return ctx;
}
