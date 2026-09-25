import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import CsvDropzone from "../components/CsvDropzone";
import ProgressBar from "../components/ProgressBar";
import StateBlock from "../components/StateBlock";
import { useAnalysis, STATUS } from "../context/AnalysisContext";

export default function UploadPage() {
  const { status, progress, error, filename, analyze, reset } = useAnalysis();
  const navigate = useNavigate();

  useEffect(() => {
    if (status === STATUS.SUCCESS) {
      navigate("/results");
    }
  }, [status, navigate]);

  const isBusy = status === STATUS.UPLOADING || status === STATUS.ANALYZING;

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Upload a Light Curve</h1>
        <p className="page-subtitle">
          Upload a CSV with only <strong>time</strong> and <strong>flux</strong> (or{" "}
          <strong>brightness</strong>) columns. The ML service runs a real Box Least Squares
          transit search on the light curve and generates the model's 17 internal features
          automatically — nothing else is required, and there's no minimum observation duration.
        </p>
      </header>

      <div className="panel">
        <CsvDropzone onFileSelected={analyze} disabled={isBusy} />

        {isBusy && (
          <div style={{ marginTop: 24 }}>
            <ProgressBar
              percent={status === STATUS.UPLOADING ? progress : 100}
              label={status === STATUS.UPLOADING ? `Uploading ${filename}` : "Analyzing — running transit search + Random Forest + CNN…"}
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
