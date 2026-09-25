import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import CsvDropzone from "../components/CsvDropzone";
import ProgressBar from "../components/ProgressBar";
import StateBlock from "../components/StateBlock";
import StepIndicator from "../components/StepIndicator";
import { useAnalysis, STATUS } from "../context/AnalysisContext";

export default function UploadPage() {
  const { status, progress, error, filename, analyze, reset } = useAnalysis();
  const navigate = useNavigate();

  useEffect(() => {
    // Successful CSV analysis moves to the parameter-entry step, never
    // straight to results -- no prediction has been run yet at this point.
    if (status === STATUS.SUCCESS) {
      navigate("/manual-parameters");
    }
  }, [status, navigate]);

  const isBusy = status === STATUS.UPLOADING || status === STATUS.ANALYZING;

  return (
    <div className="fade-in">
      <StepIndicator current={1} />
      <header className="page-header">
        <h1 className="page-title">Step 1 — Upload Light Curve</h1>
        <p className="page-subtitle">
          Upload a CSV with only <strong>time</strong> and <strong>flux</strong> (or{" "}
          <strong>brightness</strong>) columns. The ML service runs a real Box Least Squares
          transit search to analyze the light curve — nothing else is required, and there's no
          minimum observation duration. This is analysis only; you'll enter the planet/stellar
          parameters next, and the final prediction runs once both are provided.
        </p>
      </header>

      <div className="panel">
        <CsvDropzone onFileSelected={analyze} disabled={isBusy} />

        {isBusy && (
          <div style={{ marginTop: 24 }}>
            <ProgressBar
              percent={status === STATUS.UPLOADING ? progress : 100}
              label={status === STATUS.UPLOADING ? `Uploading ${filename}` : "Analyzing — running transit search…"}
            />
          </div>
        )}

        {status === STATUS.ERROR && (
          <div style={{ marginTop: 24 }}>
            <StateBlock
              variant="error"
              icon="⚠️"
              title={error?.code || "Analysis failed"}
              description={error?.message || "Something went wrong while analyzing the file."}
              action={
                <button className="btn btn-ghost" onClick={reset} style={{ marginTop: 12 }}>
                  Try again
                </button>
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}
