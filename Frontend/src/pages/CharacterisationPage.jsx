import { Link, useSearchParams } from "react-router-dom";
import StateBlock from "../components/StateBlock";
import Icon from "../components/Icon";
import StageNav from "../components/StageNav";
import PhysicsStatusBadge from "../components/PhysicsStatusBadge";
import CharacterizationOverridePanel from "../components/CharacterizationOverridePanel";
import TransitLightCurveChart from "../components/charts/TransitLightCurveChart";
import TimingChart from "../components/charts/TimingChart";
import RadiusScale from "../components/charts/RadiusScale";
import OrbitSchematic from "../components/charts/OrbitSchematic";
import TensionChart from "../components/charts/TensionChart";
import PlanetPreview from "../components/charts/PlanetPreview";
import {
  CLASSIFICATION_DISCLAIMER, ClassificationCard, PROVENANCE_LABELS, ParamDetailsTable, ParamList,
  ProvenanceChip, ReliabilityTag, StatusChip, isComputed, paramText,
} from "../components/characterization/primitives";
import { useAnalysis, STATUS, CHARACTERIZATION_STATUS } from "../context/AnalysisContext";

const VIEWS = [
  { id: "overview", label: "Overview", icon: "dashboard" },
  { id: "planet", label: "Planetary Properties", icon: "public" },
  { id: "orbit", label: "Orbital Analysis", icon: "orbit" },
  { id: "star", label: "Host Star", icon: "wb_sunny" },
  { id: "transit", label: "Transit Analysis", icon: "show_chart" },
  { id: "consistency", label: "Physical Consistency", icon: "fact_check" },
  { id: "sources", label: "Data Sources", icon: "database" },
];
const TOOL_VIEWS = [{ id: "override", label: "Expert Override", icon: "tune" }];

function sectionParams(report, id, { details = false } = {}) {
  const section = (report.sections || []).find((s) => s.id === id);
  if (!section) return [];
  const names = details ? [...section.parameters, ...section.details] : section.parameters;
  return names.map((n) => report.parameters?.[n]).filter(Boolean);
}

function pick(report, names) {
  return names.map((n) => report.parameters?.[n]).filter(Boolean);
}

function Panel({ title, icon, action, className = "", children, testId }) {
  return (
    <section className={`ws-panel ${className}`} data-testid={testId}>
      <header className="ws-panel-head">
        <h3>{icon && <Icon name={icon} size={18} />} {title}</h3>
        {action}
      </header>
      {children}
    </section>
  );
}

function OpenView({ view, onOpen, label = "Details" }) {
  return (
    <button type="button" className="ws-link" onClick={() => onOpen(view)}>
      {label} <Icon name="chevron_right" size={16} />
    </button>
  );
}

function DetailsBlock({ params, summary = "Methods, uncertainties and provenance" }) {
  return (
    <details className="physics-calc-details ws-details">
      <summary>{summary}</summary>
      <div className="physics-calc-body">
        <ParamDetailsTable params={params} />
      </div>
    </details>
  );
}

function SummaryStrip({ report }) {
  const radius = report.parameters?.planet_radius;
  const period = report.parameters?.orbital_period;
  const size = (report.classifications || []).find((c) => c.name === "size_category");
  const items = [
    { label: "Target", value: report.candidate?.object_id || "—", sub: report.candidate?.kepler_name || null },
    { label: "Planet radius", value: paramText(radius), sub: radius ? PROVENANCE_LABELS[radius.provenance] : null },
    { label: "Orbital period", value: paramText(period), sub: period ? PROVENANCE_LABELS[period.provenance] : null },
    { label: "Size category", value: size?.status === "computed" ? size.category : "Unavailable", sub: size?.status === "computed" ? "Radius-based" : null },
  ];
  return (
    <div className="kpi-strip" data-testid="char-summary">
      {items.map((it) => (
        <div className="kpi" key={it.label}>
          <span className="kpi-label">{it.label}</span>
          <span className={`kpi-value${it.value === "Unavailable" ? " is-unavailable" : ""}`}>{it.value}</span>
          {it.sub && <span className="kpi-sub">{it.sub}</span>}
        </div>
      ))}
      <div className="kpi">
        <span className="kpi-label">Characterization</span>
        <span className="kpi-value kpi-badges"><StatusChip status={report.status} /><ReliabilityTag level={report.reliability} /></span>
        <span className="kpi-sub">{report.status_message}</span>
      </div>
    </div>
  );
}

