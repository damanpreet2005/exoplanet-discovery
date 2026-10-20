/**
 * Minimal, dependency-free inline-SVG bar chart comparing an observed value
 * against the value the adopted physical model expects. Built specifically
 * NOT to require a charting library (keeps the dependency list unchanged)
 * and to only ever plot real numbers it was given -- if either value is
 * null, the bar for it is omitted and labeled "unavailable" rather than
 * drawn as zero (which would misleadingly imply a measured zero).
 */
export default function ComparisonBarChart({ observedLabel, observedValue, expectedLabel, expectedValue, unit }) {
  const values = [observedValue, expectedValue].filter((v) => typeof v === "number" && Number.isFinite(v));
  const max = values.length ? Math.max(...values) * 1.15 : 1;

  const bars = [
    { label: observedLabel, value: observedValue, className: "bar-observed" },
    { label: expectedLabel, value: expectedValue, className: "bar-expected" },
  ];

  return (
    <div className="comparison-chart" role="img" aria-label={`${observedLabel} vs ${expectedLabel}, in ${unit}`}>
      {bars.map((bar) => {
        const pct = typeof bar.value === "number" && Number.isFinite(bar.value) && max > 0
          ? Math.max((bar.value / max) * 100, 2)
          : 0;
        return (
          <div className="comparison-row" key={bar.label}>
            <span className="comparison-row-label">{bar.label}</span>
            <div className="comparison-track">
              {typeof bar.value === "number" && Number.isFinite(bar.value) ? (
                <div className={`comparison-fill ${bar.className}`} style={{ width: `${pct}%` }} />
              ) : null}
            </div>
            <span className="comparison-row-value">
              {typeof bar.value === "number" && Number.isFinite(bar.value)
                ? `${bar.value.toFixed(2)} ${unit}`
                : "Unavailable"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
