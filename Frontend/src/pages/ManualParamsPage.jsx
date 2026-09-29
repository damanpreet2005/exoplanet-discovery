import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ManualParamForm from "../components/ManualParamForm";
import StateBlock from "../components/StateBlock";
import StepIndicator from "../components/StepIndicator";
import { fetchFeatureSchema } from "../api/client";
import { useAnalysis, STATUS, FINAL_STATUS } from "../context/AnalysisContext";

// Only these fields can be legitimately suggested from a light-curve transit
// search (see ml_service's suggest_koi_parameters) -- used only as a
// fallback when a session predates the richer `features` report below.
const SUGGESTABLE_CANONICALS = new Set([
  "koi_period", "koi_time0bk", "koi_duration", "koi_depth", "koi_model_snr",
]);

export default function ManualParamsPage() {
  const { status, result, finalStatus, finalError, submitCombinedPrediction, acceptExtractedPrediction, reset } = useAnalysis();
  const navigate = useNavigate();

  const [schemaState, setSchemaState] = useState({ loading: true, features: [], orderConfigured: false, error: null });
  const [values, setValues] = useState({});
  const [prefilled, setPrefilled] = useState(new Set());
  const [expertMode, setExpertMode] = useState(false);
  const [autoAccepted, setAutoAccepted] = useState(false);

  // Route guard: this step requires a light curve already attached to the
  // session -- never an independent "just enter parameters" mode.
  useEffect(() => {
    if (status !== STATUS.SUCCESS || !result) {
      navigate("/", { replace: true });
    }
  }, [status, result, navigate]);

  // Pre-fill every field the backend already resolved (estimated/derived/
  // catalog) from the new, fully-attributed `features` report. Falls back to
  // the older suggested_parameters-only prefill for a session from before
  // this report existed. Only runs once (guarded by `values` being empty)
  // so it never clobbers user edits.
  useEffect(() => {
    if (!result || schemaState.loading || schemaState.error) return;
    setValues((prev) => {
      if (Object.keys(prev).length > 0) return prev;
      const next = {};
      const nowPrefilled = new Set();
      if (result.features) {
        for (const [canonical, fv] of Object.entries(result.features)) {
          if (fv.value !== null && fv.value !== undefined) {
            next[canonical] = String(fv.value);
            nowPrefilled.add(canonical);
          }
        }
      } else {
        for (const [canonical, value] of Object.entries(result.suggested_parameters || {})) {
          if (SUGGESTABLE_CANONICALS.has(canonical)) {
            next[canonical] = String(value);
            nowPrefilled.add(canonical);
          }
        }
      }
      setPrefilled(nowPrefilled);
      return next;
    });
  }, [result, schemaState.loading, schemaState.error]);

  useEffect(() => {
    let cancelled = false;
    fetchFeatureSchema()
      .then((body) => {
        if (cancelled) return;
        setSchemaState({ loading: false, features: body.features, orderConfigured: body.order_configured, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setSchemaState({ loading: false, features: [], orderConfigured: false, error: err });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Zero-manual-entry path: every one of the 17 features was already
  // resolved and the ML service already ran the real trained-model
  // prediction as part of the CSV-upload response -- accept it directly
  // rather than re-submitting the same values as a second network call.
  useEffect(() => {
    if (autoAccepted) return;
    if (result?.ready_for_prediction && result?.prediction && finalStatus === FINAL_STATUS.IDLE) {
      const payload = {};
      for (const [canonical, fv] of Object.entries(result.features || {})) {
        payload[canonical] = fv.value;
      }
      setAutoAccepted(true);
      acceptExtractedPrediction(payload, result.prediction);
    }
  }, [result, finalStatus, autoAccepted, acceptExtractedPrediction]);

  useEffect(() => {
    if (finalStatus === FINAL_STATUS.SUCCESS) {
      navigate("/results");
    }
  }, [finalStatus, navigate]);

  function handleWrongObjectId() {
    // The whole light-curve session was analyzed against an object ID that
    // doesn't resolve to a catalog entry -- clear it (not just this page's
    // local state) so Step 1 doesn't silently re-show the stale result/error
    // for an ID the user is about to replace.
    reset();
    navigate("/");
  }

  function handleChange(canonical, rawValue) {
    setValues((prev) => ({ ...prev, [canonical]: rawValue }));
    setPrefilled((prev) => {
      if (!prev.has(canonical)) return prev;
      const next = new Set(prev);
      next.delete(canonical); // user edited it -- no longer just a suggestion
      return next;
    });
  }

  const statusByCanonical = {};
  if (result?.features) {
    for (const [canonical, fv] of Object.entries(result.features)) {
      statusByCanonical[canonical] = fv.status;
    }
  }
  const missingFeatures = new Set(result?.missing_features || []);
  const hasRichFeatureReport = Boolean(result?.features);

  const allFilled = schemaState.features.length > 0 &&
    schemaState.features.every((f) => values[f.canonical] !== undefined && values[f.canonical] !== "" && !Number.isNaN(Number(values[f.canonical])));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!allFilled) return;
    const payload = {};
    for (const f of schemaState.features) payload[f.canonical] = Number(values[f.canonical]);
    await submitCombinedPrediction(payload);
  }

  if (status !== STATUS.SUCCESS || !result) {
    return null; // redirecting
  }

  if (result.ready_for_prediction && result.prediction) {
    return (
      <div className="fade-in">
        <StepIndicator current={2} />
        <div className="panel">
          <StateBlock icon="✨" title="All 17 parameters resolved automatically" description="Running the trained model — you're being taken straight to your results." />
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <StepIndicator current={2} />
      <header className="page-header">
        <h1 className="page-title">Step 2 — Complete the Remaining Parameters</h1>
        <p className="page-subtitle">
          {hasRichFeatureReport && missingFeatures.size > 0
            ? `${schemaState.features.length - missingFeatures.size} of ${schemaState.features.length} model parameters were resolved automatically (from your light curve and/or a catalog lookup) and are locked below. Only the ${missingFeatures.size} field(s) marked "unavailable" need manual entry.`
            : "The final prediction combines your uploaded light curve with these 17 model parameters. A few fields have been pre-filled from your light-curve analysis where possible — review and adjust them, then fill in the rest."}
        </p>
      </header>

      <div className="attached-banner">✓ Light curve attached — {result.filename}</div>

      {result.catalog_resolution && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Object Information</h3>
          <dl className="candidate-detail" style={{ marginBottom: 12 }}>
            <div>
              <dt>Object ID</dt>
              <dd>{result.object_id}</dd>
            </div>
          </dl>
          {(result.catalog_resolution.match_status === "not_found" ||
            result.catalog_resolution.match_status === "unsupported_identifier_type") && (
            <p style={{ color: "var(--warning)", fontSize: "0.85rem", marginTop: 0, marginBottom: 8 }}>
              Stellar information unavailable for Object ID {result.object_id}. Please verify the Object ID.
            </p>
          )}
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: 0 }}>
            {result.catalog_resolution.note}
          </p>
          {(result.catalog_resolution.match_status === "not_found" ||
            result.catalog_resolution.match_status === "unsupported_identifier_type") && (
            <button type="button" className="btn btn-ghost" style={{ marginTop: 12 }} onClick={handleWrongObjectId}>
              Wrong Input? Try Again
            </button>
          )}
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Light Curve Summary</h3>
        <dl className="candidate-detail">
          <div>
            <dt>BLS period</dt>
            <dd>{result.diagnostics.bls_period_days.toFixed(4)} days</dd>
          </div>
          <div>
            <dt>Transit depth</dt>
            <dd>{result.diagnostics.bls_depth_ppm.toFixed(1)} ppm</dd>
          </div>
          <div>
            <dt>Transit duration</dt>
            <dd>{result.diagnostics.bls_duration_hours.toFixed(2)} hours</dd>
          </div>
          <div>
            <dt>Points used</dt>
            <dd>{result.diagnostics.n_points_used}</dd>
          </div>
        </dl>
      </div>

      <div className="panel">
        {schemaState.loading && <StateBlock icon="⏳" title="Loading parameter list…" />}

        {schemaState.error && (
          <StateBlock
            variant="error"
            icon="⚠️"
            title="Could not load the parameter schema"
            description={schemaState.error.message || "Is the backend running?"}
          />
        )}

        {!schemaState.loading && !schemaState.error && (
          <>
            {!schemaState.orderConfigured && (
              <p style={{ color: "var(--warning)", fontSize: "0.85rem", marginTop: 0 }}>
                ⚠️ The model's exact trained feature order has not been confirmed in this deployment
                yet, so submitting will return a clear configuration error rather than a fabricated
                prediction until it is.
              </p>
            )}
            {hasRichFeatureReport ? (
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: 16 }}>
                <input type="checkbox" checked={expertMode} onChange={(e) => setExpertMode(e.target.checked)} />
                Expert override — unlock the automatically-resolved fields for manual editing
              </label>
            ) : (
              prefilled.size > 0 && (
                <p style={{ color: "var(--accent-cyan)", fontSize: "0.8rem", marginTop: 0 }}>
                  Fields marked with a light-curve estimate below are editable — adjust them if you
                  have more precise catalog values.
                </p>
              )
            )}
            <form onSubmit={handleSubmit}>
              <ManualParamForm
                features={schemaState.features}
                values={values}
                onChange={handleChange}
                disabled={finalStatus === FINAL_STATUS.SUBMITTING}
                prefilled={prefilled}
                statusByCanonical={hasRichFeatureReport ? statusByCanonical : undefined}
                expertMode={expertMode}
              />
              <button
                type="submit"
                className="btn btn-primary"
                style={{ marginTop: 24 }}
                disabled={!allFilled || finalStatus === FINAL_STATUS.SUBMITTING}
              >
                {finalStatus === FINAL_STATUS.SUBMITTING ? "Running combined prediction…" : "Submit"}
              </button>
            </form>
          </>
        )}

        {finalStatus === FINAL_STATUS.ERROR && (
          <div style={{ marginTop: 24 }}>
            <StateBlock
              variant="error"
              icon="⚠️"
              title={finalError?.code || "Prediction failed"}
              description={finalError?.message}
            />
          </div>
        )}
      </div>
    </div>
  );
}