function PhysicsLink({ physicsResult, physicsResultIsCurrent }) {
  return (
    <div className="ws-callout">
      <Icon name="science" size={18} />
      <div>
        <strong>Physics Validation</strong>
        {physicsResultIsCurrent && physicsResult ? (
          <p>
            <PhysicsStatusBadge status={physicsResult.overall_status} /> {physicsResult.summary.message}
          </p>
        ) : (
          <p>Not yet run for the submitted parameters of this candidate.</p>
        )}
      </div>
      <Link to="/physics-validation" className="ws-link">Open <Icon name="chevron_right" size={16} /></Link>
    </div>
  );
}

function ConsistencyList({ checks }) {
  if (!checks?.length) return <p className="char-muted">No consistency checks could be computed for this candidate.</p>;
  return (
    <ul className="check-list">
      {checks.map((c) => {
        // consistent === null: the check could not be evaluated (never shown as a pass or a flag).
        const state = c.consistent === null || c.consistent === undefined ? "na" : c.consistent ? "ok" : "warn";
        return (
        <li key={c.check} className={state}>
          <Icon name={{ ok: "check_circle", warn: "warning", na: "do_not_disturb_on" }[state]} size={18} filled />
          <div>
            <div className="check-title">
              {c.label}
              <span className="check-verdict">{{ ok: "Consistent", warn: "Flagged for review", na: "Not evaluated" }[state]}{c.strength === "weak" && state !== "na" ? " (weak test)" : ""}
                {c.tension_sigma !== undefined && c.tension_sigma !== null && ` · ${c.tension_sigma}σ`}
              </span>
            </div>
            {c.ratio !== undefined && (
              <div className="char-alt">
                Ratio {c.ratio}{c.ratio_interval ? ` (68%: ${c.ratio_interval[0]}–${c.ratio_interval[1]})` : ""}
              </div>
            )}
            <p className="check-note">{c.note}</p>
          </div>
        </li>
        );
      })}
    </ul>
  );
}

function FitDiagnostics({ fit }) {
  const f = (x, d = 3) => (x === null || x === undefined ? "—" : Number(x).toPrecision(d));
  return (
    <>
      <dl className="metric-grid">
        <div><dt>Fit status</dt><dd>{fit.status}{fit.converged === false ? " (not converged)" : ""}</dd></div>
        <div><dt>Ephemeris seed</dt><dd>{fit.seed_source === "catalog_ephemeris" ? "KOI catalogue" : "Transit search (BLS)"}</dd></div>
        <div><dt>Transits with data</dt><dd>{fit.n_transits_with_data ?? "—"}</dd></div>
        <div><dt>Points fitted</dt><dd>{fit.n_points ?? "—"}</dd></div>
        <div><dt>Reduced χ²</dt><dd>{f(fit.reduced_chi2)}</dd></div>
        <div><dt>Red-noise factor β</dt><dd>{f(fit.beta_red_noise)}</dd></div>
        <div><dt>Noise per point</dt><dd>{fit.noise_per_point_ppm ? `${f(fit.noise_per_point_ppm)} ppm` : "—"}</dd></div>
        <div><dt>Limb darkening</dt><dd>{fit.limb_darkening ? `u₁ ${fit.limb_darkening.u1}, u₂ ${fit.limb_darkening.u2} (assumed)` : "—"}</dd></div>
      </dl>
      <p className="char-muted">{fit.method}</p>
      {fit.bls_note && <p className="char-muted">{fit.bls_note}</p>}
    </>
  );
}

function ProvenanceBreakdown({ report }) {
  const counts = {};
  for (const p of Object.values(report.parameters || {})) counts[p.provenance] = (counts[p.provenance] || 0) + 1;
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const order = Object.keys(report.provenance_categories || PROVENANCE_LABELS);
  return (
    <ul className="prov-list">
      {order.filter((k) => counts[k]).map((k) => (
        <li key={k}>
          <div className="prov-list-head">
            <ProvenanceChip provenance={k} />
            <span className="prov-count">{counts[k]} of {total}</span>
          </div>
          <span className="prov-bar"><span className={`prov-${k}`} style={{ width: `${(counts[k] / total) * 100}%` }} /></span>
          <p className="char-muted">{report.provenance_categories?.[k]}</p>
        </li>
      ))}
    </ul>
  );
}

