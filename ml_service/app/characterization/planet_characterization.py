"""
Public interface of the Planet Characterization Engine.

    characterize_light_curve(time, flux, bls, catalog_resolution, object_id, ...)
        -> report dict        (light curve + catalogue -> full report; runs the transit fit)

    recompute_characterization(inputs, overrides, config)
        -> report dict        (re-runs only the cheap engine stage on a stored
                               input snapshot, e.g. after an expert override)

The report embeds its own `inputs` snapshot (transit-fit result + catalogue
values, all JSON-serialisable), so a client can request a recomputation
later without re-uploading or re-fitting the light curve.

Data flow
  light curve --BLS (lightcurve_extraction.py, existing)--> seed ephemeris
              --transit_fit.py--> fitted geometry + covariance + transit times
  Object ID --stellar_catalog_service.py (existing)--> KOI catalogue row(s)
              --build_inputs()--> stellar values with err1/err2, reference KOI values
  inputs + overrides + config --engine.compute_report()--> report
"""
from __future__ import annotations

import hashlib
import json
import logging
import math

import numpy as np

from app.characterization.engine import (
    SCHEMA_VERSION, CharacterizationConfig, OverrideValidationError, compute_report, normalize_overrides,
)
from app.characterization import archive_enrichment
from app.characterization.engine import INGRESS_RESOLUTION_FRACTION
from app.characterization.transit_fit import FitConfig, fit_transit, stellar_density_profile

logger = logging.getLogger("ml_service")

__all__ = ["characterize_light_curve", "recompute_characterization", "build_inputs", "OverrideValidationError",
           "CharacterizationInputError", "inputs_cache_key"]

# Catalogue column -> (engine name) for stellar values, and for the
# planet-level reference values used only for cross-checking.
# koi_smass is not in the current local snapshot (checked); it is mapped so a
# snapshot that includes it is used as the first-priority stellar mass.
STELLAR_COLUMNS = {"stellar_teff": "koi_steff", "stellar_logg": "koi_slogg", "stellar_radius": "koi_srad",
                   "stellar_mass": "koi_smass", "ra": "ra", "dec": "dec", "kepmag": "koi_kepmag"}
REFERENCE_COLUMNS = {"orbital_period": "koi_period", "transit_epoch": "koi_time0bk", "impact_parameter": "koi_impact",
                     "transit_duration": "koi_duration", "transit_depth": "koi_depth", "planet_radius": "koi_prad",
                     "equilibrium_temperature": "koi_teq", "insolation": "koi_insol", "transit_snr": "koi_model_snr"}
PERIOD_MATCH_TOLERANCE = 0.01
SNR_DETECTION_THRESHOLD = 7.1


class CharacterizationInputError(ValueError):
    """The supplied input snapshot is malformed."""


def _num(raw) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _record(row: dict, column: str) -> dict | None:
    value = _num(row.get(column))
    if value is None:
        return None
    ep, em = _num(row.get(f"{column}_err1")), _num(row.get(f"{column}_err2"))
    return {"value": value, "err_plus": abs(ep) if ep is not None else None,
            "err_minus": abs(em) if em is not None else None, "column": column}


def _catalog_inputs(resolution, period_hint: float | None) -> dict:
    if resolution is None:
        return {"match_status": "not_provided", "note": "No Object ID was supplied.", "stellar": {}, "reference": {}}
    rows = list(getattr(resolution, "matched_rows", []) or [])
    out = {"match_status": resolution.match_status, "note": resolution.note, "stellar": {}, "reference": {},
           "reference_source": None, "reference_koi": None}
    if not rows:
        return out
    # Stellar parameters are shared by every KOI on the star.
    out["stellar"] = {name: rec for name, col in STELLAR_COLUMNS.items() if (rec := _record(rows[0], col))}

    ref_row = None
    if len(rows) == 1:
        ref_row, out["reference_source"] = rows[0], "matched_koi"
    elif period_hint:
        # Several candidates on one star: use the one whose catalogue period
        # matches the light-curve period (within 1%), if exactly one does.
        matches = [r for r in rows if (p := _num(r.get("koi_period"))) and abs(p / period_hint - 1) < PERIOD_MATCH_TOLERANCE]
        if len(matches) == 1:
            ref_row, out["reference_source"] = matches[0], "period_matched"
            out["note"] = (out["note"] + f" Reference KOI {matches[0]['kepoi_name']} selected because its catalogue "
                           "period matches the light-curve period within 1%.").strip()
    if ref_row is not None:
        out["reference"] = {name: rec for name, col in REFERENCE_COLUMNS.items() if (rec := _record(ref_row, col))}
        out["reference_koi"] = {"kepoi_name": ref_row.get("kepoi_name"), "kepler_name": ref_row.get("kepler_name"),
                                "disposition": ref_row.get("koi_disposition")}
    return out


