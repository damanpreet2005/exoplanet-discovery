import PhysicsStatusBadge from "./PhysicsStatusBadge";
import ComparisonBarChart from "./ComparisonBarChart";
import TeX from "./TeX";
import Icon from "./Icon";
import { PHYSICS_STAGES, displayUnit } from "../lib/physicsEquations";
import { SOURCE_META, featureSource } from "../lib/featureSources";
import { planetSizeIsCircular } from "../lib/evidence";
import { useAnalysis } from "../context/AnalysisContext";

function num(value, digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1e5 || abs < 1e-3)) return value.toExponential(3);
  return abs >= 1000 ? value.toFixed(1) : Number(value.toPrecision(digits)).toString();
}

function fmt(measurement) {
  const v = num(measurement?.value);
  if (v === null) return "Unavailable";
  const unit = displayUnit(measurement.unit);
  return unit === "—" ? v : `${v} ${unit}`;
}

/** Residual for display: floating-point noise around an exact match
 * (e.g. 5.7e-14 ppm) is shown as 0, not as a meaningless tiny number. */
function residualText(residual, observed) {
  const v = residual?.value;
  const scale = Math.abs(observed?.value ?? 0);
  if (Number.isFinite(v) && scale > 0 && Math.abs(v) < 1e-9 * scale) {
    const unit = displayUnit(residual.unit);
    return unit === "—" ? "0" : `0 ${unit}`;
  }
  return fmt(residual);
}

const INTERPRETATION = {
  PASS: "Consistent with the physical model within the stated tolerance.",
  REVIEW_REQUIRED: "A real discrepancy or geometric inconsistency was found. This is a prompt for closer inspection, not a verdict that the candidate is a false positive.",
  NOT_EVALUATED: "No comparison was performed because a required input was missing or invalid. No result is reported.",
};

