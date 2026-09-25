import { createContext, useContext, useState, useCallback } from "react";
import { uploadCsvForAnalysis, submitManualParameters } from "../api/client";

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

const SESSION_STORAGE_KEY = "exoplanet_prediction_session_v1";

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

  const analyze = useCallback(async (file) => {
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
    clearPersistedSession();

    try {
      const body = await uploadCsvForAnalysis(file, {
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
      persistSession({ manualParameters: values, finalResult: body });
    } catch (err) {
      setFinalError(err);
      setFinalStatus(FINAL_STATUS.ERROR);
    }
  }, []);

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
    clearPersistedSession();
  }, []);

  return (
    <AnalysisContext.Provider
      value={{
        status, progress, result, error, filename, analyze, reset,
        manualParameters, finalStatus, finalResult, finalError, submitCombinedPrediction,
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