function Insights({ report, physicsResult, physicsResultIsCurrent }) {
  const flagged = Object.values(report.parameters || {}).filter(
    (p) => isComputed(p) && (p.reliability === "low_confidence" || p.reliability === "unreliable")
  );
  const unavailable = Object.values(report.parameters || {}).filter((p) => !isComputed(p));
  const computedClasses = (report.classifications || []).filter((c) => c.status === "computed");
  return (
    <aside className="ws-insights" aria-label="Insights" data-testid="char-insights">
      <div className="insight-block insight-planet">
        <PlanetPreview report={report} />
      </div>
      <div className="insight-block">
        <h4>Key findings</h4>
        {computedClasses.length ? (
          <ul className="insight-list">
            {computedClasses.map((c) => (
              <li key={c.name}>
                <span className="insight-label">{c.label}</span>
                <span>{c.category}</span>
              </li>
            ))}
          </ul>
        ) : <p className="char-muted">No classification could be computed.</p>}
        <p className="insight-disclaimer">{CLASSIFICATION_DISCLAIMER}</p>
      </div>

      {report.warnings?.length > 0 && (
        <div className="insight-block warn" data-testid="char-warnings">
          <h4><Icon name="warning" size={16} /> Warnings</h4>
          <ul className="insight-notes">{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      <div className="insight-block">
        <h4>Uncertainty flags</h4>
        {flagged.length ? (
          <p className="insight-flags">
            <strong>{flagged.length} value{flagged.length > 1 ? "s" : ""}</strong> rated low confidence or unreliable:{" "}
            {flagged.map((p) => p.label).join(", ")}.
          </p>
        ) : <p className="char-muted">All computed parameters are rated reliable.</p>}
      </div>

      <div className="insight-block">
        <h4>Missing parameters</h4>
        {unavailable.length || report.missing_inputs?.length ? (
          <ul className="insight-notes">
            {unavailable.map((p) => <li key={p.name}><strong>{p.label}</strong> unavailable</li>)}
          </ul>
        ) : <p className="char-muted">No parameters are missing.</p>}
        {unavailable.length > 0 && <p className="char-muted">Reasons are listed under Data Sources.</p>}
      </div>

      <div className="insight-block">
        <h4>Physics validation</h4>
        {physicsResultIsCurrent && physicsResult
          ? <PhysicsStatusBadge status={physicsResult.overall_status} />
          : <p className="char-muted">Not run for this candidate yet.</p>}
      </div>
    </aside>
  );
}

function OverviewView({ report, open, physicsResult, physicsResultIsCurrent }) {
  const size = (report.classifications || []).find((c) => c.name === "size_category");
  return (
    <div className="ws-grid">
      <Panel title="Transit Analysis" icon="show_chart" className="span-2" action={<OpenView view="transit" onOpen={open} />}>
        <div className="ws-split">
          <TransitLightCurveChart folded={report.transit_fit?.folded} compact />
          <ParamList lookup={report.parameters} params={pick(report, ["transit_depth", "transit_duration", "impact_parameter", "transit_snr"])} />
        </div>
      </Panel>
      <Panel title="Planetary Properties" icon="public" action={<OpenView view="planet" onOpen={open} />}>
        <ParamList lookup={report.parameters} params={pick(report, ["planet_radius", "planet_mass", "planet_density"])} />
        {size && <div className="ws-inline-class"><span>Size category</span><strong>{size.category || "Unavailable"}</strong></div>}
      </Panel>
      <Panel title="Orbital Analysis" icon="orbit" action={<OpenView view="orbit" onOpen={open} />}>
        <ParamList lookup={report.parameters} params={pick(report, ["semi_major_axis", "inclination", "equilibrium_temperature", "insolation"])} />
      </Panel>
      <Panel title="Host Star" icon="wb_sunny" action={<OpenView view="star" onOpen={open} />}>
        <ParamList lookup={report.parameters} params={pick(report, ["stellar_radius", "stellar_mass", "stellar_teff", "stellar_logg"])} />
      </Panel>
      <Panel title="Physical Consistency" icon="fact_check" action={<OpenView view="consistency" onOpen={open} />}>
        <ConsistencyList checks={report.consistency_checks} />
        <PhysicsLink physicsResult={physicsResult} physicsResultIsCurrent={physicsResultIsCurrent} />
      </Panel>
    </div>
  );
}

function PlanetView({ report }) {
  const params = sectionParams(report, "planet", { details: true });
  return (
    <div className="ws-grid">
      <Panel title="Planetary Properties" icon="public" testId="char-section-planet">
        <ParamList lookup={report.parameters} params={params} />
      </Panel>
      <Panel title="Size comparison" icon="straighten">
        <RadiusScale radius={report.parameters?.planet_radius} />
      </Panel>
      <Panel title="Classification" icon="category" className="span-2" testId="char-classifications">
        <p className="char-muted">
          Each category comes from the engine's documented rules; percentages are the share of Monte Carlo samples
          (propagated uncertainties) that fall in each category. {CLASSIFICATION_DISCLAIMER}
        </p>
        <div className="class-grid">
          {(report.classifications || []).map((c) => <ClassificationCard key={c.name} c={c} />)}
        </div>
      </Panel>
      <div className="span-2"><DetailsBlock params={params} /></div>
    </div>
  );
}

function OrbitView({ report }) {
  const orbit = sectionParams(report, "orbit", { details: true });
  const thermal = sectionParams(report, "thermal", { details: true });
  return (
    <div className="ws-grid">
      <Panel title="Orbit" icon="orbit" testId="char-section-orbit">
        <ParamList lookup={report.parameters} params={orbit} />
      </Panel>
      <Panel title="Orbit schematic" icon="radio_button_unchecked">
        <OrbitSchematic parameters={report.parameters} />
      </Panel>
      <Panel title="Irradiation & thermal environment" icon="thermostat" className="span-2" testId="char-section-thermal">
        <ParamList lookup={report.parameters} params={thermal} />
      </Panel>
      <div className="span-2"><DetailsBlock params={[...orbit, ...thermal]} /></div>
    </div>
  );
}

function StarView({ report }) {
  const section = (report.sections || []).find((s) => s.id === "host_star");
  const primary = pick(report, section?.parameters || []);
  const extra = pick(report, section?.details || []);
  const c = report.candidate || {};
  return (
    <div className="ws-grid">
      <Panel title="Stellar properties" icon="wb_sunny" testId="char-section-host_star">
        <ParamList lookup={report.parameters} params={primary} />
      </Panel>
      <Panel title="Identification & position" icon="travel_explore">
        <dl className="metric-grid">
          <div><dt>Object ID</dt><dd>{c.object_id || "—"}</dd></div>
          <div><dt>Catalogue match</dt><dd>{c.match_status ? c.match_status.replace(/_/g, " ") : "—"}</dd></div>
          {c.kepid && <div><dt>Kepler Input Catalog</dt><dd>KIC {c.kepid}</dd></div>}
          {c.kepoi_name && <div><dt>KOI</dt><dd>{c.kepoi_name}</dd></div>}
          {c.kepler_name && <div><dt>Kepler name</dt><dd>{c.kepler_name}</dd></div>}
        </dl>
        <ParamList lookup={report.parameters} params={extra} />
      </Panel>
      <div className="span-2"><DetailsBlock params={[...primary, ...extra]} /></div>
    </div>
  );
}

function TransitView({ report }) {
  const params = sectionParams(report, "transit_signal", { details: true });
  return (
    <div className="ws-grid">
      <Panel title="Transit light curve" icon="show_chart" className="span-2">
        <TransitLightCurveChart folded={report.transit_fit?.folded} />
      </Panel>
      <Panel title="Transit parameters" icon="straighten" testId="char-section-transit_signal">
        <ParamList lookup={report.parameters} params={params} />
      </Panel>
      <Panel title="Transit-model fit" icon="model_training">
        {report.transit_fit ? <FitDiagnostics fit={report.transit_fit} /> : <p className="char-muted">No transit fit.</p>}
      </Panel>
      <Panel title="Transit timing" icon="schedule" className="span-2">
        <TimingChart timing={report.transit_timing} />
      </Panel>
      <div className="span-2"><DetailsBlock params={params} /></div>
    </div>
  );
}

function ConsistencyView({ report, physicsResult, physicsResultIsCurrent }) {
  return (
    <div className="ws-grid">
      <Panel title="Internal consistency checks" icon="fact_check">
        <ConsistencyList checks={report.consistency_checks} />
      </Panel>
      <Panel title="Independent validation" icon="science">
        <PhysicsLink physicsResult={physicsResult} physicsResultIsCurrent={physicsResultIsCurrent} />
        <p className="char-muted">
          Physics Validation checks the submitted model parameters against transit and orbital relations; the
          checks on the left compare this characterization's own fitted values against each other and the catalogue.
        </p>
      </Panel>
      <Panel title="Comparison with the KOI catalogue" icon="compare_arrows" className="span-2">
        <TensionChart rows={report.catalog_comparison} />
        {report.catalog_comparison?.some((c) => c.note) && (
          <ul className="insight-notes">
            {report.catalog_comparison.filter((c) => c.note).map((c) => <li key={c.parameter}><strong>{c.label}:</strong> {c.note}</li>)}
          </ul>
        )}
      </Panel>
      {report.warnings?.length > 0 && (
        <Panel title="Validation warnings" icon="warning" className="span-2">
          <ul className="insight-notes">{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </Panel>
      )}
    </div>
  );
}

function SourcesView({ report }) {
  const cfg = report.config || {};
  return (
    <div className="ws-grid">
      <Panel title="Provenance of reported values" icon="account_tree">
        <ProvenanceBreakdown report={report} />
      </Panel>
      <Panel title="Missing inputs" icon="help">
        {report.missing_inputs?.length ? (
          <ul className="insight-notes">
            {report.missing_inputs.map((m) => (
              <li key={m.parameter}>
                <strong>{m.label}</strong> — {m.reason}
                {m.required_for?.length > 0 && <> Needed for: {m.required_for.join(", ")}.</>}
                {m.overridable && " Can be supplied through Expert Override."}
              </li>
            ))}
          </ul>
        ) : <p className="char-muted">No inputs are missing.</p>}
      </Panel>
      <Panel title={`Model assumptions (${report.assumptions?.length || 0})`} icon="rule" className="span-2">
        <ul className="insight-notes">{report.assumptions?.map((a) => <li key={a.id}>{a.text}</li>)}</ul>
      </Panel>
      <Panel title="Engine configuration" icon="settings" className="span-2">
        <dl className="metric-grid">
          <div><dt>Bond albedo (assumed)</dt><dd>{cfg.bond_albedo ?? "—"}</dd></div>
          <div><dt>Heat redistribution</dt><dd>{cfg.heat_redistribution ?? "—"}</dd></div>
          <div><dt>Monte Carlo samples</dt><dd>{cfg.mc_samples ?? "—"}</dd></div>
          <div><dt>Detection SNR threshold</dt><dd>{cfg.snr_detection_threshold ?? "—"}</dd></div>
          <div><dt>Engine version</dt><dd>{report.engine_version || "—"}</dd></div>
          <div><dt>Generated</dt><dd>{report.generated_at ? new Date(report.generated_at).toLocaleString() : "—"}</dd></div>
        </dl>
      </Panel>
    </div>
  );
}

export default function CharacterisationPage() {
  const {
    status, result, characterization, characterizationStatus, characterizationError,
    characterizationOverrides, characterizationConfig, characterizationModelEdits,
    runCharacterization, restoreCharacterization, physicsResult, physicsResultIsCurrent,
  } = useAnalysis();
  const [searchParams, setSearchParams] = useSearchParams();
  const allViews = [...VIEWS, ...TOOL_VIEWS];
  const view = allViews.some((v) => v.id === searchParams.get("view")) ? searchParams.get("view") : "overview";
  const open = (id) => setSearchParams(id === "overview" ? {} : { view: id });

  if (status !== STATUS.SUCCESS || !result) {
    return (
      <div className="fade-in">
        <header className="page-header">
          <h1 className="page-title">Planet Characterization</h1>
        </header>
        <div className="panel">
          <StateBlock
            icon={<Icon name="radar" size={32} />}
            title="Available after analysis"
            description="Upload a light curve to characterize its transit signal here."
            action={<Link to="/" className="btn btn-primary" style={{ marginTop: 12 }}>Go to Upload</Link>}
          />
        </div>
      </div>
    );
  }

  const report = characterization;
  const candidate = report?.candidate || {};
  const hostStar = candidate.kepid ? `KIC ${candidate.kepid}` : null;
  const viewLabel = allViews.find((v) => v.id === view)?.label;
  const canOverride = report?.parameters && Object.keys(report.parameters).length > 0 && result.characterization?.inputs;

  return (
    <div className="fade-in">
      <header className="analysis-header">
        <div>
          <h1 className="page-title">Planet Characterization</h1>
          <div className="analysis-meta">
            <span className="meta-chip"><Icon name="target" size={15} /> {result.object_id || "No object ID"}</span>
            {candidate.kepler_name && <span className="meta-chip">{candidate.kepler_name}</span>}
            {hostStar && <span className="meta-chip"><Icon name="wb_sunny" size={15} /> Host {hostStar}</span>}
            {report && <StatusChip status={report.status} />}
            {characterizationStatus === CHARACTERIZATION_STATUS.RUNNING && (
              <span className="meta-chip"><Icon name="progress_activity" size={15} className="icon-spin" /> Recomputing…</span>
            )}
          </div>
        </div>
        <div className="analysis-actions">
          <Link to="/report" className="btn btn-ghost"><Icon name="summarize" size={16} /> Discovery Report</Link>
        </div>
      </header>

      {!report ? (
        <div className="panel">
          <StateBlock
            icon={<Icon name="info" size={32} />}
            title="No characterization report for this session"
            description="This session was analyzed before the characterization engine existed. Upload the light curve again to characterize it."
          />
        </div>
      ) : (
        <div className="char-workspace" data-testid="characterization-dashboard">
          <nav className="ws-sidebar" aria-label="Characterization sections">
            <ul>
              {VIEWS.map((v) => (
                <li key={v.id}>
                  <button type="button" className={view === v.id ? "active" : ""} aria-current={view === v.id ? "page" : undefined} onClick={() => open(v.id)}>
                    <Icon name={v.icon} size={18} /> <span>{v.label}</span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="ws-sidebar-divider" aria-hidden="true" />
            <ul>
              {TOOL_VIEWS.map((v) => (
                <li key={v.id}>
                  <button type="button" className={view === v.id ? "active" : ""} aria-current={view === v.id ? "page" : undefined} onClick={() => open(v.id)}>
                    <Icon name={v.icon} size={18} /> <span>{v.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <div className="ws-main">
            <SummaryStrip report={report} />
            {view !== "overview" && <h2 className="ws-view-title">{viewLabel}</h2>}
            {view === "overview" && <OverviewView report={report} open={open} physicsResult={physicsResult} physicsResultIsCurrent={physicsResultIsCurrent} />}
            {view === "planet" && <PlanetView report={report} />}
            {view === "orbit" && <OrbitView report={report} />}
            {view === "star" && <StarView report={report} />}
            {view === "transit" && <TransitView report={report} />}
            {view === "consistency" && <ConsistencyView report={report} physicsResult={physicsResult} physicsResultIsCurrent={physicsResultIsCurrent} />}
            {view === "sources" && <SourcesView report={report} />}
            {view === "override" && (
              canOverride ? (
                <CharacterizationOverridePanel
                  report={report}
                  overrides={characterizationOverrides}
                  config={characterizationConfig}
                  modelEdits={characterizationModelEdits}
                  status={characterizationStatus}
                  error={characterizationError}
                  onRecompute={(args) => runCharacterization(args)}
                  onRestore={restoreCharacterization}
                />
              ) : (
                <div className="ws-panel"><p className="char-muted">Expert override needs the report's stored inputs snapshot, which this session does not have.</p></div>
              )
            )}
          </div>

          <Insights report={report} physicsResult={physicsResult} physicsResultIsCurrent={physicsResultIsCurrent} />
        </div>
      )}

      <StageNav current="/characterisation" />
    </div>
  );
}
