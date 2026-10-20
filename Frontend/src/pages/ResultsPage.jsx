import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import StepIndicator from "../components/StepIndicator";
import PhysicsStatusBadge from "../components/PhysicsStatusBadge";
import Icon from "../components/Icon";
import { useAnalysis, STATUS, FINAL_STATUS, PHYSICS_STATUS } from "../context/AnalysisContext";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function ResultsPage() {
  const {
    status, result, finalStatus, finalResult, manualParameters, reset,
    physicsStatus, physicsResult, physicsError, physicsResultIsCurrent, startPhysicsValidation,
  } = useAnalysis();
  const navigate = useNavigate();

  async function handleStartPhysicsValidation() {
    await startPhysicsValidation();
    navigate("/physics-validation");
  }

  function handleNewPrediction() {
    // Clears the light curve, manual parameters, and final result (both in
    // memory and from sessionStorage) so the next visit to Page 1 starts a
    // genuinely fresh session rather than reusing anything from this one.
    reset();
    navigate("/");
  }

  // Route guards: results only exist once BOTH the light curve and the
  // combined prediction are present -- never an independent CSV-only or
  // parameters-only result.
  useEffect(() => {
    if (status !== STATUS.SUCCESS || !result) {
      navigate("/", { replace: true });
    } else if (finalStatus !== FINAL_STATUS.SUCCESS || !finalResult) {
      navigate("/manual-parameters", { replace: true });
    }
  }, [status, result, finalStatus, finalResult, navigate]);

  if (status !== STATUS.SUCCESS || !result || finalStatus !== FINAL_STATUS.SUCCESS || !finalResult) {
    return null; // redirecting
  }

  const { diagnostics, characterisation } = result;

  const STELLAR_DISPLAY = [
    { canonical: "koi_srad", label: "Stellar Radius", unitSuffix: " R☉" },
    { canonical: "koi_steff", label: "Effective Temperature", unitSuffix: " K" },
    { canonical: "koi_slogg", label: "Surface Gravity", unitSuffix: " log10(cm/s²)" },
    { canonical: "ra", label: "Right Ascension", unitSuffix: "°" },
    { canonical: "dec", label: "Declination", unitSuffix: "°" },
    { canonical: "koi_kepmag", label: "Kepler Magnitude", unitSuffix: "" },
  ];
  const SOURCE_LABELS = {
    estimated: "Light curve / BLS",
    derived: "Derived",
    catalog: "Astronomical catalog",
    unavailable: "Unavailable",
  };

  return (
    <div className="fade-in">
      <StepIndicator current={3} />
      <header className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">Step 3 — Prediction Results</h1>
          <p className="page-subtitle">
            Combined result from your light curve (<strong>{result.filename}</strong>) and the 17
            submitted model parameters.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={handleNewPrediction}>
          <Icon name="refresh" size={16} /> New Prediction
        </button>
      </header>

      {/* NOTE: result.warnings (from the Page-1 light-curve analysis) is
          deliberately NOT shown here. It describes the best-effort transit-
          search reconstruction, not this final prediction -- which comes
          from the manually-entered/reviewed 17 parameters through the
          verified feature mapping. The accurate caveat for the handful of
          light-curve-suggested fields is already shown per-field ("✦
          estimated") on the parameter page, where it actually applies. */}

      <div className="summary-row">
        <div className="summary-tile">
          <div className="value" style={{ color: finalResult.prediction === 1 ? "var(--success)" : "var(--text-muted)" }}>
            {finalResult.prediction}
          </div>
          <div className="label">Predicted class</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(finalResult.weighted_probability)}</div>
          <div className="label">Weighted probability</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(finalResult.random_forest_probability)}</div>
          <div className="label">Random Forest (w={finalResult.weights.random_forest})</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(finalResult.cnn_probability)}</div>
          <div className="label">2D CNN (w={finalResult.weights.cnn})</div>
        </div>
        <div className="summary-tile">
          <div className="value">{finalResult.model_version}</div>
          <div className="label">Model version</div>
        </div>
      </div>

      {result.features && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Object Information</h3>
          <dl className="candidate-detail" style={{ marginBottom: 12 }}>
            <div>
              <dt>Object ID</dt>
              <dd>{result.object_id}</dd>
            </div>
          </dl>
          <h4 style={{ marginBottom: 8, fontSize: "0.9rem", color: "var(--text-muted)" }}>Stellar Parameters</h4>
          <div className="table-scroll">
            <table className="feature-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Value</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {STELLAR_DISPLAY.map(({ canonical, label, unitSuffix }) => {
                  const fv = result.features[canonical];
                  return (
                    <tr key={canonical}>
                      <th>{label}</th>
                      <td className="value">
                        {fv && fv.value !== null && fv.value !== undefined
                          ? `${typeof fv.value === "number" ? fv.value.toFixed(3).replace(/\.?0+$/, "") : fv.value}${unitSuffix}`
                          : "Unavailable"}
                      </td>
                      <td style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                        {fv ? SOURCE_LABELS[fv.status] || fv.status : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Light Curve Diagnostics</h3>
        <dl className="candidate-detail">
          <div>
            <dt>Points used / dropped</dt>
            <dd>{diagnostics.n_points_used} / {diagnostics.n_points_dropped}</dd>
          </div>
          <div>
            <dt>Observation baseline</dt>
            <dd>{diagnostics.baseline_days.toFixed(2)} days</dd>
          </div>
          <div>
            <dt>BLS best period</dt>
            <dd>{diagnostics.bls_period_days.toFixed(4)} days</dd>
          </div>
          <div>
            <dt>Transit duration</dt>
            <dd>{diagnostics.bls_duration_hours.toFixed(2)} hours</dd>
          </div>
          <div>
            <dt>Transit depth</dt>
            <dd>{diagnostics.bls_depth_ppm.toFixed(1)} ppm</dd>
          </div>
          <div>
            <dt>Transit SNR</dt>
            <dd>{diagnostics.bls_transit_snr.toFixed(2)}</dd>
          </div>
          <div>
            <dt>Transits observed</dt>
            <dd>{diagnostics.num_transits_observed}</dd>
          </div>
        </dl>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Characterisation — Transit Vetting</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: -8 }}>{characterisation.note}</p>
        <dl className="candidate-detail">
          <div>
            <dt>Odd/even depth ratio</dt>
            <dd>{characterisation.odd_even_depth_ratio.toFixed(3)}</dd>
          </div>
          <div>
            <dt>Secondary eclipse depth</dt>
            <dd>{characterisation.secondary_eclipse_depth_ppm.toFixed(1)} ppm</dd>
          </div>
        </dl>
      </div>

      <div className="panel physics-teaser">
        <div className="physics-teaser-header">
          <div>
            <h3 style={{ margin: "0 0 6px" }}>Physics Validation</h3>
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: 0, maxWidth: 560 }}>
              Stage 2 independently checks this candidate's reported transit depth, transit duration, and orbital
              configuration against standard physics -- separately from the classifier above. A promising
              prediction does not by itself mean these physical checks pass.
            </p>
          </div>
          {physicsResultIsCurrent && physicsResult && <PhysicsStatusBadge status={physicsResult.overall_status} size="lg" />}
        </div>

        {physicsStatus === PHYSICS_STATUS.ERROR && (
          <p style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
            {physicsError?.message || "Physics validation failed. Try again."}
          </p>
        )}

        <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
          <button
            className="btn btn-primary"
            onClick={handleStartPhysicsValidation}
            disabled={physicsStatus === PHYSICS_STATUS.RUNNING}
          >
            {physicsStatus === PHYSICS_STATUS.RUNNING ? (
              <>
                <Icon name="progress_activity" size={16} className="icon-spin" /> Running Physics Validation…
              </>
            ) : physicsResultIsCurrent && physicsResult ? (
              <>
                View Physics Validation <Icon name="arrow_forward" size={16} />
              </>
            ) : (
              <>
                <Icon name="science" size={16} /> Start Physics Validation
              </>
            )}
          </button>
        </div>
      </div>

      <div className="panel">
        <details open={Boolean(result.features)}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: "0.85rem" }}>
            17 submitted model parameters (exactly what produced this result)
          </summary>
          <div className="table-scroll">
            <table className="feature-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Value</th>
                  {result.features && <th>Source</th>}
                </tr>
              </thead>
              <tbody>
                {Object.entries(manualParameters || {}).map(([key, value]) => {
                  const fv = result.features?.[key];
                  return (
                    <tr key={key}>
                      <th>{key}</th>
                      <td className="value">{typeof value === "number" ? value : String(value)}</td>
                      {result.features && (
                        <td style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                          {fv ? fv.status : "manual"}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      </div>

      <div style={{ display: "flex", justifyContent: "center", marginTop: 8 }}>
        <button className="btn btn-primary" onClick={handleNewPrediction}>
          <Icon name="refresh" size={16} /> Start a New Prediction
        </button>
      </div>
    </div>
  );
}
