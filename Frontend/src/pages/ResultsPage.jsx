import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PhysicsStatusBadge from "../components/PhysicsStatusBadge";
import StageNav from "../components/StageNav";
import Icon from "../components/Icon";
import TransitLightCurveChart from "../components/charts/TransitLightCurveChart";
import { groupFeatures } from "../components/ManualParamForm";
import { ReliabilityTag, StatusChip, paramText } from "../components/characterization/primitives";
import { fetchFeatureSchema } from "../api/client";
import { SOURCE_META, featureSource, formatNumber, sourceCounts } from "../lib/featureSources";
import { DETECTION_SNR, catalogDependence, transitDetection } from "../lib/evidence";
import { useAnalysis, STATUS, FINAL_STATUS, PHYSICS_STATUS, CHARACTERIZATION_STATUS } from "../context/AnalysisContext";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

const MATCH_TEXT = {
  matched_koi: "Matched a KOI catalogue entry",
  matched_star: "Matched a catalogue star",
  not_found: "Not found in the catalogue",
  unsupported_identifier_type: "Unsupported identifier type",
  lookup_error: "Catalogue lookup failed",
  not_provided: "No Object ID provided",
};

const FINDING_ICON = { positive: "check_circle", negative: "cancel", warning: "warning", unavailable: "do_not_disturb_on", info: "info" };

function SourceTag({ source }) {
  const meta = SOURCE_META[source] || { label: source, className: "" };
  return <span className={`src-tag ${meta.className}`}>{meta.label}</span>;
}

function ProbabilityBar({ label, value, weight }) {
  const pctValue = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <div className="prob-row">
      <div className="prob-head">
        <span>{label}{weight !== undefined && <span className="prob-weight"> · weight {weight}</span>}</span>
        <strong>{pct(value)}</strong>
      </div>
      <div className="prob-track" role="img" aria-label={`${label}: ${pct(value)} probability of class 1`}>
        {value !== null && value !== undefined && <span className="prob-fill" style={{ width: `${pctValue}%` }} />}
        <span className="prob-threshold" style={{ left: "50%" }} title="Decision threshold 0.5" />
      </div>
    </div>
  );
}

function buildFindings({ result, finalResult, characterization, counts, physicsResult, physicsResultIsCurrent, dependence }) {
  const out = [];
  // 1. Light-curve evidence only.
  const det = transitDetection(result, characterization);
  out.push({ kind: det.detected === null ? "unavailable" : det.detected ? "positive" : "negative", title: det.label, text: det.text });
  // 2. ML classification -- catalogue-informed when koi_score came from the catalogue.
  const mlText = `Weighted probability ${pct(finalResult.weighted_probability)} ${finalResult.prediction === 1 ? "≥" : "<"} 0.5. A classifier score, not a confirmation.`;
  const catalogNote = dependence?.fromCatalog
    ? ` Catalogue-informed: it uses NASA's vetting score koi_score = ${dependence.value}; with that set to its training median the model gives ${pct(dependence.weighted_probability_with_neutral_value)}.`
    : "";
  out.push({ kind: dependence?.fromCatalog ? "info" : finalResult.prediction === 1 ? "positive" : "negative",
    title: `ML ensemble predicts class ${finalResult.prediction}${dependence?.fromCatalog ? " (catalogue-informed)" : ""}`,
    text: mlText + catalogNote });
  const match = result.catalog_resolution?.match_status;
  if (match) {
    const ok = match === "matched_koi" || match === "matched_star";
    out.push({ kind: ok ? "positive" : "warning", title: MATCH_TEXT[match] || match, text: ok ? null : "Stellar parameters could not be taken from the catalogue." });
  }
  if (counts.manual) {
    out.push({ kind: "info", title: `${counts.manual} parameter${counts.manual > 1 ? "s" : ""} entered manually`, text: "Values that were unavailable automatically, or were overridden, in the parameter form." });
  }
  if (physicsResultIsCurrent && physicsResult) {
    const status = physicsResult.overall_status;
    out.push({ kind: status === "PASS" ? "positive" : status === "NOT_EVALUATED" ? "unavailable" : "warning", title: "Physics validation", text: physicsResult.summary.message });
  } else {
    out.push({ kind: "unavailable", title: "Physics validation not run", text: "Run it below to check the parameters against transit and orbital physics." });
  }
  if (characterization?.warnings?.length) {
    out.push({ kind: "warning", title: `${characterization.warnings.length} characterization warning${characterization.warnings.length > 1 ? "s" : ""}`, text: characterization.warnings[0] });
  }
  return out;
}

