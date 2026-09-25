import { Link } from "react-router-dom";
import StateBlock from "../components/StateBlock";
import ComingSoonPanel from "../components/ComingSoonPanel";
import { useAnalysis, STATUS } from "../context/AnalysisContext";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function ResultsPage() {
  const { status, result } = useAnalysis();

  if (status !== STATUS.SUCCESS || !result) {
    return (
      <div className="fade-in">
        <header className="page-header">
          <h1 className="page-title">Results</h1>
        </header>
        <div className="panel">
          <StateBlock
            icon="🛰️"
            title="No analysis yet"
            description="Upload a light curve to see its prediction here."
            action={
              <Link to="/" className="btn btn-primary" style={{ marginTop: 12 }}>
                Go to Upload
              </Link>
            }
          />
        </div>
      </div>
    );
  }

  const { diagnostics, characterisation } = result;

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Analysis Result</h1>
        <p className="page-subtitle">{result.filename}</p>
      </header>

      {result.warnings?.length > 0 && (
        <div className="panel" style={{ borderColor: "rgba(255, 207, 92, 0.4)" }}>
          {result.warnings.map((w, i) => (
            <p key={i} style={{ margin: 0, color: "var(--warning)", fontSize: "0.85rem" }}>
              ⚠️ {w}
            </p>
          ))}
        </div>
      )}

      <div className="summary-row">
        <div className="summary-tile">
          <div className={`value`} style={{ color: result.prediction === 1 ? "var(--success)" : "var(--text-muted)" }}>
            {result.prediction}
          </div>
          <div className="label">Predicted class</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(result.weighted_probability)}</div>
          <div className="label">Weighted probability</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(result.random_forest_probability)}</div>
          <div className="label">Random Forest (w={result.weights.random_forest})</div>
        </div>
        <div className="summary-tile">
          <div className="value">{pct(result.cnn_probability)}</div>
          <div className="label">1D CNN (w={result.weights.cnn})</div>
        </div>
        <div className="summary-tile">
          <div className="value">{result.cache_hit ? "Hit" : "Computed"}</div>
          <div className="label">Cache</div>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Transit Search Diagnostics</h3>
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
        <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", marginTop: 12, marginBottom: 0 }}>
          An odd/even ratio far from 1.0, or a significant secondary eclipse depth, are classic
          signs of an eclipsing binary rather than a genuine planet.
        </p>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Physics Validation</h3>
        <ComingSoonPanel title="Physics Validation" message={result.physics_validation.message} />
      </div>

      <div className="panel">
        <details>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: "0.85rem" }}>
            17 internal model features (extracted)
          </summary>
          <table className="feature-table">
            <tbody>
              {Object.entries(result.extracted_features).map(([key, value]) => (
                <tr key={key}>
                  <th>{key}</th>
                  <td className="value">{typeof value === "number" ? value.toFixed(4) : value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </div>
  );
}