function InputTable({ stage, test }) {
  const { result, manualParameters } = useAnalysis();
  const missing = new Set(test.missing_data || []);
  return (
    <div className="table-scroll">
      <table className="feature-table data-table param-table">
        <thead>
          <tr><th>Symbol</th><th>Parameter</th><th>Value used</th><th>Unit</th><th>Source</th></tr>
        </thead>
        <tbody>
          {stage.inputs.map((row) => {
            const m = test.calculation?.inputs?.[row.key];
            // Cross-check inputs are not part of the backend's `inputs`
            // block; show the exact submitted value the check read.
            const raw = m ? m.value : manualParameters?.[row.key];
            const unit = m ? m.unit : result?.features?.[row.key]?.unit;
            const isMissing = missing.has(row.key) || raw === null || raw === undefined;
            const source = featureSource(row.key, result, manualParameters);
            return (
              <tr key={row.key} className={isMissing ? "is-missing" : ""}>
                <td><TeX math={row.sym} /></td>
                <th>
                  {row.name}
                  <span className="mono-sub">{row.key}{row.crossCheck ? " · cross-check only" : ""}</span>
                </th>
                <td className="value">{isMissing ? <span className="missing-flag"><Icon name="error" size={14} /> Missing / invalid</span> : num(raw)}</td>
                <td>{displayUnit(unit)}</td>
                <td><span className={`src-tag ${SOURCE_META[source]?.className || ""}`}>{SOURCE_META[source]?.label || source}</span></td>
              </tr>
            );
          })}
          {stage.constants.map((c) => (
            <tr key={c.sym} className="is-constant">
              <td><TeX math={c.sym} /></td>
              <th>{c.name}</th>
              <td className="value">{c.value}</td>
              <td>{c.unit}</td>
              <td><span className="src-tag src-constant">{c.source}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DerivedTable({ stage, test }) {
  const entries = Object.entries(test.calculation?.derived || {});
  if (!entries.length) return null;
  return (
    <div className="table-scroll">
      <table className="feature-table data-table param-table">
        <thead><tr><th>Symbol</th><th>Intermediate quantity</th><th>Value</th><th>Unit</th></tr></thead>
        <tbody>
          {entries.map(([key, m]) => {
            const meta = stage?.derived?.[key];
            return (
              <tr key={key}>
                <td>{meta ? <TeX math={meta.sym} /> : "—"}</td>
                <th>{meta?.name || key.replace(/_/g, " ")}</th>
                <td className="value">{num(m.value) ?? "Unavailable"}</td>
                <td>{displayUnit(m.unit)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ResultArea({ stage, test }) {
  const evaluated = test.status !== "NOT_EVALUATED";
  const obsKey = Object.keys(test.observed || {})[0];
  const observed = obsKey ? test.observed[obsKey] : null;
  const expected = obsKey ? test.expected?.[obsKey] : null;
  const tol = test.tolerance?.relative_tolerance;
  const hasPair = observed && expected && Number.isFinite(observed.value) && Number.isFinite(expected.value);

  return (
    <div className={`stage-result status-${test.status}`} data-testid={`physics-result-${test.test_id}`}>
      <div className="stage-result-head">
        <h4>Result</h4>
        <PhysicsStatusBadge status={test.status} />
      </div>

      {evaluated && hasPair ? (
        <dl className="result-grid">
          <div><dt>Observed</dt><dd>{fmt(observed)}</dd></div>
          <div><dt>Expected</dt><dd>{fmt(expected)}</dd></div>
          {test.discrepancy && (
            <div>
              <dt>Residual</dt>
              <dd>
                {residualText(test.discrepancy.absolute, observed)}
                {test.discrepancy.relative_valid && test.discrepancy.relative !== null && (
                  <span className="result-sub">{(test.discrepancy.relative * 100).toFixed(1)}% relative</span>
                )}
              </dd>
            </div>
          )}
          <div>
            <dt>Constraint</dt>
            <dd>{tol !== null && tol !== undefined ? `≤ ${(tol * 100).toFixed(0)}% relative` : "—"}</dd>
          </div>
        </dl>
      ) : evaluated ? (
        <>
          {test.consistency_checks?.length > 0 && (
            <ul className="check-list compact">
              {test.consistency_checks.map((c, i) => (
                <li key={i} className="ok"><Icon name="check_circle" size={16} filled /><div><p className="check-note">{c}</p></div></li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="stage-result-missing">
          <Icon name="do_not_disturb_on" size={16} /> Not evaluated — missing or invalid: <code>{(test.missing_data || []).join(", ") || "see summary"}</code>
        </p>
      )}

      {stage?.constraint && tol !== null && tol !== undefined && (
        <div className="stage-constraint"><span>Pass condition</span><TeX math={`\\displaystyle ${stage.constraint(tol)}`} /></div>
      )}
      {stage?.constraintTex && (
        <div className="stage-constraint"><span>Pass condition</span><TeX math={`\\displaystyle ${stage.constraintTex}`} /></div>
      )}

      {evaluated && hasPair && (
        <ComparisonBarChart observedLabel="Observed" observedValue={observed.value} expectedLabel="Expected" expectedValue={expected.value} unit={displayUnit(observed.unit)} />
      )}

      <div className="stage-interpretation">
        <h5>What this means</h5>
        <p>{test.summary}</p>
        <p className="char-muted">{INTERPRETATION[test.status]}</p>
      </div>
    </div>
  );
}

/**
 * One Stage 2 physics check, laid out as: question → equation → parameters
 * (with the actual values used) → result → interpretation. Every number
 * comes from the backend report.
 */
export default function PhysicsTestCard({ test }) {
  const stage = PHYSICS_STAGES[test.test_id];
  const { result, manualParameters } = useAnalysis();
  const circular = test.test_id === "planet_size" && planetSizeIsCircular(result, manualParameters);
  return (
    <details className="panel physics-stage" open data-testid={`physics-stage-${test.test_id}`}>
      <summary className="physics-stage-summary">
        <div className="physics-stage-title">
          <h3>{test.name}</h3>
          {stage && <p>{stage.question}</p>}
        </div>
        <PhysicsStatusBadge status={test.status} />
        {circular && <span className="char-chip prov-assumed" data-testid="physics-circular">Not independent</span>}
        <Icon name="expand_more" size={22} className="physics-stage-chevron" />
      </summary>
      {circular && (
        <p className="physics-circular-note" role="note">
          <Icon name="warning" size={16} />
          {/* One text element: as separate flex items, the text and <sub> tags were laid out as columns. */}
          <span>
            Not an independent check: the planet radius was computed from this same transit depth
            (R<sub>p</sub> = R<sub>⋆</sub>√δ), so the expected depth equals the observed depth by construction and
            this check cannot fail. An independently measured planet radius is needed to test it.
          </span>
        </p>
      )}

      <div className="physics-stage-body">
        <div className="physics-stage-science">
          {stage && <p className="stage-explanation">{stage.explanation}</p>}

          <div className="stage-block">
            <h4>Equation</h4>
            {stage ? (
              <>
                <TeX math={stage.equation} block className="stage-equation" />
                {stage.equationNote && <p className="char-muted">{stage.equationNote}</p>}
                {stage.derivations?.length > 0 && (
                  <details className="stage-derivations">
                    <summary>Supporting relations ({stage.derivations.length})</summary>
                    {stage.derivations.map((d) => (
                      <div key={d.label} className="stage-derivation">
                        <span>{d.label}</span>
                        <TeX math={d.tex} block />
                      </div>
                    ))}
                  </details>
                )}
              </>
            ) : (
              <code className="char-eq">{test.calculation?.equation}</code>
            )}
          </div>

          <div className="stage-block">
            <h4>Parameters</h4>
            {stage ? <InputTable stage={stage} test={test} /> : null}
            {stage?.unitNotes?.length > 0 && (
              <ul className="unit-notes">
                {stage.unitNotes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            )}
          </div>

          {Object.keys(test.calculation?.derived || {}).length > 0 && (
            <div className="stage-block">
              <h4>Calculated intermediate values</h4>
              <DerivedTable stage={stage} test={test} />
            </div>
          )}
        </div>

        <ResultArea stage={stage} test={test} />
      </div>

      <details className="physics-calc-details stage-assumptions">
        <summary>Assumptions &amp; tolerance rationale</summary>
        <div className="physics-calc-body">
          <ul>{test.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          <p className="char-muted" style={{ marginBottom: 0 }}>
            {test.tolerance.relative_tolerance !== null ? `Tolerance ±${(test.tolerance.relative_tolerance * 100).toFixed(0)}% relative. ` : ""}
            {test.tolerance.rationale}
          </p>
        </div>
      </details>
    </details>
  );
}