export default function ResultsPage() {
  const {
    status, result, finalStatus, finalResult, manualParameters, reset,
    physicsStatus, physicsResult, physicsError, physicsResultIsCurrent, startPhysicsValidation,
    characterization, characterizationStatus,
  } = useAnalysis();
  const navigate = useNavigate();
  const [schema, setSchema] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchFeatureSchema()
      .then((body) => { if (!cancelled && Array.isArray(body?.features)) setSchema(body.features); })
      .catch(() => {}); // labels fall back to canonical names
    return () => { cancelled = true; };
  }, []);

  async function handleStartPhysicsValidation() {
    await startPhysicsValidation();
    navigate("/physics-validation");
  }

  function handleNewPrediction() {
    // Clears the light curve, manual parameters, and final result (both in
    // memory and from sessionStorage) so the next visit to Page 1 starts a
    // genuinely fresh session rather than reusing anything from this one.
    reset();
    navigate("/");
  }

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
  const counts = sourceCounts(result, manualParameters);
  const dependence = catalogDependence(finalResult, result.features, manualParameters);
  const detection = transitDetection(result, characterization);
  const findings = buildFindings({ result, finalResult, characterization, counts, physicsResult, physicsResultIsCurrent, dependence });
  const cr = result.catalog_resolution;
  const sizeClass = characterization?.classifications?.find((c) => c.name === "size_category");

  // Model inputs table: schema order/labels when available, else the submitted keys.
  const features = schema
    ? schema.filter((f) => manualParameters && f.canonical in manualParameters)
    : Object.keys(manualParameters || {}).map((canonical) => ({ canonical, display: canonical, unit: result.features?.[canonical]?.unit || "" }));
  const groups = groupFeatures(features);

  return (
    <div className="fade-in">
      <header className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">Transit Detection &amp; ML Prediction</h1>
          <p className="page-subtitle">
            Combined result from your light curve (<strong>{result.filename}</strong>) and the 17
            submitted model parameters.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={handleNewPrediction}>
          <Icon name="refresh" size={16} /> New Prediction
        </button>
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

      <div className="results-grid">
        {/* ---- Left: target summary ---- */}
        <div className="results-col results-left">
          <section className="ws-panel" data-testid="results-target">
            <header className="ws-panel-head"><h3><Icon name="target" size={18} /> Target</h3></header>
            <dl className="kv-list">
              <div><dt>Object ID</dt><dd>{result.object_id || "—"}</dd></div>
              {cr?.matched_kepler_name && <div><dt>Kepler name</dt><dd>{cr.matched_kepler_name}</dd></div>}
              {cr?.matched_kepoi_name && <div><dt>KOI</dt><dd>{cr.matched_kepoi_name}</dd></div>}
              {cr?.matched_kepid && <div><dt>Host star</dt><dd>KIC {cr.matched_kepid}</dd></div>}
              <div><dt>Light curve</dt><dd>{result.filename}</dd></div>
              <div><dt>Points used / dropped</dt><dd>{diagnostics.n_points_used} / {diagnostics.n_points_dropped}</dd></div>
              <div><dt>Baseline</dt><dd>{diagnostics.baseline_days.toFixed(2)} days</dd></div>
            </dl>
            {cr && (
              <p className={`kv-note${cr.match_status === "matched_koi" || cr.match_status === "matched_star" ? "" : " warn"}`}>
                {MATCH_TEXT[cr.match_status] || cr.match_status}. {cr.note}
              </p>
            )}
          </section>

          <section className="ws-panel">
            <header className="ws-panel-head"><h3><Icon name="database" size={18} /> Parameter sources</h3></header>
            <p className="char-muted" style={{ marginTop: 0 }}>Where the 17 submitted model parameters came from.</p>
            <ul className="source-counts">
              {["catalog", "estimated", "derived", "manual", "unavailable"].filter((k) => counts[k]).map((k) => (
                <li key={k}><SourceTag source={k} /> <strong>{counts[k]}</strong></li>
              ))}
            </ul>
          </section>
        </div>

        {/* ---- Centre: detection & prediction evidence ---- */}
        <div className="results-col results-main">
          <section className="ws-panel" data-testid="results-detection">
            <header className="ws-panel-head">
              <h3><Icon name="show_chart" size={18} /> Transit Detection</h3>
              <span className={`char-chip ${detection.detected ? "status-complete" : "status-partial"}`} data-testid="detection-chip">{detection.label}</span>
            </header>
            <TransitLightCurveChart folded={characterization?.transit_fit?.folded} compact />
            <h4 className="ws-subhead">Box Least Squares transit search</h4>
            <dl className="metric-grid">
              <div><dt>Best period</dt><dd>{diagnostics.bls_period_days.toFixed(4)} d</dd></div>
              <div><dt>Transit depth</dt><dd>{diagnostics.bls_depth_ppm.toFixed(1)} ppm</dd></div>
              <div><dt>Transit duration</dt><dd>{diagnostics.bls_duration_hours.toFixed(2)} h</dd></div>
              <div data-testid="bls-snr">
                <dt>Transit SNR (BLS box)</dt>
                <dd>
                  {formatNumber(diagnostics.bls_transit_snr, 3) ?? "Unavailable"}
                  {Number.isFinite(diagnostics.bls_transit_snr) && (
                    <span className={`snr-flag ${diagnostics.bls_transit_snr >= DETECTION_SNR ? "ok" : "low"}`}>
                      {diagnostics.bls_transit_snr >= DETECTION_SNR ? `≥ ${DETECTION_SNR} threshold` : `below ${DETECTION_SNR}`}
                    </span>
                  )}
                </dd>
              </div>
              <div><dt>Noise per point</dt><dd>{diagnostics.bls_noise_ppm != null ? `${formatNumber(diagnostics.bls_noise_ppm, 3)} ppm` : "Unavailable"}</dd></div>
              <div><dt>In-transit points</dt><dd>{diagnostics.bls_n_in_transit ?? "—"}</dd></div>
              <div><dt>Transits observed</dt><dd>{diagnostics.num_transits_observed}</dd></div>
              <div><dt>BLS peak SDE</dt><dd>{formatNumber(diagnostics.bls_sde, 3) ?? "—"}</dd></div>
              {characterization?.parameters?.transit_snr && (
                <div><dt>Transit SNR (model fit)</dt><dd>{paramText(characterization.parameters.transit_snr)}</dd></div>
              )}
            </dl>
            <p className="char-muted" data-testid="bls-snr-definition">
              Transit SNR = δ / (σ √(1/N<sub>in</sub> + 1/N<sub>out</sub>)) for the best box, all observed transits
              combined, with σ the per-point noise (white noise assumed). {DETECTION_SNR} is the Kepler pipeline's
              transit-detection threshold (Jenkins et al. 2010), quoted for reference.{" "}
              {diagnostics.bls_transit_snr == null && "It is unavailable here because the per-point noise could not be estimated. "}
              SDE measures how far the periodogram peak stands above the other trial periods; it is not an SNR, and
              neither is a probability.
            </p>
          </section>

          <section className="ws-panel" data-testid="results-prediction">
            <header className="ws-panel-head"><h3><Icon name="neurology" size={18} /> ML Prediction</h3></header>
            <ProbabilityBar label="Weighted ensemble" value={finalResult.weighted_probability} />
            <ProbabilityBar label="Random Forest" value={finalResult.random_forest_probability} weight={finalResult.weights.random_forest} />
            <ProbabilityBar label="2D CNN" value={finalResult.cnn_probability} weight={finalResult.weights.cnn} />
            <p className="char-muted">
              Bars show each model's probability of class 1; the marker is the 0.5 decision threshold. The ensemble
              predicts class 1 when the weighted probability is at least 0.5. Class semantics are not recorded in the
              stored model artifacts, the probability is not calibrated, and a classifier score is not a confirmation
              of a planet.
            </p>
            {dependence && (
              <div className={`catalog-dependence${dependence.fromCatalog ? " is-catalog" : ""}`} data-testid="catalog-dependence">
                <h4 className="ws-subhead">Dependence on catalogue vetting</h4>
                <p>
                  One of the model's 17 inputs, <code>koi_score</code>, is NASA's Robovetter disposition score
                  {dependence.fromCatalog ? <> (here {dependence.value}, from the KOI catalogue)</> : <> (here {dependence.value}, entered manually)</>}.
                  It carries {Math.round(dependence.rf_importance * 100)}% of the Random Forest's feature importance and
                  in the KOI table alone matches NASA's own disposition for about 98% of objects, so it largely restates
                  the catalogue's verdict.
                </p>
                <ProbabilityBar label={`With koi_score at its training median (${dependence.neutral_value.toFixed(3)})`} value={dependence.weighted_probability_with_neutral_value} />
                <p className="char-muted">
                  A sensitivity check, not a corrected prediction: the model was trained with koi_score and has no
                  light-curve-only variant. {dependence.fromCatalog && "Treat the headline probability as catalogue-informed, not as independent evidence from the uploaded light curve."}
                </p>
              </div>
            )}
          </section>

          <section className="ws-panel">
            <header className="ws-panel-head"><h3><Icon name="policy" size={18} /> Transit Vetting</h3></header>
            <div className="vet-grid">
              <div className="vet-item">
                <span className="vet-label">Odd / even depth ratio</span>
                <span className="vet-value">{characterisation.odd_even_depth_ratio.toFixed(3)}</span>
                <p>Depth of even-numbered transits divided by odd-numbered ones. Values far from 1.0 suggest an eclipsing binary.</p>
              </div>
              <div className="vet-item">
                <span className="vet-label">Secondary eclipse depth</span>
                <span className="vet-value">{characterisation.secondary_eclipse_depth_ppm.toFixed(1)} ppm</span>
                <p>Flux dip opposite the primary transit. A real secondary eclipse suggests an eclipsing binary rather than a planet.</p>
              </div>
            </div>
            <p className="char-muted">{characterisation.note}</p>
          </section>
        </div>

        {/* ---- Right: findings & next stages ---- */}
        <div className="results-col results-right">
          <section className="ws-panel" data-testid="results-findings">
            <header className="ws-panel-head"><h3><Icon name="checklist" size={18} /> Findings</h3></header>
            <ul className="finding-list">
              {findings.map((f, i) => (
                <li key={i} className={`finding ${f.kind}`}>
                  <Icon name={FINDING_ICON[f.kind]} size={18} filled />
                  <div>
                    <div className="finding-title">{f.title}</div>
                    {f.text && <p>{f.text}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="ws-panel physics-teaser">
            <header className="ws-panel-head">
              <h3><Icon name="science" size={18} /> Physics Validation</h3>
              {physicsResultIsCurrent && physicsResult && <PhysicsStatusBadge status={physicsResult.overall_status} />}
            </header>
            <p className="char-muted" style={{ marginTop: 0 }}>
              Independently checks transit depth, duration and orbital configuration against standard physics,
              separately from the classifier. A promising prediction does not by itself mean these checks pass.
            </p>
            {physicsStatus === PHYSICS_STATUS.ERROR && (
              <p style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
                {physicsError?.message || "Physics validation failed. Try again."}
              </p>
            )}
            <button
              className="btn btn-primary btn-block"
              onClick={handleStartPhysicsValidation}
              disabled={physicsStatus === PHYSICS_STATUS.RUNNING}
            >
              {physicsStatus === PHYSICS_STATUS.RUNNING ? (
                <><Icon name="progress_activity" size={16} className="icon-spin" /> Running Physics Validation…</>
              ) : physicsResultIsCurrent && physicsResult ? (
                <>View Physics Validation <Icon name="arrow_forward" size={16} /></>
              ) : (
                <><Icon name="science" size={16} /> Start Physics Validation</>
              )}
            </button>
          </section>

          <section className="ws-panel" data-testid="results-characterization">
            <header className="ws-panel-head"><h3><Icon name="radar" size={18} /> Planet Characterization</h3></header>
            {characterization ? (
              <>
                {characterizationStatus === CHARACTERIZATION_STATUS.RUNNING && (
                  <p className="char-note"><Icon name="progress_activity" size={16} className="icon-spin" /> Updating with your edited parameters…</p>
                )}
                <dl className="kv-list">
                  <div><dt>Planet radius</dt><dd>{paramText(characterization.parameters?.planet_radius)}</dd></div>
                  <div><dt>Size category</dt><dd>{sizeClass?.status === "computed" ? sizeClass.category : "Unavailable"}</dd></div>
                  <div><dt>Status</dt><dd><StatusChip status={characterization.status} /> <ReliabilityTag level={characterization.reliability} /></dd></div>
                </dl>
                <Link to="/characterisation" className="btn btn-ghost btn-block">
                  Open Planet Characterization <Icon name="arrow_forward" size={16} />
                </Link>
              </>
            ) : (
              <p className="char-muted" style={{ margin: 0 }}>
                No characterization report is attached to this session (it was analyzed before the characterization
                engine existed, or was a tabular upload). Start a new prediction to characterize this candidate.
              </p>
            )}
          </section>
        </div>
      </div>

      <section className="ws-panel results-inputs" data-testid="results-model-inputs">
        <header className="ws-panel-head">
          <h3><Icon name="table_rows" size={18} /> Model inputs</h3>
          <span className="char-muted">The 17 parameters exactly as submitted to the classifier</span>
        </header>
        <div className="inputs-groups">
          {groups.map(({ category, features: rows }) => (
            <div className="inputs-group" key={category}>
              <h4 className="ws-subhead">{category}</h4>
              <div className="table-scroll">
                <table className="feature-table data-table">
                  <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th>Source</th></tr></thead>
                  <tbody>
                    {rows.map((f) => {
                      const value = manualParameters[f.canonical];
                      const shown = formatNumber(value, 6);
                      return (
                        <tr key={f.canonical}>
                          <th>
                            {f.display}
                            {f.display !== f.canonical && <span className="mono-sub">{f.canonical}</span>}
                          </th>
                          <td className="value">{shown ?? "Unavailable"}</td>
                          <td>{f.unit || "—"}</td>
                          <td><SourceTag source={featureSource(f.canonical, result, manualParameters)} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
        <details className="physics-calc-details ws-details">
          <summary>Technical details (raw response data)</summary>
          <div className="physics-calc-body">
            <p className="char-muted">For developers: the prediction and light-curve diagnostics exactly as returned by the API.</p>
            <pre className="raw-json">{JSON.stringify({ prediction: finalResult, diagnostics, vetting: characterisation, catalog_resolution: cr }, null, 2)}</pre>
          </div>
        </details>
      </section>

      <StageNav current="/results" />

      <div style={{ display: "flex", justifyContent: "center", marginTop: 8 }}>
        <button className="btn btn-ghost" onClick={handleNewPrediction}>
          <Icon name="refresh" size={16} /> Start a New Prediction
        </button>
      </div>
    </div>
  );
}
