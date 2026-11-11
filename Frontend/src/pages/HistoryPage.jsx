import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import StateBlock from "../components/StateBlock";
import Icon from "../components/Icon";
import { downloadPredictionCsv, fetchPredictionCsv, fetchPredictionHistory, renamePrediction } from "../api/client";
import { useAnalysis } from "../context/AnalysisContext";

function pct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

const RUN_KIND_TEXT = { upload: "CSV analysis", manual: "Parameters submitted" };

/** The prediction's name, renamed in place. */
function NameCell({ run, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(run.name);
  const [state, setState] = useState({ busy: false, error: null });

  async function save(event) {
    event.preventDefault();
    setState({ busy: true, error: null });
    try {
      onRenamed(await renamePrediction(run.id, draft.trim()));
      setEditing(false);
      setState({ busy: false, error: null });
    } catch (err) {
      setState({ busy: false, error: err?.message || "Could not rename the prediction." });
    }
  }

  if (!editing) {
    return (
      <div className="history-name">
        <span className="history-name-text">{run.name}</span>
        <button
          type="button"
          className="btn btn-ghost history-name-edit"
          onClick={() => { setDraft(run.name); setEditing(true); }}
          aria-label={`Rename ${run.name}`}
          title="Rename"
        >
          <Icon name="edit" size={14} />
        </button>
      </div>
    );
  }

  return (
    <form className="history-name-form" onSubmit={save}>
      <input
        className="history-name-input"
        value={draft}
        maxLength={80}
        onChange={(e) => setDraft(e.target.value)}
        aria-label="Prediction name"
        placeholder="Leave empty for the default name"
        autoFocus
        disabled={state.busy}
      />
      <button type="submit" className="btn btn-ghost" disabled={state.busy} aria-label="Save name">
        <Icon name={state.busy ? "progress_activity" : "check"} size={16} className={state.busy ? "icon-spin" : undefined} />
      </button>
      <button type="button" className="btn btn-ghost" disabled={state.busy} onClick={() => setEditing(false)} aria-label="Cancel renaming">
        <Icon name="close" size={16} />
      </button>
      {state.error && <div className="history-row-error" role="alert">{state.error}</div>}
    </form>
  );
}

/** When the prediction was run: latest run, first run, and every run time. */
function RunTimesCell({ run }) {
  const runs = Array.isArray(run.runs) ? [...run.runs].reverse() : [];
  return (
    <>
      <time dateTime={run.last_run_at}>{formatDate(run.last_run_at)}</time>
      {run.run_count > 1 && (
        <details className="history-params">
          <summary>
            {run.run_count} runs · first {formatDate(run.first_run_at)}
          </summary>
          <ul className="history-run-list">
            {runs.map((r, i) => (
              <li key={`${r.at}-${i}`}>
                <time dateTime={r.at}>{formatDate(r.at)}</time> · {RUN_KIND_TEXT[r.kind] || r.kind}
              </li>
            ))}
          </ul>
          {run.run_count > runs.length && <div>Only the latest {runs.length} run times are kept.</div>}
        </details>
      )}
    </>
  );
}

function outcomeText(run) {
  if (run.dataset_type === "tabular_kepler") {
    return run.total_rows === null ? "Tabular batch" : `Tabular batch · ${run.total_rows} rows`;
  }
  if (run.prediction === null) return "No prediction yet";
  return `Class ${run.prediction} · ${pct(run.weighted_probability)}`;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

const PARAMETER_SOURCE_TEXT = { manual: "entered manually", extracted: "resolved automatically" };

/** The exact parameter values the run's (latest) prediction used. */
function ParametersDetail({ run }) {
  if (!Array.isArray(run.parameters) || run.parameters.length === 0) return null;
  const source = PARAMETER_SOURCE_TEXT[run.parameters_source] || "submitted";
  const resubmitted = run.manual_submission_count > 1 ? ` · latest of ${run.manual_submission_count} submissions` : "";
  return (
    <details className="history-params">
      <summary>
        {run.parameters.length} parameters {source}
        {resubmitted}
      </summary>
      <table className="feature-table data-table">
        <tbody>
          {run.parameters.map((p) => (
            <tr key={p.name}>
              <th scope="row">{p.name}</th>
              <td className="value">{formatValue(p.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** Named values for re-running a run, only when the user entered them manually. */
function manualParameterPreset(run) {
  if (run.parameters_source !== "manual" || !Array.isArray(run.parameters)) return null;
  return Object.fromEntries(run.parameters.map((p) => [p.name, p.value]));
}

function ActionsCell({ run }) {
  const { analyze } = useAnalysis();
  const navigate = useNavigate();
  const [state, setState] = useState({ busy: null, error: null });

  // Older or partially-saved runs have no stored CSV; that is shown, not treated as an error.
  if (!run.csv_file_id) {
    return <span className="char-muted">CSV unavailable</span>;
  }

  async function handleDownload() {
    setState({ busy: "download", error: null });
    try {
      await downloadPredictionCsv(run.csv_file_id, run.filename);
      setState({ busy: null, error: null });
    } catch (err) {
      setState({ busy: null, error: err?.message || "Could not download the saved CSV." });
    }
  }

  // Re-runs the saved analysis through the normal workflow: the stored CSV
  // and Object ID are uploaded again (a new history run), and manually
  // entered parameters are restored into the parameter form.
  async function handleRerun() {
    setState({ busy: "rerun", error: null });
    let file;
    try {
      const blob = await fetchPredictionCsv(run.csv_file_id);
      file = new File([blob], run.filename || "prediction.csv", { type: "text/csv" });
    } catch (err) {
      setState({ busy: null, error: err?.message || "Could not load the saved CSV." });
      return;
    }
    analyze(file, run.object_id || "", { parameterPreset: manualParameterPreset(run) });
    navigate("/");
  }

  return (
    <>
      <div className="history-actions">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={handleRerun}
          disabled={state.busy !== null}
          aria-label={`Re-run ${run.filename}`}
        >
          <Icon name={state.busy === "rerun" ? "progress_activity" : "replay"} size={16} className={state.busy === "rerun" ? "icon-spin" : undefined} />
          {state.busy === "rerun" ? "Loading…" : "Re-run"}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={handleDownload}
          disabled={state.busy !== null}
          aria-label={`Download ${run.filename}`}
        >
          <Icon name={state.busy === "download" ? "progress_activity" : "download"} size={16} className={state.busy === "download" ? "icon-spin" : undefined} />
          {state.busy === "download" ? "Downloading…" : "CSV"}
        </button>
      </div>
      {state.error && (
        <div className="history-row-error" role="alert">
          {state.error}
        </div>
      )}
    </>
  );
}

export default function HistoryPage() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await fetchPredictionHistory();
      setRuns(Array.isArray(body?.runs) ? body.runs : []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRenamed = useCallback((updated) => {
    setRuns((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
  }, []);

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Prediction History</h1>
        <p className="page-subtitle">
          Your predictions, most recently run first. Running the same CSV for the same Object ID again updates its
          entry here (with the time of every run) instead of adding a duplicate. Each keeps the exact CSV you
          uploaded and the parameter values the model was run on, so you can download it or re-run it.
        </p>
      </header>

      {loading && (
        <div className="panel">
          <StateBlock
            icon={<Icon name="progress_activity" size={32} className="icon-spin" />}
            title="Loading your history…"
          />
        </div>
      )}

      {!loading && error && (
        <div className="panel">
          <StateBlock
            variant="error"
            icon={<Icon name="error" size={32} />}
            title={error.code || "History unavailable"}
            description={error.message || "Could not load your prediction history."}
            action={
              <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={load}>
                <Icon name="refresh" size={16} /> Retry
              </button>
            }
          />
        </div>
      )}

      {!loading && !error && runs && runs.length === 0 && (
        <div className="panel">
          <StateBlock
            icon={<Icon name="history" size={32} />}
            title="No saved predictions yet"
            description="Runs are saved here automatically after a successful CSV analysis."
            action={
              <Link to="/" className="btn btn-primary" style={{ marginTop: 12 }}>
                <Icon name="satellite_alt" size={16} /> Upload & Analyze
              </Link>
            }
          />
        </div>
      )}

      {!loading && !error && runs && runs.length > 0 && (
        <div className="panel">
          <div className="table-scroll">
            <table className="feature-table data-table">
              <thead>
                <tr>
                  <th>Prediction</th>
                  <th>Last run</th>
                  <th>File</th>
                  <th>Object ID</th>
                  <th>Result</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <th scope="row">
                      <NameCell run={run} onRenamed={handleRenamed} />
                    </th>
                    <td>
                      <RunTimesCell run={run} />
                    </td>
                    <td>{run.filename || (run.dataset_type === "manual" ? "Manual entry" : "—")}</td>
                    <td>{run.object_id || "—"}</td>
                    <td className="value">
                      {outcomeText(run)}
                      <ParametersDetail run={run} />
                    </td>
                    <td>
                      <ActionsCell run={run} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
