import { createContext, useContext, useState, useCallback } from "react";
import { uploadCsvForAnalysis } from "../api/client";

const AnalysisContext = createContext(null);

// Explicit states -- no fake "loading forever" or silently-invented data.
export const STATUS = {
  EMPTY: "empty",
  UPLOADING: "uploading",
  ANALYZING: "analyzing",
  SUCCESS: "success",
  ERROR: "error",
};

export function AnalysisProvider({ children }) {
  const [status, setStatus] = useState(STATUS.EMPTY);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [filename, setFilename] = useState(null);

  const analyze = useCallback(async (file) => {
    setStatus(STATUS.UPLOADING);
    setProgress(0);
    setError(null);
    setFilename(file.name);

    try {
      const body = await uploadCsvForAnalysis(file, {
        onProgress: (pct) => {
          setProgress(pct);
          if (pct >= 100) setStatus(STATUS.ANALYZING);
        },
      });
      setResult(body);
      setStatus(STATUS.SUCCESS);
    } catch (err) {
      setError(err);
      setStatus(STATUS.ERROR);
    }
  }, []);

  const reset = useCallback(() => {
    setStatus(STATUS.EMPTY);
    setProgress(0);
    setResult(null);
    setError(null);
    setFilename(null);
  }, []);

  return (
    <AnalysisContext.Provider value={{ status, progress, result, error, filename, analyze, reset }}>
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be used within an AnalysisProvider");
  return ctx;
}