def build_inputs(time: np.ndarray, flux: np.ndarray, bls, catalog_resolution=None, object_id: str | None = None,
                 fit_config: FitConfig | None = None, archive_lookup: bool = False) -> dict:
    """Runs the transit fit and assembles the JSON-serialisable input
    snapshot. `bls` is the existing lightcurve_extraction.BlsResult."""
    fit = fit_transit(time, flux, bls.period_days, bls.transit_epoch, bls.duration_hours / 24.0,
                      bls.depth_fraction, bls.snr, fit_config)
    period_hint = fit.params.get("period") if fit.status == "fitted" else bls.period_days
    res = catalog_resolution
    catalog = _catalog_inputs(res, period_hint)
    fit = _maybe_refit_from_catalog(time, flux, fit, catalog, fit_config)
    fit = _refit_with_stellar_density(time, flux, fit, catalog, fit_config)
    if archive_lookup and getattr(res, "matched_kepid", None):
        # The planet is the period-matched reference KOI when the star has
        # several; with no verified reference KOI no planet values are fetched.
        ref_koi = catalog.get("reference_koi") or {}
        planet_name = ref_koi.get("kepler_name") or None
        period = fit.params.get("period") if fit.status == "fitted" else None
        catalog["archive"] = archive_enrichment.lookup(res.matched_kepid, planet_name, catalog.get("stellar"), period)
    candidate = {
        "object_id": object_id,
        "identifier_type": getattr(res, "identifier_type", None),
        "match_status": getattr(res, "match_status", "not_provided"),
        "kepid": getattr(res, "matched_kepid", None),
        "kepoi_name": getattr(res, "matched_kepoi_name", None),
        "kepler_name": getattr(res, "matched_kepler_name", None),
    }
    if catalog.get("reference_koi") and not candidate["kepoi_name"]:
        candidate["reference_kepoi_name"] = catalog["reference_koi"]["kepoi_name"]
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "light_curve": {"n_points": int(len(time)), "baseline_days": float(time[-1] - time[0]),
                        "median_cadence_days": float(np.median(np.diff(time))),
                        "bls": {"period_days": bls.period_days, "epoch": bls.transit_epoch,
                                "duration_hours": bls.duration_hours, "depth_ppm": bls.depth_ppm, "snr": bls.snr}},
        "transit_fit": json.loads(json.dumps(fit.to_dict(), default=float)),
        "catalog": catalog,
    }


def catalog_stellar_density(catalog: dict) -> dict | None:
    """rho* = 3 g / (4 pi G R*) from catalogue log g and R* (g/cm^3), with a
    1-sigma uncertainty from both (asymmetric errors averaged). None when
    either value or its uncertainty is missing -- an unquantified prior is
    never applied."""
    st = catalog.get("stellar") or {}
    logg, rad = st.get("stellar_logg"), st.get("stellar_radius")
    if not (logg and rad and rad.get("value", 0) > 0):
        return None
    def sig(rec):
        errs = [e for e in (rec.get("err_plus"), rec.get("err_minus")) if e is not None]
        return sum(errs) / len(errs) if errs else None
    s_logg, s_rad = sig(logg), sig(rad)
    if not s_logg or not s_rad:
        return None
    g = 10 ** logg["value"]
    r_cm = rad["value"] * 6.957e10
    rho = 3 * g / (4 * math.pi * 6.67430e-8 * r_cm)
    sigma_ln = math.hypot(math.log(10) * s_logg, s_rad / rad["value"])
    return {"value": rho, "sigma": rho * sigma_ln, "source": "catalogue log g and stellar radius (koi_slogg, koi_srad)"}


