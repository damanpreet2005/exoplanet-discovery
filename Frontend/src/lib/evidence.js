/**
 * Keeps the four lines of evidence separate: transit detection in the
 * uploaded light curve, catalogue information, the ML classification (which
 * consumes catalogue features), and physics validation.
 */

// Kepler TPS detection threshold (Jenkins et al. 2010) for a white-noise
// depth/noise transit statistic; the box and model-fit SNRs share that form.
export const DETECTION_SNR = 7.1;

/**
 * Detection from the uploaded light curve only. Uses the transit-model fit
 * SNR when one exists (it includes the red-noise factor), otherwise the BLS
 * box SNR. A completed characterization is not itself a detection.
 */
export function transitDetection(result, characterization) {
  const fit = characterization?.parameters?.transit_snr;
  const fitSnr = fit?.status === "computed" && Number.isFinite(fit.value) ? fit.value : null;
  const blsSnr = Number.isFinite(result?.diagnostics?.bls_transit_snr) ? result.diagnostics.bls_transit_snr : null;
  const snr = fitSnr ?? blsSnr;
  const basis = fitSnr !== null ? "transit-model fit" : "BLS transit search";
  if (snr === null) {
    return { detected: null, snr: null, basis, label: "Detection not assessed",
      text: "No transit signal-to-noise ratio could be computed for this light curve." };
  }
  const detected = snr >= DETECTION_SNR;
  return {
    detected, snr, basis,
    label: detected ? "Significant transit detected" : "No significant transit detected",
    text: `${basis === "transit-model fit" ? "Model-fit" : "BLS"} SNR ${snr.toFixed(1)} is ${detected ? "at or above" : "below"} the ${DETECTION_SNR} detection threshold`
      + (blsSnr !== null && fitSnr !== null ? ` (BLS SNR ${blsSnr.toFixed(1)}).` : "."),
  };
}

/**
 * True when the Planet Size check is circular: koi_prad was computed from the
 * same transit depth (Rp = R* sqrt(depth)) and not edited, so the expected
 * and observed depths agree by construction and the check cannot fail.
 */
export function planetSizeIsCircular(result, submitted) {
  const prad = result?.features?.koi_prad;
  if (!prad || prad.source !== "derived_rp_eq_rstar_sqrt_depth") return false;
  const same = (key) => {
    const auto = result?.features?.[key]?.value;
    const v = submitted?.[key];
    return v !== undefined && v !== null && auto !== null && auto !== undefined
      && Math.abs(Number(v) - Number(auto)) <= 1e-9 * Math.max(1, Math.abs(Number(auto)));
  };
  return same("koi_prad") && same("koi_depth");
}

/**
 * How much the ML probability rests on the catalogue's koi_score (NASA's
 * Robovetter disposition score). `features` is the upload's attributed
 * feature report; `submitted` the values actually sent to the model.
 */
export function catalogDependence(prediction, features, submitted) {
  const dep = prediction?.catalog_dependence;
  if (!dep) return null;
  const fromCatalog = features?.koi_score?.status === "catalog"
    && submitted?.koi_score !== undefined && Math.abs(Number(submitted.koi_score) - Number(features.koi_score.value)) < 1e-9;
  return {
    ...dep,
    fromCatalog,
    shift: prediction.weighted_probability - dep.weighted_probability_with_neutral_value,
  };
}
