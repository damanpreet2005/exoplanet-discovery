/**
 * Where each of the 17 submitted model parameters actually came from.
 *
 * The light-curve upload response attributes every feature it resolved
 * (`result.features[canonical].status`: estimated / derived / catalog /
 * unavailable). The values actually submitted for prediction and physics
 * validation are `manualParameters`; a value that differs from the
 * automatic one (or fills an unavailable one) was entered by the user.
 */
export const SOURCE_META = {
  catalog: { label: "Catalogue", className: "src-catalog" },
  estimated: { label: "Light curve", className: "src-estimated" },
  derived: { label: "Derived", className: "src-derived" },
  manual: { label: "Manual entry", className: "src-manual" },
  unavailable: { label: "Unavailable", className: "src-unavailable" },
};

function sameValue(a, b) {
  if (a === null || a === undefined || b === null || b === undefined) return false;
  const x = Number(a);
  const y = Number(b);
  return Math.abs(x - y) <= 1e-9 * Math.max(1, Math.abs(y));
}

export function featureSource(canonical, result, manualParameters) {
  const auto = result?.features?.[canonical];
  const submitted = manualParameters?.[canonical];
  const hasSubmitted = submitted !== null && submitted !== undefined;
  if (!auto) return hasSubmitted ? "manual" : "unavailable";
  if (!hasSubmitted) return auto.status === "unavailable" ? "unavailable" : auto.status;
  if (auto.status === "unavailable" || !sameValue(submitted, auto.value)) return "manual";
  return auto.status;
}

/** Counts of submitted parameters by source, e.g. {catalog: 9, estimated: 4, ...}. */
export function sourceCounts(result, manualParameters) {
  const counts = {};
  for (const canonical of Object.keys(manualParameters || {})) {
    const s = featureSource(canonical, result, manualParameters);
    counts[s] = (counts[s] || 0) + 1;
  }
  return counts;
}

/** Compact numeric display for a raw value; never turns a missing value into 0. */
export function formatNumber(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  const v = Number(value);
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs >= 1e5 || abs < 1e-3) return v.toExponential(2);
  return Number(v.toPrecision(digits)).toString();
}
