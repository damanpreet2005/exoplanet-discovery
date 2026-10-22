"""
Dedicated feature-extraction module: turns an uploaded (time, flux) light
curve, plus the required Object ID, into a fully-classified report of the
model's 17 real KOI features (see app/feature_aliases.py's
MODEL_FEATURE_ORDER). This is the "FEATURE ENGINE" + "stellar catalog
service" combination from the project's target architecture -- catalog
lookup logic itself lives in app/stellar_catalog_service.py and is never
mixed into this module's feature-building or into the RF/CNN prediction
code in app/predictor.py.

For every one of the 17 features, `extract_features` returns a `FeatureValue`
carrying:
  - value:  the number itself, or None if it could not legitimately be
            produced.
  - source: what produced it (e.g. "box_least_squares", "nasa_koi_catalog",
            "derived_equilibrium_temperature", "structural_default").
  - status: one of "estimated" (measured from the light curve), "derived"
            (computed from other estimated/catalog values via a documented
            formula), "catalog" (looked up in the local NASA Exoplanet Archive KOI catalogue),
            or "unavailable" (deliberately not fabricated).
  - note:   a short, human-readable explanation of exactly how the value was
            produced, or exactly why it wasn't.

Nothing in this module invents a value merely to fill a slot -- every
"unavailable" stays unavailable, and the caller (routers/predict_csv.py)
only runs the trained model once every one of the 17 features has a real
value.
"""
import logging
import math
from dataclasses import dataclass, field

import numpy as np

from app.astrophysics import (
    equilibrium_temperature_k,
    insolation_earth_flux,
    planet_radius_earth,
    semi_major_axis_au,
    stellar_mass_from_logg_radius,
)
from app.feature_aliases import FEATURE_DEFINITIONS, MODEL_FEATURE_ORDER
from app.lightcurve_extraction import (
    LightCurveExtraction,
    compute_feature_vector,
)
from app.stellar_catalog_service import CatalogResolution, KOI_LEVEL_FIELDS, resolve_object_id

logger = logging.getLogger("ml_service")

FEATURE_UNITS: dict[str, str] = {d["canonical"]: d["unit"] for d in FEATURE_DEFINITIONS}

STATUS_ESTIMATED = "estimated"
STATUS_DERIVED = "derived"
STATUS_CATALOG = "catalog"
STATUS_UNAVAILABLE = "unavailable"


@dataclass
class FeatureValue:
    value: float | None
    unit: str
    source: str
    status: str
    note: str


@dataclass
class FeatureExtractionResult:
    features: dict[str, FeatureValue]           # keyed by canonical name, ordered per MODEL_FEATURE_ORDER
    extraction: LightCurveExtraction             # unchanged existing BLS/vetting-stats result
    catalog: CatalogResolution
    missing_features: list[str]
    ready_for_prediction: bool
    warnings: list[str] = field(default_factory=list)


PERIOD_MATCH_TOLERANCE = 0.01


def _catalog_koi_value(catalog: CatalogResolution, column: str, period_days: float) -> float | None:
    """A KOI-level catalogue column for the KOI this light curve's transit
    belongs to: the single matched KOI, or -- for a star with several KOIs --
    the one whose catalogue period matches the light-curve period within 1%."""
    rows = list(catalog.matched_rows or [])
    if len(rows) > 1:
        rows = [r for r in rows if _finite(r.get("koi_period")) and period_days
                and abs(float(r["koi_period"]) / period_days - 1) < PERIOD_MATCH_TOLERANCE]
    if len(rows) != 1 or catalog.match_status not in ("matched_koi", "matched_star"):
        return None
    raw = rows[0].get(column)
    return float(raw) if _finite(raw) else None


def _finite(raw) -> bool:
    try:
        return math.isfinite(float(raw))
    except (TypeError, ValueError):
        return False


def apply_fitted_impact_parameter(result: "FeatureExtractionResult", report: dict | None) -> None:
    """Fills an unavailable koi_impact from the characterization engine's
    transit fit, but only when that fit used the catalogue stellar-density
    prior and the engine rates the fitted b as reliable -- never a guess.
    Updates `missing_features` / `ready_for_prediction` accordingly."""
    if result.features["koi_impact"].status != STATUS_UNAVAILABLE or not report:
        return
    b = (report.get("parameters") or {}).get("impact_parameter") or {}
    fit = report.get("transit_fit") or {}
    prior_used = bool(((report.get("inputs") or {}).get("transit_fit") or {}).get("stellar_density_prior"))
    if b.get("status") != "computed" or b.get("reliability") != "reliable" or b.get("provenance") != "fitted" \
            or not prior_used or fit.get("status") != "fitted":
        return
    result.features["koi_impact"] = FeatureValue(
        b["value"], FEATURE_UNITS.get("koi_impact", ""), "transit_model_fit", STATUS_ESTIMATED,
        f"Limb-darkened transit-model fit of the uploaded light curve with the catalogue stellar density as a "
        f"prior on a/R* (b = {b['display']}).",
    )
    result.missing_features = [c for c, fv in result.features.items() if fv.status == STATUS_UNAVAILABLE]
    result.ready_for_prediction = not result.missing_features


