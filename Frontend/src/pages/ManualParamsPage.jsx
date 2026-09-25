import { useEffect, useState } from "react";
import ManualParamForm from "../components/ManualParamForm";
import StateBlock from "../components/StateBlock";
import { fetchFeatureSchema, submitManualParameters } from "../api/client";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function ManualParamsPage() {
  const [schemaState, setSchemaState] = useState({ loading: true, features: [], orderConfigured: false, error: null });
  const [values, setValues] = useState({});
  const [submitState, setSubmitState] = useState({ status: "idle", result: null, error: null });

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

  function handleChange(canonical, rawValue) {
    setValues((prev) => ({ ...prev, [canonical]: rawValue }));
  }

  const allFilled = schemaState.features.length > 0 &&
    schemaState.features.every((f) => values[f.canonical] !== undefined && values[f.canonical] !== "" && !Number.isNaN(Number(values[f.canonical])));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!allFilled) return;
    setSubmitState({ status: "loading", result: null, error: null });
    const payload = {};
    for (const f of schemaState.features) payload[f.canonical] = Number(values[f.canonical]);
    try {
      const result = await submitManualParameters(payload);
      setSubmitState({ status: "success", result, error: null });
    } catch (err) {
      setSubmitState({ status: "error", result: null, error: err });
    }
  }

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Manual Parameter Entry</h1>
        <p className="page-subtitle">
          Enter the model's input parameters directly. These are mapped internally to the exact
          feature vector the trained scaler expects, in its trained order.
        </p>
      </header>

      <div className="panel">
        {schemaState.loading && (
          <StateBlock icon="⏳" title="Loading parameter list…" />
        )}

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
                yet, so submissions here will return a clear configuration error rather than a
                fabricated prediction until it is.
              </p>
            )}
            <form onSubmit={handleSubmit}>
              <ManualParamForm
                features={schemaState.features}
                values={values}
                onChange={handleChange}
                disabled={submitState.status === "loading"}
              />
              <button
                type="submit"
                className="btn btn-primary"
                style={{ marginTop: 24 }}
                disabled={!allFilled || submitState.status === "loading"}
              >
                {submitState.status === "loading" ? "Predicting…" : "Predict"}
              </button>
            </form>
          </>
        )}

        {submitState.status === "error" && (
          <div style={{ marginTop: 24 }}>
            <StateBlock
              variant="error"
              icon="⚠️"
              title={submitState.error?.code || "Prediction failed"}
              description={submitState.error?.message}
            />
          </div>
        )}

        {submitState.status === "success" && submitState.result && (
          <div className="summary-row" style={{ marginTop: 24 }}>
            <div className="summary-tile">
              <div className="value" style={{ color: submitState.result.prediction === 1 ? "var(--success)" : "var(--text-muted)" }}>
                {submitState.result.prediction}
              </div>
              <div className="label">Predicted class</div>
            </div>
            <div className="summary-tile">
              <div className="value">{pct(submitState.result.weighted_probability)}</div>
              <div className="label">Weighted probability</div>
            </div>
            <div className="summary-tile">
              <div className="value">{pct(submitState.result.random_forest_probability)}</div>
              <div className="label">Random Forest</div>
            </div>
            <div className="summary-tile">
              <div className="value">{pct(submitState.result.cnn_probability)}</div>
              <div className="label">1D CNN</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
