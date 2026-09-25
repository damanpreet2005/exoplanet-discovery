/**
 * Aligned grid form for the manual 17-parameter input mode. All fields share
 * one CSS Grid container (see .param-form-grid in index.css) so label/input/
 * unit columns line up across every row regardless of label text length.
 */
export default function ManualParamForm({ features, values, onChange, disabled }) {
  return (
    <div className="param-form-grid">
      {features.map((feature) => (
        <div className="param-row" key={feature.canonical}>
          <label className="param-label" htmlFor={`param-${feature.canonical}`}>
            <span className="display-name">{feature.display}</span>
            <span className="canonical-name">({feature.canonical})</span>
          </label>
          <input
            id={`param-${feature.canonical}`}
            className="param-input"
            type="number"
            step="any"
            disabled={disabled}
            value={values[feature.canonical] ?? ""}
            onChange={(e) => onChange(feature.canonical, e.target.value)}
          />
          <span className="param-unit">{feature.unit}</span>
        </div>
      ))}
    </div>
  );
}
