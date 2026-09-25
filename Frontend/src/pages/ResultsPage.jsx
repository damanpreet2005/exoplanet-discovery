import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ComingSoonPanel from "../components/ComingSoonPanel";
import StepIndicator from "../components/StepIndicator";
import { useAnalysis, STATUS, FINAL_STATUS } from "../context/AnalysisContext";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function ResultsPage() {
  const { status, result, finalStatus, finalResult, manualParameters } = useAnalysis();
  const navigate = useNavigate();

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

  return (
    <div className="fade-in">
      <StepIndicator current={3} />
      <header className="page-header">
        <h1 className="page-title">Step 3 — Prediction Results</h1>
        <p className="page-subtitle">
          Combined result from your light curve (<strong>{result.filename}</strong>) and the 17
          submitted model parameters.
        </p>
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

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Physics Validation</h3>
        <ComingSoonPanel title="Physics Validation" message={result.physics_validation.message} />
      </div>

      <div className="panel">
        <details>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: "0.85rem" }}>
            17 submitted model parameters (exactly what produced this result)
          </summary>
          <table className="feature-table">
            <tbody>
              {Object.entries(manualParameters || {}).map(([key, value]) => (
                <tr key={key}>
                  <th>{key}</th>
                  <td className="value">{typeof value === "number" ? value : String(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </div>
  );
}
