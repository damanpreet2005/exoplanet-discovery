import { Link } from "react-router-dom";
import StateBlock from "../components/StateBlock";
import Icon from "../components/Icon";
import StageNav from "../components/StageNav";
import PhysicsStatusBadge from "../components/PhysicsStatusBadge";
import {
  CLASSIFICATION_DISCLAIMER, PROVENANCE_LABELS, ReliabilityTag, isComputed, paramText,
} from "../components/characterization/primitives";
import { sourceCounts } from "../lib/featureSources";
import { catalogDependence, planetSizeIsCircular, transitDetection } from "../lib/evidence";
import { useAnalysis, STATUS, FINAL_STATUS } from "../context/AnalysisContext";

function pct(v) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

function Section({ title, icon, to, linkLabel, children, testId }) {
  return (
    <section className="report-section" data-testid={testId}>
      <header className="report-section-head">
        <h2><Icon name={icon} size={20} /> {title}</h2>
        {to && <Link to={to} className="ws-link">{linkLabel || "View details"} <Icon name="chevron_right" size={16} /></Link>}
      </header>
      {children}
    </section>
  );
}

function ParamTable({ report, names }) {
  const rows = names.map((n) => report.parameters?.[n]).filter(Boolean);
  return (
    <div className="table-scroll">
      <table className="feature-table data-table">
        <thead><tr><th>Property</th><th>Value</th><th>Source</th><th>Reliability</th></tr></thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.name}>
              <th>{p.label}</th>
              <td className="value">{paramText(p)}</td>
              <td>{p.provenance === "catalog" && p.evidence === "measured" ? "Measured" : PROVENANCE_LABELS[p.provenance] || p.provenance}</td>
              <td>{isComputed(p) && p.reliability !== "not_assessed" ? <ReliabilityTag level={p.reliability} /> : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DiscoveryReportPage() {
  const {
    status, result, finalStatus, finalResult, manualParameters, physicsResult, physicsResultIsCurrent, characterization,
  } = useAnalysis();

  if (status !== STATUS.SUCCESS || !result || finalStatus !== FINAL_STATUS.SUCCESS || !finalResult) {
    return (
      <div className="fade-in">
        <header className="page-header"><h1 className="page-title">Final Discovery Report</h1></header>
        <div className="panel">
          <StateBlock
            icon={<Icon name="summarize" size={32} />}
            title="Available after a completed prediction"
            description="The report summarises transit detection, the ML prediction, physics validation and planet characterization for one target. Analyse a light curve first."
            action={<Link to="/" className="btn btn-primary" style={{ marginTop: 12 }}>Go to Upload</Link>}
          />
        </div>
      </div>
    );
  }

  // A characterization report is only ever shown under the target it was computed for.
  const charTarget = characterization?.candidate?.object_id;
  const report = characterization && (!charTarget || !result.object_id || charTarget === result.object_id) ? characterization : null;
  const physics = physicsResultIsCurrent ? physicsResult : null;
  const d = result.diagnostics;
  const v = result.characterisation;
  const cr = result.catalog_resolution;
  const counts = sourceCounts(result, manualParameters);
  const P = (n) => report?.parameters?.[n];
  const size = report?.classifications?.find((c) => c.name === "size_category");
  const fitted = report && (report.status === "complete" || report.status === "partial");

  // Light-curve and physics evidence only; the ML classification is listed
  // separately because it consumes catalogue inputs (koi_score above all).
  const detection = transitDetection(result, report);
  const dependence = catalogDependence(finalResult, result.features, manualParameters);
  const evidenceFor = [];
  const evidenceAgainst = [];
  if (detection.detected) {
    evidenceFor.push(`${detection.label} in the uploaded light curve: ${detection.text}`
      + (fitted ? ` A limb-darkened transit model was fitted to ${report.transit_fit?.n_transits_with_data ?? "the"} observed transits.` : ""));
  } else if (detection.detected === false) {
    evidenceAgainst.push(`${detection.label} in the uploaded light curve: ${detection.text}`);
  }
  const circularSize = planetSizeIsCircular(result, manualParameters);
  for (const t of physics?.tests || []) {
    if (t.test_id === "planet_size" && circularSize) continue;   // passes by construction: not evidence
    if (t.status === "PASS") evidenceFor.push(`${t.name}: ${t.summary}`);
    else if (t.status === "REVIEW_REQUIRED") evidenceAgainst.push(`${t.name}: ${t.summary}`);
  }
  for (const c of (report?.consistency_checks || []).filter((x) => typeof x.consistent === "boolean")) {
    (c.consistent ? evidenceFor : evidenceAgainst).push(`${c.label}: ${c.consistent ? "consistent" : "flagged for review"}${c.strength === "weak" ? " (weak test)" : ""}${c.tension_sigma !== null && c.tension_sigma !== undefined ? ` (${c.tension_sigma}σ)` : ""}.`);
  }

  const limitations = [
    "This is a transit candidate. Neither the classifier score nor the physics checks confirm it as a planet; confirmation requires independent follow-up (e.g. radial velocities or statistical validation).",
    "The classifier's class labels are not documented in the stored model artifacts; class 1 is reported as the model's positive output only, and its probability is not calibrated.",
    ...(dependence?.fromCatalog ? [`The ML probability is dominated by koi_score, NASA's Robovetter disposition score for this KOI (${Math.round(dependence.rf_importance * 100)}% of the Random Forest's feature importance). For an Object ID with a high koi_score the model returns a high probability even for light curves without a planetary transit, so it cannot independently confirm what the light curve shows.`] : []),
    ...(report?.warnings || []),
    ...(report?.missing_inputs || []).map((m) => `${m.label} unavailable — ${m.reason}`),
  ];
  const lowConfidence = Object.values(report?.parameters || {})
    .filter((p) => isComputed(p) && (p.reliability === "low_confidence" || p.reliability === "unreliable"));
  if (lowConfidence.length) {
    limitations.splice(2, 0, `Low-confidence or unreliable values (reasons in Planet Characterization): ${lowConfidence.map((p) => p.label).join(", ")}.`);
  }
  if (!physics) limitations.push("Physics validation has not been run for the submitted parameters, so its checks are not part of this report.");
  if (counts.manual) limitations.push(`${counts.manual} of the 17 model parameters ${counts.manual === 1 ? "was" : "were"} entered manually rather than resolved automatically.`);

  return (
    <div className="fade-in report-page" data-testid="discovery-report">
      <header className="analysis-header">
        <div>
          <h1 className="page-title">Final Discovery Report</h1>
          <div className="analysis-meta">
            <span className="meta-chip"><Icon name="target" size={15} /> {result.object_id || "No object ID"}</span>
            {cr?.matched_kepler_name && <span className="meta-chip">{cr.matched_kepler_name}</span>}
            <span className="meta-chip"><Icon name="description" size={15} /> {result.filename}</span>
          </div>
        </div>
        <div className="analysis-actions no-print">
          <button type="button" className="btn btn-ghost" onClick={() => window.print()}>
            <Icon name="print" size={16} /> Print / save PDF
          </button>
        </div>
      </header>

      <div className="report-verdict" role="note">
        <Icon name="info" size={20} />
        <p>
          <strong>Candidate summary, not a confirmation.</strong> This report consolidates what each analysis stage
          computed for {result.object_id || "this target"} and why. Unavailable results are stated as such.
        </p>
      </div>

      <div className="report-grid">
        <Section title="Discovery overview" icon="travel_explore" testId="report-overview">
          <dl className="report-kpis">
            <div><dt>Transit detection (light curve)</dt><dd>{detection.label}{detection.snr !== null && ` · SNR ${detection.snr.toFixed(1)}`}</dd></div>
            <div><dt>ML prediction{dependence?.fromCatalog ? " (catalogue-informed)" : ""}</dt><dd>Class {finalResult.prediction} · {pct(finalResult.weighted_probability)}</dd></div>
            <div><dt>Physics validation</dt><dd>{physics ? <PhysicsStatusBadge status={physics.overall_status} /> : "Not run"}</dd></div>
            <div><dt>Size category</dt><dd>{size?.status === "computed" ? size.category : "Unavailable"}</dd></div>
            <div><dt>Planet radius</dt><dd>{paramText(P("planet_radius"))}</dd></div>
            <div><dt>Orbital period</dt><dd>{report ? paramText(P("orbital_period")) : `${d.bls_period_days.toFixed(4)} d (BLS)`}</dd></div>
          </dl>
        </Section>

        <Section title="Transit detection" icon="show_chart" to="/results" testId="report-detection">
          <dl className="metric-grid">
            <div><dt>BLS period</dt><dd>{d.bls_period_days.toFixed(4)} d</dd></div>
            <div><dt>BLS depth</dt><dd>{d.bls_depth_ppm.toFixed(1)} ppm</dd></div>
            <div><dt>BLS duration</dt><dd>{d.bls_duration_hours.toFixed(2)} h</dd></div>
            <div><dt>Transits observed</dt><dd>{d.num_transits_observed}</dd></div>
            <div><dt>Odd/even depth ratio</dt><dd>{v.odd_even_depth_ratio.toFixed(3)}</dd></div>
            <div><dt>Secondary eclipse</dt><dd>{v.secondary_eclipse_depth_ppm.toFixed(1)} ppm</dd></div>
          </dl>
        </Section>

        <Section title="ML prediction" icon="neurology" to="/results" testId="report-prediction">
          <dl className="metric-grid">
            <div><dt>Predicted class</dt><dd>{finalResult.prediction}</dd></div>
            <div><dt>Weighted probability</dt><dd>{pct(finalResult.weighted_probability)}</dd></div>
            <div><dt>Random Forest</dt><dd>{pct(finalResult.random_forest_probability)} (w={finalResult.weights.random_forest})</dd></div>
            <div><dt>2D CNN</dt><dd>{pct(finalResult.cnn_probability)} (w={finalResult.weights.cnn})</dd></div>
            <div><dt>Model version</dt><dd>{finalResult.model_version}</dd></div>
          </dl>
          <p className="char-muted">Class 1 is assigned when the weighted probability is at least 0.5.</p>
        </Section>

        <Section title="Physics validation" icon="science" to="/physics-validation" linkLabel={physics ? "View details" : "Run validation"} testId="report-physics">
          {physics ? (
            <>
              <p className="char-muted" style={{ marginTop: 0 }}>{physics.summary.message}</p>
              <ul className="report-checks">
                {physics.tests.map((t) => (
                  <li key={t.test_id}>
                    <PhysicsStatusBadge status={t.status} /> <span>{t.name}</span>
                    {t.test_id === "planet_size" && circularSize && <span className="char-muted"> (not independent: Rp derived from the depth)</span>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="char-muted" style={{ margin: 0 }}>Not run for the submitted parameters of this candidate.</p>
          )}
        </Section>

        <Section title="Planet characterization" icon="radar" to="/characterisation" testId="report-characterization">
          {report ? (
            <>
              <p className="char-muted" style={{ marginTop: 0 }}>{report.status_message} <ReliabilityTag level={report.reliability} /></p>
              <ParamTable report={report} names={["planet_radius", "radius_ratio", "planet_mass", "planet_density", "equilibrium_temperature", "insolation"]} />
            </>
          ) : (
            <p className="char-muted" style={{ margin: 0 }}>No characterization report is attached to this session.</p>
          )}
        </Section>

        <Section title="Planet classification" icon="category" to="/characterisation?view=planet" testId="report-classification">
          {report?.classifications?.length ? (
            <>
              <ul className="report-classes">
                {report.classifications.map((c) => (
                  <li key={c.name}>
                    <span className="report-class-label">{c.label}</span>
                    <strong>{c.status === "computed" ? c.category : "Unavailable"}</strong>
                    {c.status === "computed" && c.probability !== null && c.probability !== undefined && (
                      <span className="char-alt">{Math.round(c.probability * 100)}% of Monte Carlo samples · based on {c.depends_on?.join(", ")}</span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="char-muted">{CLASSIFICATION_DISCLAIMER}</p>
            </>
          ) : (
            <p className="char-muted" style={{ margin: 0 }}>No classification is available: it needs a computed planet radius.</p>
          )}
        </Section>

        <Section title="Stellar & orbital properties" icon="wb_sunny" to="/characterisation?view=star" testId="report-properties">
          {report ? (
            <ParamTable report={report} names={["stellar_radius", "stellar_mass", "stellar_teff", "stellar_logg", "orbital_period", "semi_major_axis", "inclination", "eccentricity"]} />
          ) : (
            <p className="char-muted" style={{ margin: 0 }}>Unavailable without a characterization report.</p>
          )}
        </Section>

        <Section title="Scientific evidence" icon="balance" testId="report-evidence">
          <div className="evidence-cols">
            <div>
              <h3 className="evidence-head ok"><Icon name="add_circle" size={16} /> Supports a planetary transit</h3>
              {evidenceFor.length ? <ul className="insight-notes">{evidenceFor.map((e, i) => <li key={i}>{e}</li>)}</ul> : <p className="char-muted">None recorded.</p>}
            </div>
            <div>
              <h3 className="evidence-head warn"><Icon name="do_not_disturb_on" size={16} /> Against or needing review</h3>
              {evidenceAgainst.length ? <ul className="insight-notes">{evidenceAgainst.map((e, i) => <li key={i}>{e}</li>)}</ul> : <p className="char-muted">None recorded.</p>}
            </div>
          </div>
          <p className="char-muted report-ml-note" data-testid="report-ml-evidence">
            <strong>ML classification (listed separately):</strong> class {finalResult.prediction}, weighted probability{" "}
            {pct(finalResult.weighted_probability)}.{" "}
            {dependence?.fromCatalog
              ? `It is catalogue-informed: it uses NASA's own vetting score koi_score = ${dependence.value} from the KOI catalogue; with that input set to its training median the model gives ${pct(dependence.weighted_probability_with_neutral_value)}. It is therefore not independent evidence from the uploaded light curve.`
              : "Its inputs were not taken from NASA's vetting score for this object."}
          </p>
        </Section>

        <Section title="Uncertainties & limitations" icon="report" testId="report-limitations">
          <ul className="insight-notes">{limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </Section>
      </div>

      <p className="char-muted report-footnote">
        Characterization engine {report?.engine_version || "—"} · model {finalResult.model_version}
        {physics ? ` · physics validation ${new Date(physics.generated_at).toLocaleString()}` : ""}
      </p>

      <StageNav current="/report" />
    </div>
  );
}
