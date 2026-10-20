import Icon from "./Icon";

const STATUS_LABELS = {
  estimated: { text: "estimated from light curve", icon: "sensors" },
  derived: { text: "derived", icon: "functions" },
  catalog: { text: "catalog", icon: "travel_explore" },
};

// Purely a presentation grouping (Haulix-style grouped records) -- does not
// change which fields exist, their order sent to the backend, or any
// validation/locking behavior below. Any canonical not listed here falls
// back to "Other Parameters" rather than being silently dropped.
const CATEGORY_ORDER = ["Transit Signal", "Planet", "Stellar", "Sky Position", "Other Parameters"];
const CATEGORY_BY_CANONICAL = {
  koi_score: "Transit Signal",
  koi_period: "Transit Signal",
  koi_time0bk: "Transit Signal",
  koi_impact: "Transit Signal",
  koi_duration: "Transit Signal",
  koi_depth: "Transit Signal",
  koi_model_snr: "Transit Signal",
  koi_tce_plnt_num: "Transit Signal",
  koi_prad: "Planet",
  koi_teq: "Planet",
  koi_insol: "Planet",
  koi_steff: "Stellar",
  koi_slogg: "Stellar",
  koi_srad: "Stellar",
  koi_kepmag: "Stellar",
  ra: "Sky Position",
  dec: "Sky Position",
};

function groupFeatures(features) {
  const byCategory = new Map();
  for (const feature of features) {
    const category = CATEGORY_BY_CANONICAL[feature.canonical] || "Other Parameters";
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push(feature);
  }
  return CATEGORY_ORDER
    .filter((category) => byCategory.has(category))
    .map((category) => ({ category, features: byCategory.get(category) }));
}

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
  const groups = groupFeatures(features);

  return (
    <div className="param-form-grid">
      {groups.map(({ category, features: groupFeatures }) => (
        <div className="param-section" key={category}>
          <div className="param-section-heading">{category}</div>
          {groupFeatures.map((feature) => {
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
                        style={{ marginLeft: 6, color: "var(--accent-cyan)", fontSize: "0.7rem", display: "inline-flex", alignItems: "center", gap: 3 }}
                      >
                        <Icon name={statusLabel.icon} size={12} />
                        {statusLabel.text}
                      </span>
                    )}
                    {!statusLabel && isPrefilled && (
                      <span
                        title="Estimated from your uploaded light curve"
                        style={{ marginLeft: 6, color: "var(--accent-cyan)", fontSize: "0.7rem", display: "inline-flex", alignItems: "center", gap: 3 }}
                      >
                        <Icon name="sensors" size={12} />
                        estimated
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
      ))}
    </div>
  );
}