def _unavailable_reason(catalog: CatalogResolution, canonical: str) -> str:
    if catalog.match_status in ("not_provided", "not_found", "unsupported_identifier_type", "lookup_error"):
        return catalog.note
    if catalog.match_status == "matched_star" and canonical in KOI_LEVEL_FIELDS:
        return catalog.note
    return (
        f"The matched catalog record does not have a recorded value for {canonical} "
        "(the NASA KOI table itself has this field blank for some entries)."
    )


def _target_description(catalog: CatalogResolution) -> str:
    return catalog.matched_kepler_name or catalog.matched_kepoi_name or (
        f"KIC {catalog.matched_kepid}" if catalog.matched_kepid else "the requested target"
    )


def extract_features(time: np.ndarray, flux: np.ndarray, object_id: str | None = None) -> FeatureExtractionResult:
    logger.info("object_id_received", extra={"has_object_id": bool(object_id and object_id.strip())})

    extraction = compute_feature_vector(time, flux)  # existing, unmodified BLS + vetting-stats pipeline
    bls = extraction.bls

    logger.info("catalog_lookup_started")
    catalog = resolve_object_id(object_id)
    logger.info(
        "catalog_lookup_finished",
        extra={"match_status": catalog.match_status, "identifier_type": catalog.identifier_type},
    )

    features: dict[str, FeatureValue] = {}

    def unit(canonical: str) -> str:
        return FEATURE_UNITS.get(canonical, "")

    # ---- A. directly from the light curve (Box Least Squares) -------------
    features["koi_period"] = FeatureValue(
        bls.period_days, unit("koi_period"), "box_least_squares", STATUS_ESTIMATED,
        "Best-fit orbital period from a Box Least Squares transit search over the uploaded light curve.",
    )
    features["koi_time0bk"] = FeatureValue(
        bls.transit_epoch, unit("koi_time0bk"), "box_least_squares", STATUS_ESTIMATED,
        "BLS best-fit reference transit time, in the same time convention as the uploaded 'time' "
        "column -- no BJD/Kepler-offset (2454833) conversion is applied, since the upload's time "
        "system is not independently confirmed.",
    )
    features["koi_duration"] = FeatureValue(
        bls.duration_hours, unit("koi_duration"), "box_least_squares", STATUS_ESTIMATED,
        "BLS best-fit transit duration, converted from days to hours.",
    )
    features["koi_depth"] = FeatureValue(
        bls.depth_ppm, unit("koi_depth"), "box_least_squares", STATUS_ESTIMATED,
        "BLS best-fit transit depth, converted from a flux fraction to parts per million.",
    )
    # Same definition family as the KOI table's koi_model_snr (transit depth
    # over the flux uncertainty, combined over the observed transits).
    if bls.snr is not None:
        features["koi_model_snr"] = FeatureValue(
            bls.snr, unit("koi_model_snr"), "box_least_squares", STATUS_ESTIMATED,
            f"BLS box-depth SNR, all transits combined: depth / (sigma sqrt(1/N_in + 1/N_out)) with "
            f"N_in = {bls.n_in_transit} in-transit points and sigma = {bls.noise_ppm:.0f} ppm (robust "
            "point-to-point scatter). Assumes white noise.",
        )
    else:
        features["koi_model_snr"] = FeatureValue(
            None, unit("koi_model_snr"), "box_least_squares", STATUS_UNAVAILABLE,
            "The per-point photometric noise could not be estimated from this light curve (e.g. constant or "
            "quantised flux), so a signal-to-noise ratio is undefined.",
        )

    # ---- A (potentially). impact parameter ---------------------------------
    # KOI catalogue value (NASA's own transit-model fit of the full Kepler
    # data) when the Object ID matched this KOI; otherwise unavailable here,
    # and routers/predict_csv.py fills it from the characterization engine's
    # density-constrained, limb-darkened transit fit when that rates b as
    # reliable (apply_fitted_impact_parameter). The trapezoid shape estimate
    # (estimate_impact_parameter) is no longer used: it assumes no limb
    # darkening, so on real (limb-darkened) stars the curved transit bottom
    # makes T23 too short and drives b towards 1 -- it reported b = 0.96 for
    # Kepler-227 b (catalogue b = 0.146).
    catalog_impact = _catalog_koi_value(catalog, "koi_impact", bls.period_days)
    if catalog_impact is not None:
        features["koi_impact"] = FeatureValue(
            catalog_impact, unit("koi_impact"), "nasa_koi_catalog", STATUS_CATALOG,
            f"KOI catalogue impact parameter for {_target_description(catalog)} (NASA transit-model fit of the "
            "full Kepler light curve); preferred over a shape estimate from the uploaded light curve, which "
            "cannot resolve the ingress of small planets at long cadence.",
        )
    else:
        features["koi_impact"] = FeatureValue(
            None, unit("koi_impact"), "transit_model_fit", STATUS_UNAVAILABLE,
            "No KOI catalogue impact parameter for this target, and the light curve's transit shape alone does "
            "not constrain it without a stellar-density prior (b is degenerate with a/R*).",
        )

    # ---- D. catalog/TCE-specific fields ------------------------------------
    if catalog.field_available.get("koi_tce_plnt_num"):
        features["koi_tce_plnt_num"] = FeatureValue(
            catalog.fields["koi_tce_plnt_num"], unit("koi_tce_plnt_num"), "nasa_koi_catalog", STATUS_CATALOG,
            f"Catalog TCE planet number for {_target_description(catalog)}.",
        )
    else:
        features["koi_tce_plnt_num"] = FeatureValue(
            1.0, unit("koi_tce_plnt_num"), "structural_default", STATUS_DERIVED,
            "This pipeline characterizes one transit signal per light curve, so it is treated as "
            "the first/only planet candidate for the target (matching the KOI catalog's convention "
            "of numbering a target's first detected candidate 1). Supply a KOI/Kepler-name "
            "identifier to resolve the catalog's actual TCE planet number instead.",
        )

    if catalog.field_available.get("koi_score"):
        features["koi_score"] = FeatureValue(
            catalog.fields["koi_score"], unit("koi_score"), "nasa_koi_catalog", STATUS_CATALOG,
            "NASA Robovetter disposition score for this KOI -- a meta-output of NASA's own "
            "automated vetting pipeline, not a quantity a light curve alone can reproduce.",
        )
    else:
        features["koi_score"] = FeatureValue(
            None, unit("koi_score"), "nasa_koi_catalog", STATUS_UNAVAILABLE,
            _unavailable_reason(catalog, "koi_score"),
        )

    # ---- C. stellar/catalog metadata ---------------------------------------
    for canonical in ("koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag"):
        if catalog.field_available.get(canonical):
            features[canonical] = FeatureValue(
                catalog.fields[canonical], unit(canonical), "nasa_koi_catalog", STATUS_CATALOG,
                f"Resolved from the local NASA Exoplanet Archive KOI catalogue for {_target_description(catalog)}.",
            )
        else:
            features[canonical] = FeatureValue(
                None, unit(canonical), "nasa_koi_catalog", STATUS_UNAVAILABLE,
                _unavailable_reason(catalog, canonical),
            )

    # ---- B. indirectly derived from transit + stellar parameters ----------
    srad = features["koi_srad"].value
    steff = features["koi_steff"].value
    slogg = features["koi_slogg"].value
    depth_fraction = bls.depth_fraction
    period_days = bls.period_days

    if srad is not None:
        rp = planet_radius_earth(depth_fraction, srad)
        if rp is not None:
            features["koi_prad"] = FeatureValue(
                rp, unit("koi_prad"), "derived_rp_eq_rstar_sqrt_depth", STATUS_DERIVED,
                "Rp = Rstar * sqrt(transit depth), with Rstar from the resolved catalog stellar radius.",
            )
        else:
            features["koi_prad"] = FeatureValue(
                None, unit("koi_prad"), "derived_rp_eq_rstar_sqrt_depth", STATUS_UNAVAILABLE,
                "The measured transit depth was not usable (non-positive) for a radius calculation.",
            )
    else:
        features["koi_prad"] = FeatureValue(
            None, unit("koi_prad"), "derived_rp_eq_rstar_sqrt_depth", STATUS_UNAVAILABLE,
            "Requires stellar radius (koi_srad): " + _unavailable_reason(catalog, "koi_srad"),
        )

    if steff is not None and slogg is not None and srad is not None:
        mass_solar = stellar_mass_from_logg_radius(slogg, srad)
        a_au = semi_major_axis_au(period_days, mass_solar) if mass_solar is not None else None
        if a_au is not None:
            teq = equilibrium_temperature_k(steff, srad, a_au)
            insol = insolation_earth_flux(steff, srad, a_au)
            teq_note = (
                "Teq = Steff * sqrt(Rstar / (2a)), assuming zero albedo and full heat "
                "redistribution; a (semi-major axis) from Kepler's third law using a stellar "
                "mass derived from the catalog's log g and radius."
            )
            insol_note = (
                "S = (Rstar/Rsun)^2 * (Steff/Tsun)^4 / (a/AU)^2, with a from Kepler's third law."
            )
            features["koi_teq"] = FeatureValue(
                teq, unit("koi_teq"), "derived_equilibrium_temperature",
                STATUS_DERIVED if teq is not None else STATUS_UNAVAILABLE, teq_note,
            )
            features["koi_insol"] = FeatureValue(
                insol, unit("koi_insol"), "derived_insolation",
                STATUS_DERIVED if insol is not None else STATUS_UNAVAILABLE, insol_note,
            )
        else:
            reason = "Stellar mass or semi-major axis could not be computed from the resolved catalog values."
            features["koi_teq"] = FeatureValue(None, unit("koi_teq"), "derived_equilibrium_temperature", STATUS_UNAVAILABLE, reason)
            features["koi_insol"] = FeatureValue(None, unit("koi_insol"), "derived_insolation", STATUS_UNAVAILABLE, reason)
    else:
        missing_inputs = [
            name for name, val in (("koi_steff", steff), ("koi_slogg", slogg), ("koi_srad", srad)) if val is None
        ]
        reason = f"Requires stellar temperature, surface gravity, and radius; unavailable: {', '.join(missing_inputs)}."
        features["koi_teq"] = FeatureValue(None, unit("koi_teq"), "derived_equilibrium_temperature", STATUS_UNAVAILABLE, reason)
        features["koi_insol"] = FeatureValue(None, unit("koi_insol"), "derived_insolation", STATUS_UNAVAILABLE, reason)

    ordered_features = {canonical: features[canonical] for canonical in MODEL_FEATURE_ORDER}
    warnings = _run_sanity_checks(ordered_features, bls, period_days)
    missing = [c for c, fv in ordered_features.items() if fv.status == STATUS_UNAVAILABLE]

    n_estimated = sum(1 for fv in ordered_features.values() if fv.status == STATUS_ESTIMATED)
    n_catalog = sum(1 for fv in ordered_features.values() if fv.status == STATUS_CATALOG)
    n_derived = sum(1 for fv in ordered_features.values() if fv.status == STATUS_DERIVED)
    logger.info(
        "feature_vector_constructed",
        extra={
            "n_light_curve_features": n_estimated,
            "n_stellar_parameters_retrieved": n_catalog,
            "n_derived_features": n_derived,
            "n_unavailable": len(missing),
            "ready_for_prediction": len(missing) == 0,
        },
    )

    return FeatureExtractionResult(
        features=ordered_features,
        extraction=extraction,
        catalog=catalog,
        missing_features=missing,
        ready_for_prediction=len(missing) == 0,
        warnings=warnings,
    )


