import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import CsvDropzone from "../components/CsvDropzone";
import ProgressBar from "../components/ProgressBar";
import StateBlock from "../components/StateBlock";
import Icon from "../components/Icon";
import { useAnalysis, STATUS } from "../context/AnalysisContext";

export default function UploadPage() {
  const { status, progress, error, filename, analyze, reset } = useAnalysis();
  const navigate = useNavigate();
  const [objectId, setObjectId] = useState("");
  const [objectIdError, setObjectIdError] = useState(null);

  useEffect(() => {
    // Successful CSV analysis moves to the parameter-entry step, never
    // straight to results -- no prediction has been run yet at this point.
    if (status === STATUS.SUCCESS) {
      navigate("/manual-parameters");
    }
  }, [status, navigate]);

  const isBusy = status === STATUS.UPLOADING || status === STATUS.ANALYZING;

  function handleFileSelected(file) {
    if (!objectId.trim()) {
      setObjectIdError("Object ID is required before you can upload a light curve.");
      return;
    }
    setObjectIdError(null);
    analyze(file, objectId.trim());
  }

  return (
    <div className="fade-in upload-stage">
      <header className="page-header">
        <h1 className="page-title">Upload Light Curve</h1>
        <p className="page-subtitle">
          Upload a CSV with only <strong>time</strong> and <strong>flux</strong> (or{" "}
          <strong>brightness</strong>) columns, together with the object's catalog Object ID. The
          ML service runs a real Box Least Squares transit search and combines it with a catalog
          lookup to automatically derive as many of the 17 model parameters as legitimately
          possible. Only whatever still can't be determined will need a quick manual entry next.
        </p>
      </header>

      <div className="panel">
        <label htmlFor="object-id-input" className="param-label" style={{ display: "block", marginBottom: 8 }}>
          <span className="display-name">
            Object ID <span style={{ color: "var(--danger)" }}>*</span>
          </span>
        </label>
        <input
          id="object-id-input"
          type="text"
          required
          className="param-input"
          style={{ width: "100%", maxWidth: 360, marginBottom: 4 }}
          placeholder="e.g. KIC 11904151"
          value={objectId}
          onChange={(e) => {
            setObjectId(e.target.value);
            if (objectIdError) setObjectIdError(null);
          }}
          disabled={isBusy}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "0.8rem", marginTop: 0, marginBottom: 8 }}>
          Enter the astronomical catalog ID of the star/object corresponding to this light curve
          (a KIC ID, KOI name, or confirmed Kepler planet name — e.g. "KIC 11904151"). This lets
          the backend resolve the stellar parameters (temperature, radius, sky position,
          magnitude) the model needs by looking your object up online, live, against the NASA
          Exoplanet Archive. A unique catalog identifier is required rather than a star name,
          since names aren't reliably unique.
        </p>
        {objectIdError && (
          <p role="alert" style={{ color: "var(--danger)", fontSize: "0.85rem", marginTop: 0, marginBottom: 20 }}>
            {objectIdError}
          </p>
        )}

        <CsvDropzone onFileSelected={handleFileSelected} disabled={isBusy} />

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
              icon={<Icon name="error" size={32} />}
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
