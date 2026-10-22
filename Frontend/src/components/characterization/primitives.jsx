import Icon from "../Icon";

/**
 * Display primitives for a Planet Characterization Engine report. Values,
 * uncertainties and rounding all come from the report (`display`); nothing
 * is calculated or re-rounded here.
 */

export const PROVENANCE_LABELS = {
  catalog: "Catalogue",
  observed: "Observed",
  fitted: "Fitted",
  derived: "Derived",
  model_estimated: "Model estimate",
  manual_override: "Expert override",
  assumed: "Assumed",
  unavailable: "Unavailable",
};

const RELIABILITY = {
  reliable: { icon: "check_circle", label: "Reliable", className: "char-rel reliable" },
  low_confidence: { icon: "warning", label: "Low confidence", className: "char-rel low" },
  unreliable: { icon: "error", label: "Unreliable", className: "char-rel unreliable" },
};

export const STATUS_TEXT = {
  complete: "Complete",
  partial: "Partial",
  no_transit: "No transit detected",
  failed: "Failed",
};

const UNIT_DISPLAY = { "days (uploaded time system)": "d", "log10(cm/s²)": "dex (cgs)" };

export function formatUnit(unit) {
  if (!unit) return "";
  return ` ${UNIT_DISPLAY[unit] || unit}`;
}

export function isComputed(p) {
  return Boolean(p) && p.status === "computed";
}

/** "2.35 +0.24 / −0.21 R⊕", or "Unavailable" -- never a zero for missing data. */
export function paramText(p) {
  if (!isComputed(p)) return "Unavailable";
  // Descriptive displays ("Undefined (circular orbit)") carry no unit.
  return /^[-−+]?\d/.test(p.display) ? `${p.display}${formatUnit(p.unit)}` : p.display;
}

export function ReliabilityTag({ level }) {
  const cfg = RELIABILITY[level];
  if (!cfg) return null;
  return (
    <span className={cfg.className}>
      <Icon name={cfg.icon} size={14} filled /> {cfg.label}
    </span>
  );
}

// Evidence classes that refine a provenance label (see the engine's
// EVIDENCE_BY_PROVENANCE): a catalogue value can be a direct measurement.
const EVIDENCE_LABELS = { measured: "Measured" };

export function ProvenanceChip({ provenance, evidence }) {
  const label = (provenance === "catalog" && EVIDENCE_LABELS[evidence]) || PROVENANCE_LABELS[provenance] || provenance;
  const cls = provenance === "catalog" && evidence === "measured" ? "prov-measured" : `prov-${provenance}`;
  return <span className={`char-chip ${cls}`}>{label}</span>;
}

export function StatusChip({ status }) {
  return <span className={`char-chip status-${status}`}>{STATUS_TEXT[status] || status}</span>;
}

const EVIDENCE_TEXT = {
  measured: "A direct measurement, taken from a catalogue.",
  catalogue_derived: "Taken from a catalogue; the catalogue value is itself derived from observations through a model or calibration (not a direct measurement).",
};

const BASIS_TEXT = {
  catalog: "Taken from a catalogue (a published measurement).",
  observed: "Measured directly from the light curve.",
  fitted: "Fitted to the light curve with a transit model.",
  derived: "Calculated from other values through a physical relation.",
  model_estimated: "Estimated from an empirical model, not measured.",
  manual_override: "Supplied by an expert, replacing the automatic value.",
  assumed: "Assumed, not measured.",
  unavailable: "Could not be determined.",
};

const RELIABILITY_TEXT = {
  reliable: "Reliable: well-constrained, with a relative uncertainty within the engine's 30% threshold.",
  low_confidence: "Low confidence:",
  unreliable: "Unreliable:",
  not_assessed: "Not assessed: an assumption has no measurement uncertainty.",
};

/** Expandable provenance / method / uncertainty / dependency details for one parameter. */
export function ParamDetails({ p, lookup, reasonShown = false }) {
  const deps = (p.depends_on || []).map((d) => lookup?.[d]?.label || d);
  const why = p.reliability === "reliable" || p.reliability === "not_assessed"
    ? RELIABILITY_TEXT[p.reliability]
    : reasonShown
      ? `${(RELIABILITY_TEXT[p.reliability] || "").replace(/:$/, "")} (explanation above).`
      : `${RELIABILITY_TEXT[p.reliability] || ""} ${p.reason || ""}`.trim();
  return (
    <details className="param-why">
      <summary>How this was determined</summary>
      <dl>
        <div><dt>Basis</dt><dd>{(p.provenance === "catalog" && EVIDENCE_TEXT[p.evidence]) || BASIS_TEXT[p.provenance] || p.provenance}</dd></div>
        {(p.source || p.method) && <div><dt>Source &amp; method</dt><dd>{p.method || p.source}{p.source && p.method && p.source !== p.method ? ` (${p.source})` : ""}</dd></div>}
        {p.equation && <div><dt>Relation</dt><dd><code className="char-eq">{p.equation}</code></dd></div>}
        {isComputed(p) && <div><dt>Uncertainty</dt><dd>{uncertaintyText(p.uncertainty)}</dd></div>}
        {deps.length > 0 && <div><dt>Depends on</dt><dd>{deps.join(", ")}</dd></div>}
        {isComputed(p) ? <div><dt>Confidence</dt><dd>{why}</dd></div> : <div><dt>Why unavailable</dt><dd>{p.reason || "—"}</dd></div>}
      </dl>
    </details>
  );
}

