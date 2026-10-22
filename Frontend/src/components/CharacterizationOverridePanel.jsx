import { useEffect, useState } from "react";
import Icon from "./Icon";
import { CHARACTERIZATION_STATUS } from "../context/AnalysisContext";

// The characterization inputs an expert most often has better values for.
// Ranges and units come from the report's own `overridable_parameters`, so
// the backend remains the single source of truth for validation.
const OVERRIDE_FIELDS = [
  "stellar_radius", "stellar_mass", "stellar_teff", "stellar_logg", "stellar_metallicity",
  "planet_mass", "eccentricity", "arg_periastron", "orbital_period", "radius_ratio", "impact_parameter",
];

function toForm(overrides) {
  const out = {};
  for (const [name, spec] of Object.entries(overrides || {})) {
    const value = typeof spec === "object" ? spec.value : spec;
    const unc = typeof spec === "object" ? (spec.uncertainty ?? spec.err_plus ?? "") : "";
    out[name] = { value: String(value ?? ""), uncertainty: unc === null ? "" : String(unc) };
  }
  return out;
}

/**
 * Expert Override for the characterization engine: replace selected inputs
 * (with an optional ± uncertainty) and change the Bond albedo / heat
 * redistribution assumptions, then recompute on the backend. The original
 * automatically resolved value of every overridden parameter is kept in the
 * report and can be restored at any time.
 */
export default function CharacterizationOverridePanel({
  report, overrides, config, modelEdits, status, error, onRecompute, onRestore,
}) {
  const [form, setForm] = useState(() => toForm(overrides));
  const [albedo, setAlbedo] = useState(String(config?.bond_albedo ?? report?.config?.bond_albedo ?? 0.3));
  const [redistribution, setRedistribution] = useState(
    config?.heat_redistribution ?? report?.config?.heat_redistribution ?? "full"
  );
  const [localError, setLocalError] = useState(null);

  useEffect(() => {
    setForm(toForm(overrides));
  }, [overrides]);

  const meta = report?.overrides?.overridable_parameters || {};
  const params = report?.parameters || {};
  const running = status === CHARACTERIZATION_STATUS.RUNNING;
  const applied = report?.overrides?.applied || {};
  const recomputed = report?.overrides?.recomputed_outputs || [];
  const hasCustomisation = Object.keys(applied).length > 0 || modelEdits
    || Object.keys(config || {}).length > 0;

  function setField(name, key, value) {
    setForm((prev) => ({ ...prev, [name]: { value: "", uncertainty: "", ...prev[name], [key]: value } }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    setLocalError(null);
    const next = {};
    for (const [name, f] of Object.entries(form)) {
      if (!f.value || f.value.trim() === "") continue;
      const value = Number(f.value);
      if (!Number.isFinite(value)) {
        setLocalError(`${meta[name]?.label || name} must be a number.`);
        return;
      }
      const spec = { value };
      if (f.uncertainty && f.uncertainty.trim() !== "") {
        const u = Number(f.uncertainty);
        if (!Number.isFinite(u) || u < 0) {
          setLocalError(`Uncertainty for ${meta[name]?.label || name} must be a non-negative number.`);
          return;
        }
        spec.uncertainty = u;
      }
      next[name] = spec;
    }
    const a = Number(albedo);
    if (!Number.isFinite(a) || a < 0 || a >= 1) {
      setLocalError("Bond albedo must be between 0 and 1 (exclusive).");
      return;
    }
    onRecompute({ overrides: next, config: { bond_albedo: a, heat_redistribution: redistribution } });
  }

  return (
    <div className="panel char-section" data-testid="characterization-override-panel">
      <h3 className="char-section-title">Expert Override</h3>
      <p className="char-muted">
        Replace automatically resolved inputs with independently measured values (e.g. a spectroscopic stellar
        radius or a radial-velocity planet mass) and adjust the thermal assumptions. Dependent quantities are
        recomputed on the server; the automatic values are preserved and can be restored.
      </p>

      {modelEdits && (
        <p className="char-note">
          <Icon name="info" size={16} /> Edits made in the 17-parameter Expert Override form are also applied to
          this characterization.
        </p>
      )}

      <form onSubmit={handleSubmit}>
        <div className="char-override-grid">
          {OVERRIDE_FIELDS.filter((name) => meta[name]).map((name) => {
            const current = params[name];
            return (
              <div key={name} className="char-override-field">
                <label htmlFor={`ov-${name}`} className="char-param-label">
                  {meta[name].label}{meta[name].unit ? ` (${meta[name].unit})` : ""}
                </label>
                <div className="char-override-inputs">
                  <input
                    id={`ov-${name}`}
                    className="param-input"
                    inputMode="decimal"
                    placeholder={current?.status === "computed" ? `auto: ${current.display}` : "auto: unavailable"}
                    value={form[name]?.value ?? ""}
                    onChange={(e) => setField(name, "value", e.target.value)}
                    disabled={running}
                  />
                  <input
                    aria-label={`${meta[name].label} uncertainty`}
                    className="param-input char-unc-input"
                    inputMode="decimal"
                    placeholder="± σ"
                    value={form[name]?.uncertainty ?? ""}
                    onChange={(e) => setField(name, "uncertainty", e.target.value)}
                    disabled={running}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="char-override-grid char-assumptions">
          <div className="char-override-field">
            <label htmlFor="ov-albedo" className="char-param-label">Bond albedo (assumed)</label>
            <input id="ov-albedo" className="param-input" inputMode="decimal" value={albedo}
                   onChange={(e) => setAlbedo(e.target.value)} disabled={running} />
          </div>
          <div className="char-override-field">
            <label htmlFor="ov-redistribution" className="char-param-label">Heat redistribution</label>
            <select id="ov-redistribution" className="param-input" value={redistribution}
                    onChange={(e) => setRedistribution(e.target.value)} disabled={running}>
              <option value="full">Full (f = 1/4)</option>
              <option value="dayside">Dayside only (f = 2/3)</option>
            </select>
          </div>
        </div>

        <div className="char-override-actions">
          <button type="submit" className="btn btn-primary" disabled={running}>
            {running ? (<><Icon name="progress_activity" size={16} className="icon-spin" /> Recomputing…</>)
              : (<><Icon name="calculate" size={16} /> Recompute characterization</>)}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onRestore} disabled={running || !hasCustomisation}>
            <Icon name="restart_alt" size={16} /> Restore automatic values
          </button>
        </div>
      </form>

      {(localError || (status === CHARACTERIZATION_STATUS.ERROR && error)) && (
        <p className="char-error" role="alert">{localError || error?.message || "Recomputation failed."}</p>
      )}

      {Object.keys(applied).length > 0 && (
        <div className="char-note" data-testid="char-recomputed">
          <Icon name="tune" size={16} /> Overridden: {Object.keys(applied).join(", ")}.
          {recomputed.length > 0 && <> Recomputed from them: {recomputed.join(", ")}.</>}
        </div>
      )}
    </div>
  );
}