def _run_sanity_checks(features: dict[str, FeatureValue], bls, period_days: float) -> list[str]:
    """Scientific validation (task-mandated): flags implausible results
    rather than silently passing them through. Never blocks/mutates a
    value -- only annotates the response with human-readable warnings."""
    warnings: list[str] = []

    for canonical, fv in features.items():
        if fv.value is not None and not math.isfinite(fv.value):
            warnings.append(f"{canonical} computed a non-finite value; treat this prediction with caution.")

    if bls.period_days <= 0:
        warnings.append("BLS period is not positive.")
    if bls.duration_hours <= 0:
        warnings.append("BLS duration is not positive.")
    if bls.depth_fraction < 0:
        warnings.append("BLS depth is negative.")

    duration_days = bls.duration_hours / 24.0
    if period_days > 0 and duration_days / period_days > 0.5:
        warnings.append(
            "Transit duration is more than half the orbital period, which is physically "
            "implausible for a real planetary transit -- the BLS fit may have locked onto noise."
        )

    impact_fv = features.get("koi_impact")
    if impact_fv and impact_fv.value is not None and not (0.0 <= impact_fv.value <= 1.5):
        warnings.append(f"Estimated impact parameter ({impact_fv.value:.2f}) is outside the plausible [0, 1.5] range.")

    teq_fv = features.get("koi_teq")
    if teq_fv and teq_fv.value is not None and not (10.0 <= teq_fv.value <= 6000.0):
        warnings.append(f"Derived equilibrium temperature ({teq_fv.value:.0f} K) is outside a plausible planetary range.")

    prad_fv = features.get("koi_prad")
    if prad_fv and prad_fv.value is not None and not (0.05 <= prad_fv.value <= 30.0):
        warnings.append(f"Derived planet radius ({prad_fv.value:.2f} Earth radii) is outside a plausible range.")

    return warnings
