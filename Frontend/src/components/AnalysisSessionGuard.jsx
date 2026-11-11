import { useEffect, useRef } from "react";
import { useAnalysis } from "../context/AnalysisContext";
import { useAuth } from "../context/AuthContext";

/**
 * Analysis results are kept in sessionStorage so they survive a reload. They
 * belong to whoever was signed in, so they are discarded as soon as nobody is
 * (logout, or a session that could not be restored) -- the next person using
 * this tab never sees the previous user's light curve or results.
 */
export default function AnalysisSessionGuard() {
  const { status } = useAuth();
  const { reset } = useAnalysis();
  const resetRef = useRef(reset);
  resetRef.current = reset;

  useEffect(() => {
    if (status === "anonymous") resetRef.current();
  }, [status]);

  return null;
}