def _refit_with_stellar_density(time, flux, fit, catalog: dict, fit_config: FitConfig | None):
    """Refits the transit with the catalogue stellar density as a prior on
    a/R*, which breaks the b - a/R* degeneracy that otherwise leaves the
    impact parameter, durations and inclination poorly constrained. Seeded
    from the chosen fit's ephemeris. The prior-free fit is kept on the result
    (`unconstrained`) so the transit-only stellar density can still be
    checked independently against the catalogue. Falls back to the prior-free
    fit if the constrained one fails."""
    # Only a significant transit has a geometry to constrain (this also keeps
    # the profile likelihood from refitting noise at a spurious short period).
    if fit.status != "fitted" or fit.snr is None or fit.snr < SNR_DETECTION_THRESHOLD:
        return fit
    prior = catalog_stellar_density(catalog)
    if prior is None:
        # No catalogue density: no prior, but the light-curve-only density
        # still comes from the profile, not the (invalid) linear covariance.
        fit.density_profile = _transit_only_density(time, flux, fit, fit_config)
        return fit
    p = fit.params
    t14 = fit.t14_days or (fit.bls.get("duration_hours", 0) / 24.0)
    constrained = fit_transit(time, flux, p["period"], p["t0"], t14, fit.depth or p["k"] ** 2, fit.bls.get("snr"),
                              fit_config, rho_prior=prior)
    if constrained.status != "fitted":
        return fit
    constrained.seed_source = fit.seed_source
    constrained.bls = fit.bls
    constrained.warnings = [w for w in fit.warnings if w not in constrained.warnings] + constrained.warnings
    constrained.unconstrained = {
        "params": fit.params, "errors": fit.errors, "fitted_names": fit.fitted_names,
        "covariance": fit.covariance, "reduced_chi2": fit.reduced_chi2, "chi2": fit.chi2,
        "density_profile": _transit_only_density(time, flux, constrained, fit_config, profile_fit=fit),
    }
    logger.info("characterization_density_prior_fit", extra={"b_free": p.get("b"), "b_prior": constrained.params["b"]})
    return constrained


def _transit_only_density(time, flux, fit, fit_config, profile_fit=None) -> dict | None:
    """The prior-free profile likelihood of rho*, or a record that the transit
    shape is not resolved (ingress shorter than half an exposure, judged from
    the best -- density-constrained when available -- fit), in which case the
    light curve cannot constrain rho* independently and the costly profile is
    skipped. `profile_fit` is the prior-free fit to profile (default: `fit`)."""
    exposure = fit.exposure_days or 0.0
    if exposure > 0 and fit.t14_days and fit.t23_days is not None:
        ingress = 0.5 * (fit.t14_days - fit.t23_days)
        if ingress < INGRESS_RESOLUTION_FRACTION * exposure:
            return {"resolved": False, "ingress_minutes": ingress * 1440.0, "exposure_minutes": exposure * 1440.0}
    return stellar_density_profile(time, flux, profile_fit or fit, fit_config)


