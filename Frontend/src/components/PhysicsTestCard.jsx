import PhysicsStatusBadge from "./PhysicsStatusBadge";
import ComparisonBarChart from "./ComparisonBarChart";

function fmt(measurement, digits = 3) {
  if (!measurement || measurement.value === null || measurement.value === undefined) return "Unavailable";
  const v = measurement.value;
  const rounded = Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(digits);
  return `${rounded}${measurement.unit ? ` ${measurement.unit}` : ""}`;
}

// Each test's primary observed/expected metric key -- used to decide which
// pair to plot as a comparison bar chart. Orbital Physics has no single
// observed-vs-expected pair (it checks self-consistency instead), so it's
// omitted here deliberately.
const CHART_METRIC_KEY = {
  planet_size: "transit_depth",
  transit_duration: "transit_duration",
};

export default function PhysicsTestCard({ test }) {
  const chartKey = CHART_METRIC_KEY[test.test_id];
  const observedMetric = chartKey ? test.observed?.[chartKey] : null;
  const expectedMetric = chartKey ? test.expected?.[chartKey] : null;
  const hasChartData = observedMetric && expectedMetric
    && typeof observedMetric.value === "number" && typeof expectedMetric.value === "number";

  return (
    <div className="panel physics-card">
      <div className="physics-card-header">
        <h3 style={{ margin: 0 }}>{test.name}</h3>
        <PhysicsStatusBadge status={test.status} />
      </div>

      <p className="physics-card-summary">{test.summary}</p>

      {hasChartData && (
        <ComparisonBarChart
          observedLabel="Observed"
          observedValue={observedMetric.value}
          expectedLabel="Expected"
          expectedValue={expectedMetric.value}
          unit={observedMetric.unit}
        />
      )}

      <div className="physics-metric-grid">
        {Object.entries(test.observed || {}).map(([key, m]) => (
          <div className="physics-metric" key={`observed-${key}`}>
            <span className="physics-metric-label">Observed {key.replace(/_/g, " ")}</span>
            <span className="physics-metric-value">{fmt(m)}</span>
          </div>
        ))}
        {Object.entries(test.expected || {}).map(([key, m]) => (
          <div className="physics-metric" key={`expected-${key}`}>
            <span className="physics-metric-label">Expected {key.replace(/_/g, " ")}</span>
            <span className="physics-metric-value">{fmt(m)}</span>
          </div>
        ))}
        {test.calculation?.derived && Object.entries(test.calculation.derived).map(([key, m]) => (
          <div className="physics-metric" key={`derived-${key}`}>
            <span className="physics-metric-label">{key.replace(/_/g, " ")}</span>
            <span className="physics-metric-value">{fmt(m)}</span>
          </div>
        ))}
      </div>

      {test.discrepancy && (
        <p className="physics-discrepancy-line">
          Discrepancy: {fmt(test.discrepancy.absolute)}
          {test.discrepancy.relative_valid && test.discrepancy.relative !== null
            ? ` (${(test.discrepancy.relative * 100).toFixed(1)}% relative, tolerance ${(test.tolerance.relative_tolerance * 100).toFixed(0)}%)`
            : " (relative discrepancy not mathematically valid here)"}
        </p>
      )}

      {test.consistency_checks && test.consistency_checks.length > 0 && (
        <ul className="physics-consistency-list">
          {test.consistency_checks.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}

      {test.missing_data && test.missing_data.length > 0 && (
        <p className="physics-missing-line">
          Missing or invalid: <code>{test.missing_data.join(", ")}</code>
        </p>
      )}

      <details className="physics-calc-details">
        <summary>View Calculation Details</summary>
        <div className="physics-calc-body">
          <p className="physics-equation"><strong>Equation:</strong> {test.calculation?.equation}</p>

          <h4>Inputs</h4>
          <table className="feature-table">
            <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
            <tbody>
              {Object.entries(test.calculation?.inputs || {}).map(([key, m]) => (
                <tr key={key}>
                  <th>{key}</th>
                  <td className="value">{fmt(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {test.calculation?.derived && Object.keys(test.calculation.derived).length > 0 && (
            <>
              <h4>Derived Values</h4>
              <table className="feature-table">
                <thead><tr><th>Quantity</th><th>Value</th></tr></thead>
                <tbody>
                  {Object.entries(test.calculation.derived).map(([key, m]) => (
                    <tr key={key}>
                      <th>{key.replace(/_/g, " ")}</th>
                      <td className="value">{fmt(m)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h4>Assumptions</h4>
          <ul>
            {test.assumptions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>

          <h4>Tolerance</h4>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>
            {test.tolerance.relative_tolerance !== null
              ? `±${(test.tolerance.relative_tolerance * 100).toFixed(0)}% relative discrepancy. `
              : ""}
            {test.tolerance.rationale}
          </p>
        </div>
      </details>
    </div>
  );
}
