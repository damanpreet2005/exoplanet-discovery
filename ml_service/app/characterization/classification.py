"""
Descriptive planet classifications.

These are *descriptive labels derived from computed quantities*, with the
rule and its literature basis stated next to every result. They never
assert atmospheric composition, surface conditions, habitability, or that
the candidate is a confirmed planet. Each category carries the fraction of
Monte Carlo samples that fall in it, so a radius straddling a boundary is
reported as such rather than forced into one bin.

All thresholds live in CLASSIFICATION_RULES and can be replaced via
`classify(..., rules=...)`.
"""
from __future__ import annotations

import numpy as np

from app.characterization import physics
from app.characterization.models import STATUS_COMPUTED, STATUS_UNAVAILABLE, Classification

CLASSIFICATION_RULES = {
    "size": {
        "basis": "Planet-radius bins of Borucki et al. (2011, ApJ 736, 19), as used for Kepler candidate statistics.",
        "bins": [
            (0.0, 1.25, "Earth-size"),
            (1.25, 2.0, "Super-Earth-size"),
            (2.0, 6.0, "Neptune-size"),
            (6.0, 15.0, "Jupiter-size"),
            (15.0, 22.4, "Larger than Jupiter-size"),
            (22.4, float("inf"), "Exceeds planetary radii (~2 R_Jup): likely stellar companion, blend or bad stellar radius"),
        ],
    },
    "composition": {
        "basis": "Radius-only composition candidates: most planets larger than ~1.6 R_earth are not purely rocky "
                 "(Rogers 2015, ApJ 801, 41); the radius valley near 1.5-2 R_earth separates rocky super-Earths "
                 "from volatile-rich sub-Neptunes (Fulton et al. 2017, AJ 154, 109); ~10 R_earth marks the "
                 "transition to gas giants.",
        "bins": [
            (0.0, 1.6, "Rocky / terrestrial candidate"),
            (1.6, 4.0, "Volatile-rich sub-Neptune candidate"),
            (4.0, 10.0, "Neptune-like (ice/gas giant) candidate"),
            (10.0, float("inf"), "Gas-giant candidate"),
        ],
    },
    "irradiation": {
        "basis": "Descriptive bins of incident flux relative to Earth (S_earth = 1). Not a standard taxonomy.",
        "bins": [
            (0.0, 0.3, "Low irradiation (< 0.3 S_earth)"),
            (0.3, 3.0, "Earth-like irradiation (0.3-3 S_earth)"),
            (3.0, 100.0, "High irradiation (3-100 S_earth)"),
            (100.0, float("inf"), "Very high irradiation (> 100 S_earth)"),
        ],
    },
    "thermal": {
        "basis": "Descriptive equilibrium-temperature regimes; 'ultra-hot' follows the ~2000-2200 K threshold used "
                 "for ultra-hot Jupiters (Parmentier et al. 2018). Teq is not a surface temperature.",
        "bins": [
            (0.0, 200.0, "Cold (Teq < 200 K)"),
            (200.0, 400.0, "Temperate (200-400 K)"),
            (400.0, 1000.0, "Warm (400-1000 K)"),
            (1000.0, 2000.0, "Hot (1000-2000 K)"),
            (2000.0, float("inf"), "Ultra-hot (> 2000 K)"),
        ],
    },
}

MASS_UNKNOWN_CAVEAT = (
    "Planetary mass is not measured, so bulk composition cannot be determined: planets of the same radius "
    "span a wide range of densities. This label is a radius-based candidate category only."
)


def _bin_label(value: float, bins) -> str | None:
    for lo, hi, label in bins:
        if lo <= value < hi:
            return label
    return None


def _bin_probabilities(samples: np.ndarray, bins) -> dict[str, float]:
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return {}
    probs = {}
    for lo, hi, label in bins:
        frac = float(np.mean((finite >= lo) & (finite < hi)))
        if frac >= 0.005:
            probs[label] = round(frac, 3)
    return probs


def _binned(name: str, label: str, rule: dict, value, samples, depends_on: list[str],
            caveats: list[str], missing_reason: str) -> Classification:
    if value is None or samples is None:
        return Classification(name, label, None, rule["basis"], caveats=[missing_reason],
                              depends_on=depends_on, status=STATUS_UNAVAILABLE)
    category = _bin_label(value, rule["bins"])
    probs = _bin_probabilities(samples, rule["bins"])
    return Classification(name, label, category, rule["basis"], probability=probs.get(category),
                          probabilities=probs, caveats=caveats, depends_on=depends_on, status=STATUS_COMPUTED)


