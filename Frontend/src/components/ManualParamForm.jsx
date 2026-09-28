const STATUS_LABELS = {
  estimated: "✦ estimated from light curve",
  derived: "✦ derived",
  catalog: "✦ catalog",
};

/**
 * Aligned grid form for the 17-parameter input mode. All fields share one
 * CSS Grid container (see .param-form-grid in index.css) so label/input/unit
 * columns line up across every row regardless of label text length.
 *
 * `statusByCanonical` (optional) maps canonical -> "estimated" | "derived" |
 * "catalog" | "unavailable". Any field whose status is one of the first
 * three renders as a locked, read-only row with a status badge instead of
 * an input, UNLESS `expertMode` is true -- this is what prevents accidental
 * overwrites of automatically-derived values while still allowing a
 * deliberate manual override. Fields with no status (or "unavailable")
 * always render as editable inputs. When `statusByCanonical` is omitted
 * entirely, every field renders as a plain editable input (original
 * all-manual behavior).
 */
export default function ManualParamForm({ features, values, onChange, disabled, prefilled, statusByCanonical, expertMode }) {
  return (
    <div className="param-form-grid">
      {features.map((feature) => {
        const status = statusByCanonical?.[feature.canonical];
        const isLocked = status && status !== "unavailable" && !expertMode;
        const isPrefilled = prefilled?.has(feature.canonical);
        const statusLabel = status ? STATUS_LABELS[status] : null;

        return (
          <div className="param-row" key={feature.canonical}>
            <label className="param-label" htmlFor={`param-${feature.canonical}`}>
              <span className="display-name">
                {feature.display}
                {statusLabel && (
                  <span
                    title={`This value was ${status} automatically`}
                    style={{ marginLeft: 6, color: "var(--accent-cyan)", fontSize: "0.7rem" }}
                  >
                    {statusLabel}
                  </span>
                )}
                {!statusLabel && isPrefilled && (
                  <span title="Estimated from your uploaded light curve" style={{ marginLeft: 6, color: "var(--accent-cyan)", fontSize: "0.7rem" }}>
                    ✦ estimated
                  </span>
                )}
              </span>
              <span className="canonical-name">({feature.canonical})</span>
            </label>
            {isLocked ? (
              <span id={`param-${feature.canonical}`} className="param-input" style={{ display: "inline-flex", alignItems: "center", color: "var(--text-muted)" }}>
                {values[feature.canonical] ?? ""}
              </span>
            ) : (
              <input
                id={`param-${feature.canonical}`}
                className="param-input"
                type="number"
                step="any"
                disabled={disabled}
                value={values[feature.canonical] ?? ""}
                onChange={(e) => onChange(feature.canonical, e.target.value)}
              />
            )}
            <span className="param-unit">{feature.unit}</span>
          </div>
        );
      })}
    </div>
  );
}