/**
 * Compact parameter rows (label | value, provenance & reliability beneath,
 * the reason for any reduced confidence, and expandable details). Used
 * inside dashboard panels; each row carries data-testid
 * `char-param-<name>`, so a parameter must appear at most once per view.
 * `lookup` (all report parameters) names dependencies by label.
 */
export function ParamList({ params, lookup }) {
  const rows = params.filter(Boolean);
  if (!rows.length) return <p className="char-muted">No parameters in this group.</p>;
  // A reason shared by consecutive rows (e.g. one degenerate fit parameter
  // behind several dependents) is shown once, under the first of them.
  let lastReason = null;
  return (
    <dl className="param-list">
      {rows.map((p) => {
        const unavailable = !isComputed(p);
        const showReason = (unavailable || p.reliability === "low_confidence" || p.reliability === "unreliable")
          && p.reason && p.reason !== lastReason;
        if (showReason) lastReason = p.reason;
        return (
          <div key={p.name} className={`param-list-row${unavailable ? " is-unavailable" : ""}`} data-testid={`char-param-${p.name}`}>
            <dt>{p.label}</dt>
            <dd>
              <span className="param-list-value">{paramText(p)}</span>
              <span className="param-list-meta">
                <ProvenanceChip provenance={p.provenance} evidence={p.evidence} />
                <ReliabilityTag level={p.reliability} />
              </span>
            </dd>
            {showReason && <dd className="param-list-reason">{p.reason}</dd>}
            <dd className="param-list-details"><ParamDetails p={p} lookup={lookup} reasonShown={showReason} /></dd>
          </div>
        );
      })}
    </dl>
  );
}

export function uncertaintyText(u) {
  if (!u) return "None available";
  const parts = [`${u.method.replace(/_/g, " ")}, ${u.interval}`];
  if (!u.complete && u.excluded_inputs?.length) parts.push(`excludes ${u.excluded_inputs.join(", ")} (no uncertainty)`);
  if (u.systematic?.length) parts.push(`not included: ${u.systematic.join(" ")}`);
  return parts.join("; ");
}

/** Full per-parameter method / provenance / uncertainty / dependency table. */
export function ParamDetailsTable({ params }) {
  return (
    <div className="table-scroll">
      <table className="feature-table char-detail-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Value</th>
            <th>Source &amp; method</th>
            <th>Uncertainty</th>
            <th>Depends on</th>
          </tr>
        </thead>
        <tbody>
          {params.filter(Boolean).map((p) => (
            <tr key={p.name}>
              <th>{p.label}</th>
              <td className="value">
                {isComputed(p) ? `${p.display}${formatUnit(p.unit)}` : "—"}
                {p.alternate_units?.map((alt) => (
                  <div key={alt.unit} className="char-alt">= {alt.value} {alt.unit}</div>
                ))}
                {p.systematic_range && (
                  <div className="char-alt">
                    Systematic range {p.systematic_range.min}–{p.systematic_range.max} {p.systematic_range.unit}
                  </div>
                )}
              </td>
              <td>
                <ProvenanceChip provenance={p.provenance} evidence={p.evidence} /> {p.method || p.reason}
                {p.equation && <code className="char-eq">{p.equation}</code>}
                {p.original && (
                  <div className="char-alt">
                    Automatic value: {p.original.display} ({PROVENANCE_LABELS[p.original.provenance] || p.original.provenance})
                  </div>
                )}
              </td>
              <td>{isComputed(p) ? uncertaintyText(p.uncertainty) : "—"}</td>
              <td>
                {p.depends_on?.length ? p.depends_on.join(", ") : "—"}
                {p.depends_on_override?.length > 0 && (
                  <div className="char-override-dep">
                    <Icon name="tune" size={13} /> Uses override: {p.depends_on_override.join(", ")}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One classification with the share of Monte Carlo samples in each category. */
export function ClassificationCard({ c }) {
  const computed = c.status === "computed";
  const probs = Object.entries(c.probabilities || {}).sort((a, b) => b[1] - a[1]);
  return (
    <div className={`class-card${computed ? "" : " is-unavailable"}`}>
      <div className="class-card-label">{c.label}</div>
      <div className="class-card-value">{c.category || "Unavailable"}</div>
      {computed && probs.length > 0 && (
        <div className="class-probs" aria-label="Share of Monte Carlo samples per category">
          {probs.map(([name, v]) => (
            <div className="class-prob" key={name}>
              <span className="class-prob-name">{name}</span>
              <span className="class-prob-track"><span style={{ width: `${Math.max(v * 100, 1)}%` }} /></span>
              <span className="class-prob-value">{Math.round(v * 100)}%</span>
            </div>
          ))}
        </div>
      )}
      <p className="class-card-basis">
        <strong>Based on:</strong> {c.depends_on?.join(", ") || "—"}. {c.basis}
      </p>
      {c.caveats?.length > 0 && (
        <ul className="class-card-caveats">
          {c.caveats.map((cv, i) => <li key={i}>{cv}</li>)}
        </ul>
      )}
    </div>
  );
}

export const CLASSIFICATION_DISCLAIMER =
  "Classifications describe size and irradiation only. They do not establish composition, atmosphere, habitability, or that this candidate is a confirmed planet.";