def _maybe_refit_from_catalog(time, flux, fit, catalog: dict, fit_config: FitConfig | None):
    """The BLS search runs on the raw (un-detrended) light curve and can lock
    onto instrumental features (e.g. Kepler quarter-to-quarter jumps). When
    the resolved KOI has a catalogue ephemeris and the BLS-seeded fit is not
    significant or disagrees with it, a second fit is seeded from the
    catalogue ephemeris. It is kept only if it is itself significant and has
    a higher SNR; the seed used is recorded in the fit result. The fitted
    values remain light-curve measurements -- the catalogue only says where
    to look. If the upload's time system differs from the catalogue's
    (BKJD), the catalogue-seeded fit finds nothing and is discarded."""
    ref = catalog.get("reference") or {}
    if not all(k in ref for k in ("orbital_period", "transit_epoch", "transit_duration", "transit_depth")):
        return fit
    cfg = fit_config or FitConfig()
    p_ref = ref["orbital_period"]["value"]
    bls_ok = fit.status == "fitted" and fit.snr is not None and fit.snr >= SNR_DETECTION_THRESHOLD \
        and abs(fit.params["period"] / p_ref - 1) < PERIOD_MATCH_TOLERANCE
    if bls_ok:
        return fit
    alt = fit_transit(time, flux, p_ref, ref["transit_epoch"]["value"], ref["transit_duration"]["value"] / 24.0,
                      ref["transit_depth"]["value"] * 1e-6, None, cfg)
    if alt.status == "fitted" and alt.snr is not None and alt.snr >= SNR_DETECTION_THRESHOLD \
            and alt.snr > (fit.snr or 0.0):
        alt.seed_source = "catalog_ephemeris"
        alt.bls = fit.bls
        alt.warnings.insert(0, (
            f"The transit search's best period ({fit.bls.get('period_days', float('nan')):.4f} d) did not yield a "
            f"significant transit fit; the fit was seeded from the KOI catalogue ephemeris (P = {p_ref:.4f} d) "
            f"instead and recovered the transit at SNR {alt.snr:.1f}. All fitted values are measured from the "
            "uploaded light curve."))
        logger.info("characterization_catalog_seeded_fit", extra={"snr_bls": fit.snr, "snr_catalog": alt.snr})
        return alt
    return fit


def validate_inputs(inputs) -> dict:
    """Minimal structural validation of a client-returned snapshot; the
    engine itself tolerates missing optional pieces."""
    if not isinstance(inputs, dict):
        raise CharacterizationInputError("inputs must be a JSON object (the report's 'inputs' snapshot).")
    if inputs.get("schema_version") != SCHEMA_VERSION:
        raise CharacterizationInputError(f"Unsupported inputs schema_version (expected {SCHEMA_VERSION}).")
    fit = inputs.get("transit_fit")
    if not isinstance(fit, dict) or "status" not in fit:
        raise CharacterizationInputError("inputs.transit_fit is missing or malformed.")
    if fit.get("status") == "fitted":
        params = fit.get("params") or {}
        for key in ("t0", "period", "k", "a_rs", "b"):
            if _num(params.get(key)) is None:
                raise CharacterizationInputError(f"inputs.transit_fit.params.{key} must be a finite number.")
        cov = fit.get("covariance")
        names = fit.get("fitted_names") or []
        if cov is not None:
            arr = np.asarray(cov, dtype=float)
            if arr.shape != (len(names), len(names)) or not np.all(np.isfinite(arr)):
                raise CharacterizationInputError("inputs.transit_fit.covariance is malformed.")
    if not isinstance(inputs.get("catalog", {}), dict):
        raise CharacterizationInputError("inputs.catalog must be an object.")
    return inputs


def inputs_cache_key(inputs: dict, overrides: dict | None, config: dict | None) -> str:
    """Content hash of everything a report depends on: any change to the
    inputs, overrides or assumptions yields a different key, so cached
    reports are invalidated automatically."""
    payload = json.dumps({"i": inputs, "o": overrides or {}, "c": config or {}}, sort_keys=True, default=str)
    return "characterization:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attach(report: dict, inputs: dict) -> dict:
    report["inputs"] = inputs
    return report


def characterize_light_curve(time: np.ndarray, flux: np.ndarray, bls, catalog_resolution=None,
                             object_id: str | None = None, overrides: dict | None = None,
                             config: dict | None = None, archive_lookup: bool = False) -> dict:
    """Single entry point for the upload pipeline. Never raises for
    scientific reasons: a failed fit or missing catalogue data produce an
    explicit status inside the report."""
    inputs = build_inputs(time, flux, bls, catalog_resolution, object_id, archive_lookup=archive_lookup)
    report = compute_report(inputs, overrides, config)
    logger.info("characterization_completed", extra={"status": report["status"], "reliability": report["reliability"]})
    return _attach(report, inputs)


def recompute_characterization(inputs: dict, overrides: dict | None = None, config: dict | None = None) -> dict:
    """Re-runs the engine on a stored snapshot (no light-curve refit).
    Raises OverrideValidationError / CharacterizationInputError for bad
    requests."""
    validate_inputs(inputs)
    normalize_overrides(overrides)          # fail fast with a clear message
    CharacterizationConfig.from_dict(config)
    return _attach(compute_report(inputs, overrides, config), inputs)
