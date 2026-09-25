import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ManualParamForm from "../components/ManualParamForm";
import StateBlock from "../components/StateBlock";
import StepIndicator from "../components/StepIndicator";
import { fetchFeatureSchema } from "../api/client";
import { useAnalysis, STATUS, FINAL_STATUS } from "../context/AnalysisContext";

// Only these fields can be legitimately suggested from a light-curve transit
// search (see ml_service's suggest_koi_parameters) -- everything else is a
// stellar/catalog value a light curve cannot provide, so it stays manual.
const SUGGESTABLE_CANONICALS = new Set([
  "koi_period", "koi_time0bk", "koi_duration", "koi_depth", "koi_model_snr",
]);

export default function ManualParamsPage() {
  const { status, result, finalStatus, finalError, submitCombinedPrediction } = useAnalysis();
  const navigate = useNavigate();

  const [schemaState, setSchemaState] = useState({ loading: true, features: [], orderConfigured: false, error: null });
  const [values, setValues] = useState({});
  const [prefilled, setPrefilled] = useState(new Set());

  // Route guard: this step requires a light curve already attached to the
  // session -- never an independent "just enter parameters" mode.
  useEffect(() => {
    if (status !== STATUS.SUCCESS || !result) {
      navigate("/", { replace: true });
    }
  }, [status, result, navigate]);

  // Once both the light-curve result and the schema are available, pre-fill
  // the subset of fields the transit search can inform. Only runs once
  // (guarded by `values` being empty) so it never clobbers user edits.
  useEffect(() => {
    if (!result || schemaState.loading || schemaState.error) return;
    setValues((prev) => {
      if (Object.keys(prev).length > 0) return prev;
      const next = {};
      const nowPrefilled = new Set();
      for (const [canonical, value] of Object.entries(result.suggested_parameters || {})) {
        if (SUGGESTABLE_CANONICALS.has(canonical)) {
          next[canonical] = String(value);
          nowPrefilled.add(canonical);
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

  useEffect(() => {
    if (finalStatus === FINAL_STATUS.SUCCESS) {
      navigate("/results");
    }
  }, [finalStatus, navigate]);

  function handleChange(canonical, rawValue) {
    setValues((prev) => ({ ...prev, [canonical]: rawValue }));
    setPrefilled((prev) => {
      if (!prev.has(canonical)) return prev;
      const next = new Set(prev);
      next.delete(canonical); // user edited it -- no longer just a suggestion
      return next;
    });
  }

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

  return (
    <div className="fade-in">
      <StepIndicator current={2} />
      <header className="page-header">
        <h1 className="page-title">Step 2 — Enter Planet &amp; Stellar Parameters</h1>
        <p className="page-subtitle">
          The final prediction combines your uploaded light curve with these 17 model parameters.
          A few fields have been pre-filled from your light-curve analysis where possible — review
          and adjust them, then fill in the rest.
        </p>
      </header>

      <div className="attached-banner">✓ Light curve attached — {result.filename}</div>

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
            {prefilled.size > 0 && (
              <p style={{ color: "var(--accent-cyan)", fontSize: "0.8rem", marginTop: 0 }}>
                Fields marked with a light-curve estimate below are editable — adjust them if you
                have more precise catalog values.
              </p>
            )}
            <form onSubmit={handleSubmit}>
              <ManualParamForm
                features={schemaState.features}
                values={values}
                onChange={handleChange}
                disabled={finalStatus === FINAL_STATUS.SUBMITTING}
                prefilled={prefilled}
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