def classify(values: dict, samples: dict, mass_provenance: str | None, rules: dict | None = None) -> list[Classification]:
    """`values`/`samples` are keyed by parameter name (central value and MC
    samples; None when unavailable)."""
    rules = rules or CLASSIFICATION_RULES
    rp, rp_s = values.get("planet_radius"), samples.get("planet_radius")
    s, s_s = values.get("insolation"), samples.get("insolation")
    teq, teq_s = values.get("equilibrium_temperature"), samples.get("equilibrium_temperature")

    composition_caveats = [] if mass_provenance in ("manual_override",) else [MASS_UNKNOWN_CAVEAT]
    out = [
        _binned("size_category", "Planet size category", rules["size"], rp, rp_s, ["planet_radius"],
                ["Based on radius alone; says nothing about mass or composition."],
                "Requires the planet radius, which is unavailable."),
        _binned("composition_candidate", "Radius-based composition candidate", rules["composition"], rp, rp_s,
                ["planet_radius"], composition_caveats + ["Atmospheric and interior composition are not inferred."],
                "Requires the planet radius, which is unavailable."),
        _binned("irradiation", "Relative stellar irradiation", rules["irradiation"], s, s_s, ["insolation"],
                ["Orbit-averaged incident flux; does not account for atmospheric response."],
                "Requires the stellar insolation, which is unavailable."),
        _binned("thermal_regime", "Approximate thermal regime", rules["thermal"], teq, teq_s,
                ["equilibrium_temperature"],
                ["Equilibrium temperature depends on the assumed Bond albedo and heat redistribution; it is not a "
                 "surface temperature (greenhouse warming, internal heat and clouds are not modelled)."],
                "Requires the equilibrium temperature, which is unavailable."),
        habitable_zone(values, samples),
    ]
    return out


def habitable_zone(values: dict, samples: dict) -> Classification:
    """Estimated position relative to the Kopparapu et al. (2014) habitable
    zone, from the planet's insolation and the host star's Teff. Conservative
    HZ: runaway greenhouse - maximum greenhouse; optimistic HZ: recent Venus
    - early Mars."""
    basis = ("Kopparapu et al. (2014, ApJL 787, L29) habitable-zone flux boundaries for a 1 M_earth planet, "
             "valid for 2600-7200 K host stars; compares the planet's orbit-averaged insolation with the "
             "boundary fluxes for the host star's effective temperature.")
    caveats = [
        "An estimated habitable-zone position is not evidence of habitability or of life: it ignores the "
        "planet's mass, atmosphere, composition and climate.",
        "Boundaries are model-dependent and computed for a 1 M_earth planet.",
    ]
    teff, s = values.get("stellar_teff"), values.get("insolation")
    teff_s, s_s = samples.get("stellar_teff"), samples.get("insolation")
    deps = ["insolation", "stellar_teff"]
    if teff is None or s is None:
        return Classification("habitable_zone", "Estimated habitable-zone position", None, basis,
                              caveats=["Requires the planet's insolation and the host star's effective temperature."],
                              depends_on=deps, status=STATUS_UNAVAILABLE)
    lo_t, hi_t = physics.HZ_TEFF_RANGE_K
    if not (lo_t <= teff <= hi_t):
        return Classification("habitable_zone", "Estimated habitable-zone position", None, basis,
                              caveats=[f"Host star Teff = {teff:.0f} K is outside the model's {lo_t:.0f}-{hi_t:.0f} K "
                                       "validity range."],
                              depends_on=deps, status=STATUS_UNAVAILABLE)

    def zone(s_val, t_val):
        rv = physics.hz_effective_flux(t_val, "recent_venus")
        rg = physics.hz_effective_flux(t_val, "runaway_greenhouse")
        mg = physics.hz_effective_flux(t_val, "maximum_greenhouse")
        em = physics.hz_effective_flux(t_val, "early_mars")
        return np.select(
            [s_val > rv, s_val > rg, s_val >= mg, s_val >= em, s_val < em],
            ["Interior to the habitable zone (too irradiated)", "Optimistic habitable zone (inner edge)",
             "Conservative habitable zone", "Optimistic habitable zone (outer edge)",
             "Exterior to the habitable zone (too little irradiation)"],
            default="Undetermined",
        )

    category = str(zone(np.array(s), np.array(teff)))
    probs: dict[str, float] = {}
    if s_s is not None and teff_s is not None:
        z = zone(np.asarray(s_s), np.asarray(teff_s))
        ok = np.isfinite(s_s) & np.isfinite(teff_s)
        labels, counts = np.unique(z[ok], return_counts=True)
        n_ok = int(ok.sum())
        probs = {str(lbl): round(int(c) / n_ok, 3) for lbl, c in zip(labels, counts) if int(c) / n_ok >= 0.005}
    return Classification("habitable_zone", "Estimated habitable-zone position", category, basis,
                          probability=probs.get(category), probabilities=probs or None, caveats=caveats,
                          depends_on=deps, status=STATUS_COMPUTED)
