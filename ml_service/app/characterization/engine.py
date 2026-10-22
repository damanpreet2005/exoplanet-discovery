"""
Characterization engine: turns a characterization *input snapshot* (transit
fit + catalogue values, see planet_characterization.build_inputs) plus
optional expert overrides into a full, provenance-tracked report.

This stage is cheap (vectorised Monte Carlo, no fitting), so it can be
re-run synchronously whenever an override or assumption changes; the
expensive light-curve fit happens once, upstream, in transit_fit.py.

DEPENDENCY GRAPH
Parameters are computed in a fixed topological order (`_NODE_ORDER`). Each
derived parameter records the parameters it was actually computed from
(`depends_on`). An expert override replaces a node's value and cuts its
upstream edges; values never propagate *backwards* (overriding the planet
radius does not change the stellar radius), so the graph stays acyclic by
construction -- checked at import time by `_assert_acyclic`.

RELIABILITY
`status` says whether a calculation ran; `reliability` says whether its
result should be interpreted. A parameter is only as reliable as its least
reliable input, and is downgraded further by its own validity checks (e.g.
a grazing transit makes the radius ratio poorly constrained).
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np

from app.characterization import physics
from app.characterization.classification import classify
from app.characterization.models import (
    ASSUMED, CATALOG, DERIVED, EVIDENCE_BY_PROVENANCE, FITTED, LOW, MANUAL_OVERRIDE, MEASURED, MODEL_ESTIMATED,
    NOT_ASSESSED, OBSERVED, RELIABLE,
    STATUS_COMPUTED, STATUS_UNAVAILABLE, UNAVAILABLE, UNRELIABLE, Parameter, Uncertainty, unavailable,
    worst_reliability,
)
from app.characterization.transit_model import central_depth
from app.characterization.uncertainty import (
    analytic_power_law, format_measurement, log10_sigma, multivariate_normal, split_normal, summarize,
    symmetric_sigma,
)

ENGINE_VERSION = "1.0.0"
SCHEMA_VERSION = 1


class OverrideValidationError(ValueError):
    """An expert override (or config value) is malformed or unphysical."""


@dataclass
class CharacterizationConfig:
    bond_albedo: float = 0.3                 # NASA KOI koi_teq convention
    heat_redistribution: str = "full"        # "full" (f = 1/4) | "dayside" (f = 2/3)
    mc_samples: int = 4000
    random_seed: int = 20240601
    snr_detection_threshold: float = 7.1     # Kepler pipeline multiple-event-statistic threshold
    low_confidence_relative_uncertainty: float = 0.3
    tension_sigma: float = 3.0

    @classmethod
    def from_dict(cls, data: dict | None) -> "CharacterizationConfig":
        cfg = cls()
        for key, value in (data or {}).items():
            if not hasattr(cfg, key):
                raise OverrideValidationError(f"Unknown configuration option '{key}'.")
            setattr(cfg, key, value)
        if not isinstance(cfg.bond_albedo, (int, float)) or isinstance(cfg.bond_albedo, bool) \
                or not (0.0 <= float(cfg.bond_albedo) < 1.0):
            raise OverrideValidationError("bond_albedo must be a number in [0, 1).")
        if cfg.heat_redistribution not in physics.HEAT_REDISTRIBUTION_FACTORS:
            raise OverrideValidationError(
                f"heat_redistribution must be one of {sorted(physics.HEAT_REDISTRIBUTION_FACTORS)}.")
        if not isinstance(cfg.mc_samples, int) or not (500 <= cfg.mc_samples <= 50000):
            raise OverrideValidationError("mc_samples must be an integer in [500, 50000].")
        cfg.bond_albedo = float(cfg.bond_albedo)
        return cfg


# ---- assumptions -----------------------------------------------------------

# The light curve resolves the transit shape only when the ingress lasts at
# least this fraction of one exposure (otherwise b and a/R* are degenerate).
INGRESS_RESOLUTION_FRACTION = 0.5

# Quantities on a logarithmic scale: the relative-uncertainty rule does not apply.
LOG_SCALE_PARAMETERS = {"stellar_logg", "stellar_metallicity"}


def assumption_texts(cfg: CharacterizationConfig) -> dict[str, str]:
    f = physics.HEAT_REDISTRIBUTION_FACTORS[cfg.heat_redistribution]
    return {
        "circular_orbit": "Circular orbit (e = 0) unless an eccentricity is supplied by expert override. Transit "
                          "photometry alone does not constrain eccentricity, so this is an assumption, not a result.",
        "limb_darkening_fixed": "Quadratic limb darkening fixed at u1 = 0.40, u2 = 0.26 (representative Kepler-band "
                                "values for a Sun-like dwarf); not fitted.",
        "no_dilution": "No third-light dilution: the measured depth is assumed to come from the target star alone.",
        "negligible_planet_mass": "Planet mass neglected in Kepler's third law unless a measured mass is supplied.",
        "stellar_density_prior": "The transit fit uses the catalogue stellar density (from log g and R*) as a "
                                 "Gaussian prior on a/R*, which breaks the impact-parameter / a/R* degeneracy. This "
                                 "assumes a circular orbit and accurate catalogue stellar parameters; the prior-free "
                                 "fit is kept for the transit-vs-catalogue density check.",
        "bond_albedo": f"Bond albedo A = {cfg.bond_albedo:g} (assumed; the NASA KOI table convention is 0.3). "
                       "Albedo is not measured from the light curve.",
        "heat_redistribution": f"Heat redistribution '{cfg.heat_redistribution}' (f = {f:.3g} in "
                               "Teq = Teff sqrt(R*/a) [f(1-A)]^1/4).",
        "blackbody": "Star and planet radiate as blackbodies; no internal heat or greenhouse effect.",
        "time_in_days": "The uploaded time column is in days; no barycentric correction or BJD offset is applied.",
        "white_noise_empirical": "Photometric uncertainties estimated empirically from out-of-transit point-to-point "
                                 "scatter, inflated by the measured red-noise factor.",
        "ck17_mass_radius": "Planet mass estimated from radius with the Chen & Kipping (2017) empirical mass-radius "
                            "relation, including its intrinsic scatter. An estimate, not a measurement.",
        "catalog_stellar_parameters": "Stellar Teff, log g and radius from the local NASA Exoplanet Archive KOI "
                                      "cumulative table (Kepler DR25 stellar properties).",
        "kopparapu_hz": "Habitable-zone boundaries from Kopparapu et al. (2014) for a 1 M_earth planet.",
        "fit_covariance_gaussian": "Transit-fit uncertainties from the linearised covariance at the best fit "
                                   "(Gaussian approximation), sampled with physical bounds enforced.",
    }


# ---- parameter metadata ----------------------------------------------------

PARAM_META: dict[str, tuple[str, str]] = {
    "orbital_period": ("Orbital period", "days"),
    "transit_epoch": ("Transit epoch (mid-transit time)", "days (uploaded time system)"),
    "transit_duration": ("Transit duration (T14)", "hours"),
    "transit_duration_full": ("Full-depth duration (T23)", "hours"),
    "ingress_duration": ("Ingress/egress duration", "minutes"),
    "transit_depth": ("Transit depth (model, mid-transit)", "ppm"),
    "transit_depth_bls": ("Transit depth (BLS box)", "ppm"),
    "impact_parameter": ("Impact parameter", ""),
    "transit_snr": ("Transit signal-to-noise ratio", ""),
    "radius_ratio": ("Radius ratio (Rp/R*)", ""),
    "a_over_rstar": ("Scaled semi-major axis (a/R*)", ""),
    "planet_radius": ("Planet radius", "R⊕"),
    "planet_mass": ("Planet mass", "M⊕"),
    "planet_density": ("Planet bulk density", "g/cm³"),
    "planet_surface_gravity": ("Surface gravity", "m/s²"),
    "escape_velocity": ("Escape velocity", "km/s"),
    "semi_major_axis": ("Semi-major axis", "AU"),
    "inclination": ("Orbital inclination", "deg"),
    "orbital_velocity": ("Mean orbital velocity", "km/s"),
    "eccentricity": ("Eccentricity", ""),
    "arg_periastron": ("Argument of periastron", "deg"),
    "equilibrium_temperature": ("Equilibrium temperature", "K"),
    "insolation": ("Stellar insolation", "S⊕"),
    "hz_inner_conservative": ("HZ inner edge (conservative)", "AU"),
    "hz_outer_conservative": ("HZ outer edge (conservative)", "AU"),
    "hz_inner_optimistic": ("HZ inner edge (optimistic)", "AU"),
    "hz_outer_optimistic": ("HZ outer edge (optimistic)", "AU"),
    "stellar_teff": ("Effective temperature", "K"),
    "stellar_logg": ("Surface gravity (log g)", "log10(cm/s²)"),
    "stellar_radius": ("Stellar radius", "R☉"),
    "stellar_mass": ("Stellar mass", "M☉"),
    "stellar_luminosity": ("Stellar luminosity", "L☉"),
    "stellar_density": ("Stellar density (from M*, R*)", "g/cm³"),
    "stellar_density_transit": ("Stellar density (transit-derived)", "g/cm³"),
    "stellar_metallicity": ("Metallicity [Fe/H]", "dex"),
    "distance": ("Distance", "pc"),
    "ra": ("Right ascension", "deg"),
    "dec": ("Declination", "deg"),
    "kepmag": ("Kepler magnitude", "mag"),
}

SECTIONS = [
    {"id": "transit_signal", "title": "Transit Signal",
     "parameters": ["orbital_period", "transit_epoch", "transit_duration", "transit_depth", "impact_parameter",
                    "transit_snr"],
     "details": ["transit_duration_full", "ingress_duration", "transit_depth_bls"]},
    {"id": "planet", "title": "Planet",
     "parameters": ["planet_radius", "radius_ratio", "planet_mass", "planet_density", "planet_surface_gravity",
                    "escape_velocity"], "details": []},
    {"id": "orbit", "title": "Orbit",
     "parameters": ["semi_major_axis", "inclination", "orbital_period", "orbital_velocity", "eccentricity"],
     "details": ["a_over_rstar", "arg_periastron"]},
    {"id": "thermal", "title": "Thermal Environment",
     "parameters": ["equilibrium_temperature", "insolation"],
     "details": ["hz_inner_conservative", "hz_outer_conservative", "hz_inner_optimistic", "hz_outer_optimistic"]},
    {"id": "host_star", "title": "Host Star",
     "parameters": ["stellar_radius", "stellar_mass", "stellar_teff", "stellar_luminosity", "stellar_logg",
                    "stellar_density", "stellar_metallicity"],
     "details": ["stellar_density_transit", "distance", "ra", "dec", "kepmag"]},
]

# Overridable parameters with their physical validity ranges (inclusive lo,
# exclusive hi where noted in the message).
OVERRIDABLE: dict[str, tuple[float, float]] = {
    "orbital_period": (1e-3, 1e6),
    "transit_epoch": (-1e8, 1e8),
    "transit_duration": (1e-3, 2000.0),
    "transit_depth": (1e-3, 1e6),
    "impact_parameter": (0.0, 2.0),
    "radius_ratio": (1e-4, 1.0),
    "a_over_rstar": (1.0, 1e5),
    "stellar_radius": (0.05, 2000.0),
    "stellar_teff": (1000.0, 100000.0),
    "stellar_logg": (-1.0, 9.0),
    "stellar_mass": (0.05, 300.0),
    "stellar_metallicity": (-5.0, 1.5),
    "stellar_luminosity": (1e-6, 1e8),
    "distance": (1e-3, 1e6),
    "planet_radius": (0.01, 200.0),
    "planet_mass": (1e-4, 1e5),
    "eccentricity": (0.0, 0.99),
    "arg_periastron": (0.0, 360.0),
    "semi_major_axis": (1e-5, 1e5),
    "equilibrium_temperature": (1.0, 1e5),
    "insolation": (1e-8, 1e9),
}

# The 17-feature manual form uses KOI column names; these map onto engine
# parameters (units already match: days, hours, ppm, R_earth, K, S_earth,
# R_sun, log cgs).
MODEL_FEATURE_TO_PARAMETER = {
    "koi_period": "orbital_period", "koi_time0bk": "transit_epoch", "koi_duration": "transit_duration",
    "koi_depth": "transit_depth", "koi_impact": "impact_parameter", "koi_prad": "planet_radius",
    "koi_teq": "equilibrium_temperature", "koi_insol": "insolation", "koi_srad": "stellar_radius",
    "koi_steff": "stellar_teff", "koi_slogg": "stellar_logg",
}

# Static dependency graph (all possible upstream edges). Used for the
# acyclicity check and to explain what an override will affect; the edges
# actually used for a given report are recorded per parameter.
DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "stellar_mass": ["stellar_logg", "stellar_radius"],
    "stellar_luminosity": ["stellar_radius", "stellar_teff"],
    "stellar_density": ["stellar_mass", "stellar_radius"],
    "a_over_rstar": ["eccentricity", "arg_periastron"],
    "transit_depth": ["radius_ratio", "impact_parameter"],
    "transit_duration": ["orbital_period", "radius_ratio", "a_over_rstar", "impact_parameter"],
    "transit_duration_full": ["orbital_period", "radius_ratio", "a_over_rstar", "impact_parameter"],
    "ingress_duration": ["transit_duration", "transit_duration_full"],
    "planet_radius": ["radius_ratio", "stellar_radius"],
    "semi_major_axis": ["orbital_period", "stellar_mass", "planet_mass", "a_over_rstar", "stellar_radius"],
    "inclination": ["impact_parameter", "a_over_rstar", "eccentricity", "arg_periastron"],
    "stellar_density_transit": ["orbital_period", "a_over_rstar"],
    "insolation": ["stellar_luminosity", "semi_major_axis", "eccentricity"],
    "equilibrium_temperature": ["stellar_teff", "stellar_radius", "semi_major_axis", "eccentricity"],
    "orbital_velocity": ["semi_major_axis", "orbital_period"],
    "planet_mass": ["planet_radius"],
    "planet_density": ["planet_mass", "planet_radius"],
    "planet_surface_gravity": ["planet_mass", "planet_radius"],
    "escape_velocity": ["planet_mass", "planet_radius"],
    "hz_inner_conservative": ["stellar_teff", "stellar_luminosity"],
    "hz_outer_conservative": ["stellar_teff", "stellar_luminosity"],
    "hz_inner_optimistic": ["stellar_teff", "stellar_luminosity"],
    "hz_outer_optimistic": ["stellar_teff", "stellar_luminosity"],
}


def _assert_acyclic(graph: dict[str, list[str]]) -> None:
    state: dict[str, int] = {}

    def visit(node: str, path: tuple[str, ...]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            raise RuntimeError(f"Circular parameter dependency: {' -> '.join(path + (node,))}")
        state[node] = 1
        for dep in graph.get(node, []):
            visit(dep, path + (node,))
        state[node] = 2

    for n in graph:
        visit(n, ())


_assert_acyclic(DEPENDENCY_GRAPH)


def downstream_of(names: set[str]) -> set[str]:
    """Every parameter that (transitively) can depend on any of `names`."""
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node, deps in DEPENDENCY_GRAPH.items():
            if node not in out and (set(deps) & (names | out)):
                out.add(node)
                changed = True
    return out


# ---- override validation ---------------------------------------------------

def normalize_overrides(raw: dict | None) -> dict[str, dict]:
    """Validates expert overrides. Accepted forms per parameter:
    a bare number, or {"value": x, "uncertainty": s} or
    {"value": x, "err_plus": a, "err_minus": b}. Unknown names, non-finite
    or out-of-range values raise OverrideValidationError."""
    out: dict[str, dict] = {}
    for name, spec in (raw or {}).items():
        if name not in OVERRIDABLE:
            raise OverrideValidationError(
                f"'{name}' cannot be overridden. Overridable parameters: {', '.join(sorted(OVERRIDABLE))}.")
        if isinstance(spec, dict):
            value = spec.get("value")
            ep = spec.get("err_plus", spec.get("uncertainty"))
            em = spec.get("err_minus", spec.get("uncertainty"))
            note = str(spec.get("note", ""))[:300]
        else:
            value, ep, em, note = spec, None, None, ""
        try:
            value = float(value)
            ep = None if ep is None else abs(float(ep))
            em = None if em is None else abs(float(em))
        except (TypeError, ValueError):
            raise OverrideValidationError(f"Override for '{name}' must be numeric.") from None
        if isinstance(spec, bool) or not math.isfinite(value) or any(e is not None and not math.isfinite(e) for e in (ep, em)):
            raise OverrideValidationError(f"Override for '{name}' must be a finite number.")
        lo, hi = OVERRIDABLE[name]
        if not (lo <= value <= hi) or (name in ("eccentricity", "arg_periastron") and value >= hi):
            raise OverrideValidationError(f"Override for '{name}' = {value:g} is outside the physical range [{lo:g}, {hi:g}).")
        out[name] = {"value": value, "err_plus": ep, "err_minus": em, "note": note}
    return out


def overrides_from_model_features(submitted: dict, automatic: dict) -> dict[str, dict]:
    """Converts edits made in the 17-feature Expert Override form into engine
    overrides: only fields whose submitted value differs from the
    automatically resolved one (or that had no automatic value) count."""
    out = {}
    for feature, param in MODEL_FEATURE_TO_PARAMETER.items():
        if feature not in submitted or submitted[feature] is None:
            continue
        try:
            new = float(submitted[feature])
        except (TypeError, ValueError):
            continue
        auto = automatic.get(feature)
        if auto is None or not math.isclose(new, float(auto), rel_tol=1e-9, abs_tol=1e-12):
            out[param] = {"value": new, "note": f"Edited in the model-parameter form ({feature})."}
    return out


# ---- engine ----------------------------------------------------------------

class _Engine:
    def __init__(self, inputs: dict, overrides: dict[str, dict], cfg: CharacterizationConfig):
        self.inputs = inputs
        self.cfg = cfg
        self.n = cfg.mc_samples
        self.rng = np.random.default_rng(cfg.random_seed)
        self.overrides = overrides
        self.params: dict[str, Parameter] = {}
        self.samples: dict[str, np.ndarray | None] = {}
        self.fixed: dict[str, set[str]] = {}      # inputs held fixed (no uncertainty) upstream of each param
        # Parameters downgraded *only* because their interval is wide. That
        # width is already propagated numerically, so dependents must not
        # inherit the downgrade as well (it would double-count).
        self.wide_only: set[str] = set()
        self.warnings: list[str] = []
        self.checks: list[dict] = []
        self.fit = inputs.get("transit_fit") or {}
        self.fit_ok = self.fit.get("status") == "fitted"
        self.ld = self.fit.get("limb_darkening") or {"u1": 0.40, "u2": 0.26}
        snr = self.fit.get("snr")
        self.fit_reliability = RELIABLE
        self.fit_reason = ""
        if self.fit_ok and (snr is None or snr < cfg.snr_detection_threshold):
            self.fit_reliability = UNRELIABLE
            self.fit_reason = (f"Transit SNR {snr:.1f} is below the {cfg.snr_detection_threshold} detection threshold; "
                               "the signal is not significant." if snr is not None else "Transit SNR unavailable.")

    # -- helpers -----------------------------------------------------------
    def _meta(self, name):
        return PARAM_META[name]

    def _put(self, p: Parameter, samples: np.ndarray | None, fixed: set[str]):
        if not p.evidence:
            p.evidence = EVIDENCE_BY_PROVENANCE.get(p.provenance, p.provenance)
        self.params[p.name] = p
        self.samples[p.name] = samples
        self.fixed[p.name] = fixed

    def _unavailable(self, name: str, reason: str, missing=None, depends_on=None):
        label, unit = self._meta(name)
        self._put(unavailable(name, label, unit, reason, missing, depends_on), None, set())

    def _value(self, name):
        p = self.params.get(name)
        return None if p is None or p.status != STATUS_COMPUTED else p.value

    def _ok(self, name) -> bool:
        p = self.params.get(name)
        return p is not None and p.status == STATUS_COMPUTED and p.value is not None

    def _input(self, name, value, provenance, err_plus=None, err_minus=None, method="", source="",
               assumptions=None, reliability=RELIABLE, reason="", uncertainty_method="catalog",
               samples=None, validation=None, round_value=True, alternate=None):
        label, unit = self._meta(name)
        if samples is None:
            samples = split_normal(value, err_plus, err_minus, self.n, self.rng)
        unc = None
        if uncertainty_method == "fit_covariance" and (err_plus is not None or err_minus is not None):
            # Report the interval of the physically truncated samples that
            # every downstream quantity is computed from, so the reported
            # fit uncertainty and the propagated ones are consistent.
            summ = summarize(samples)
            if summ:
                value, lo, hi = summ
                unc = Uncertainty(lower=lo, upper=hi, method=uncertainty_method,
                                  interval="68% (16th-84th percentile of covariance samples within physical bounds)")
        elif err_plus is not None or err_minus is not None:
            ep = err_plus if err_plus is not None else err_minus
            em = err_minus if err_minus is not None else err_plus
            unc = Uncertainty(lower=abs(em), upper=abs(ep), method=uncertainty_method,
                              interval="68% (1 sigma)")
        wide = False
        # Applies to every input that carries an uncertainty (catalogue values
        # included -- an imprecise measured mass must not be rated reliable),
        # except logarithmic quantities, whose "relative" error is meaningless
        # ([Fe/H] = 0 is solar, not zero metallicity).
        if unc and provenance in (FITTED, MANUAL_OVERRIDE, CATALOG) and name not in LOG_SCALE_PARAMETERS \
                and value and max(unc.lower, unc.upper) / abs(value) > self.cfg.low_confidence_relative_uncertainty:
            wide = reliability == RELIABLE
            reliability = worst_reliability(reliability, LOW)
            reason = (reason + " " if reason else "") + \
                f"Relative uncertainty exceeds {self.cfg.low_confidence_relative_uncertainty:.0%}."
        if round_value:
            rv, rl, ru, disp = format_measurement(value, unc.lower if unc else None, unc.upper if unc else None)
            if unc:
                unc.lower, unc.upper = rl, ru
        else:
            rv, disp = value, (f"{value:g}" if unc is None else
                               f"{value:g} +{unc.upper:g} / −{unc.lower:g}")
        p = Parameter(name=name, label=label, value=rv, unit=unit, provenance=provenance, reliability=reliability,
                      uncertainty=unc, method=method, source=source, assumptions=list(assumptions or []),
                      reason=reason, validation=list(validation or []), display=disp,
                      alternate_units=alternate(rv) if (alternate and rv is not None) else [])
        self._put(p, samples, set() if unc else {name})
        if wide:
            self.wide_only.add(name)

    def _apply_override(self, name: str) -> bool:
        """Installs an expert override for `name` if one was given; returns
        True when the parameter is now overridden (and must not be computed)."""
        ov = self.overrides.get(name)
        if ov is None:
            return False
        original = self.params.get(name)
        original_dict = None
        if original is not None:
            original_dict = {"value": original.value, "provenance": original.provenance, "display": original.display,
                             "uncertainty": asdict(original.uncertainty) if original.uncertainty else None}
        self._input(name, ov["value"], MANUAL_OVERRIDE, ov["err_plus"], ov["err_minus"],
                    method="Expert override" + (f": {ov['note']}" if ov.get("note") else ""),
                    source="manual_override", uncertainty_method="manual")
        p = self.params[name]
        p.original = original_dict
        if p.uncertainty is None:
            p.reason = "Override supplied without an uncertainty; dependent intervals exclude it."
        return True

    def _derive(self, name, deps, fn, method, equation, assumptions=(), analytic=None, validate=None,
                provenance=None, reliability_floor=None, extra_reason="", alternate=None, optional=()):
        """Computes a derived parameter on every Monte Carlo sample.
        `fn(samples_dict) -> ndarray`. `analytic(values_dict) -> (value, sigma)`
        replaces the MC summary for simple power laws of independent inputs."""
        if self._apply_override(name):
            return
        label, unit = self._meta(name)
        missing = [d for d in deps if not self._ok(d)]
        if missing:
            reasons = "; ".join(f"{self.params[d].label}: {self.params[d].reason or 'unavailable'}"
                                for d in missing if d in self.params)
            self._unavailable(name, f"Requires {', '.join(self.params[d].label if d in self.params else d for d in missing)}"
                                    f" ({reasons})." if reasons else f"Requires {', '.join(missing)}.",
                              missing=missing, depends_on=list(deps))
            return
        used = list(deps) + [d for d in optional if self._ok(d)]
        S = {d: self.samples[d] for d in used}
        with np.errstate(all="ignore"):
            samples = np.asarray(fn(S), dtype=float)
        fixed = set().union(*(self.fixed[d] for d in used)) if used else set()
        dep_params = [self.params[d] for d in used]

        if analytic is not None:
            vals = {d: self.params[d].value for d in used}
            value, sigma = analytic(vals)
            if value is None or not math.isfinite(value):
                self._unavailable(name, "The relation is undefined for the input values.", depends_on=used)
                return
            lo = hi = sigma
            unc_method = "analytic_first_order"
        else:
            summ = summarize(samples)
            if summ is None:
                self._unavailable(name, "The relation is undefined for most of the input distribution "
                                        "(e.g. the geometry admits no transit).", depends_on=used)
                return
            value, lo, hi = summ
            unc_method = "monte_carlo"

        has_unc = lo is not None and hi is not None and (lo > 0 or hi > 0)
        unc = None
        if has_unc:
            unc = Uncertainty(lower=lo, upper=hi, method=unc_method,
                              interval="68% (1 sigma)" if unc_method == "analytic_first_order"
                              else "68% (16th-84th percentile)",
                              complete=not fixed, excluded_inputs=sorted(fixed))
        rv, rl, ru, disp = format_measurement(value, lo if has_unc else None, hi if has_unc else None)
        if unc:
            unc.lower, unc.upper = rl, ru

        prov = provenance or (MODEL_ESTIMATED if any(p.provenance == MODEL_ESTIMATED for p in dep_params) else DERIVED)
        inherited = [p for p in dep_params if p.name not in self.wide_only]
        reliability = worst_reliability(*(p.reliability for p in inherited))
        reasons = [p.reason for p in inherited if p.reliability in (LOW, UNRELIABLE) and p.reason]
        if reliability_floor:
            reliability = worst_reliability(reliability, reliability_floor)
        if extra_reason:
            reasons.insert(0, extra_reason)
        wide = False
        if has_unc and value != 0 and max(lo, hi) / abs(value) > self.cfg.low_confidence_relative_uncertainty:
            if reliability == RELIABLE:
                reliability = LOW
                wide = True
            reasons.append(f"Relative uncertainty exceeds {self.cfg.low_confidence_relative_uncertainty:.0%}.")
        validation: list[str] = []
        if validate:
            v_rel, v_msgs, v_reason = validate(value, samples)
            reliability = worst_reliability(reliability, v_rel)
            validation.extend(v_msgs)
            if v_reason:
                reasons.insert(0, v_reason)

        ov_deps = sorted(set().union(*(set(p.depends_on_override) | ({p.name} if p.provenance == MANUAL_OVERRIDE else set())
                                       for p in dep_params))) if dep_params else []
        assumption_ids = sorted(set(assumptions).union(*(set(p.assumptions) for p in dep_params)))
        p = Parameter(name=name, label=label, value=rv, unit=unit, provenance=prov, reliability=reliability,
                      uncertainty=unc, method=method, equation=equation, assumptions=assumption_ids,
                      depends_on=used, validation=validation,
                      reason=_dedupe_sentences(reasons), depends_on_override=ov_deps,
                      display=disp, alternate_units=alternate(rv, rl, ru) if alternate else [])
        self._put(p, samples, fixed)
        if wide and not validation:
            self.wide_only.add(name)

    # -- inputs ------------------------------------------------------------
    def build_stellar_inputs(self):
        stellar = (self.inputs.get("catalog") or {}).get("stellar") or {}
        catalog_note = (self.inputs.get("catalog") or {}).get("note", "")
        for name, column in (("stellar_teff", "koi_steff"), ("stellar_logg", "koi_slogg"),
                             ("stellar_radius", "koi_srad")):
            rec = stellar.get(name)
            if rec and rec.get("value") is not None:
                self._input(name, rec["value"], CATALOG, rec.get("err_plus"), rec.get("err_minus"),
                            method="Local NASA Exoplanet Archive KOI catalogue", source=column,
                            assumptions=["catalog_stellar_parameters"], round_value=False)
                if rec.get("err_plus") is None and rec.get("err_minus") is None:
                    self.params[name].reason = "The catalogue lists no uncertainty for this value."
            else:
                self._unavailable(name, f"Not available from the KOI catalogue ({column}). {catalog_note}".strip())
            self._apply_override(name)
        for name, column in (("ra", "ra"), ("dec", "dec"), ("kepmag", "koi_kepmag")):
            rec = stellar.get(name)
            if rec and rec.get("value") is not None:
                self._input(name, rec["value"], CATALOG, method="Local NASA Exoplanet Archive KOI catalogue",
                            source=column, round_value=False)
                self.fixed[name] = set()   # identification only, never propagated
            else:
                self._unavailable(name, f"Not available from the KOI catalogue ({column}).")
        archive = (self.inputs.get("catalog") or {}).get("archive")
        archive_stellar = (archive or {}).get("stellar") or {}
        not_looked_up = ("" if archive else " The NASA Exoplanet Archive was not queried for this report.")
        for name, missing_reason in (
            ("stellar_metallicity", "The local KOI catalogue has no metallicity and the Archive's Kepler DR25 stellar "
                                    "table returned none for this star."),
            ("distance", "The local KOI catalogue has no distance and the Archive returned none for this star."),
        ):
            rec = archive_stellar.get(name)
            if rec:
                self._input(name, rec["value"], CATALOG, rec.get("err_plus"), rec.get("err_minus"),
                            method=rec["source"], source=rec["source"], round_value=False)
                self.fixed[name] = set()   # informational: no calculation in this engine uses it
            else:
                notes = " ".join((archive or {}).get("notes") or [])
                self._unavailable(name, f"{missing_reason}{not_looked_up} {notes} It can be supplied through Expert "
                                        "Override; no calculation in this engine requires it.".replace("  ", " "))
            self._apply_override(name)

    def build_transit_inputs(self):
        fit, cfg = self.fit, self.cfg
        reference = (self.inputs.get("catalog") or {}).get("reference") or {}
        lc = self.inputs.get("light_curve") or {}
        bls = fit.get("bls") or lc.get("bls") or {}

        if bls.get("depth_ppm") is not None and bls["depth_ppm"] > 0:
            self._input("transit_depth_bls", bls["depth_ppm"], OBSERVED,
                        method="Box Least Squares best-fit box depth (no limb darkening; typically underestimates "
                               "the true mid-transit depth).", source="box_least_squares", round_value=True)
        else:
            self._unavailable("transit_depth_bls", "The transit search found no positive transit depth.")

        fit_samples = None
        if self.fit_ok:
            fit_samples = self._sample_fit()
        p = fit.get("params") or {}
        errs = fit.get("errors") or {}
        fit_assumptions = ["circular_orbit", "limb_darkening_fixed", "no_dilution", "time_in_days",
                           "white_noise_empirical", "fit_covariance_gaussian"]
        if fit.get("stellar_density_prior"):
            fit_assumptions.append("stellar_density_prior")
        base_rel, base_reason = self.fit_reliability, self.fit_reason
        no_cov_reason = "" if errs else "Fit covariance unavailable (degenerate parameters); no statistical uncertainty."
        if self.fit_ok and not errs and base_rel == RELIABLE:
            base_rel = LOW

        if not self.fit_ok:
            msg = fit.get("message") or "No transit fit is available."
            for name in ("transit_epoch", "a_over_rstar", "impact_parameter"):
                self._unavailable(name, f"Transit fit unavailable: {msg}")
        else:
            self._input("transit_epoch", p["t0"], FITTED, errs.get("t0"), errs.get("t0"),
                        method="Limb-darkened transit-model fit (reference transit nearest the data midpoint).",
                        source="transit_fit", assumptions=fit_assumptions, reliability=base_rel,
                        reason=base_reason or no_cov_reason, uncertainty_method="fit_covariance",
                        samples=fit_samples["t0"])
            self._input("a_over_rstar", p["a_rs"], FITTED, errs.get("a_rs"), errs.get("a_rs"),
                        method="Transit-model fit (circular-orbit equivalent).", source="transit_fit",
                        assumptions=fit_assumptions, reliability=base_rel, reason=base_reason or no_cov_reason,
                        uncertainty_method="fit_covariance", samples=fit_samples["a_rs"])
            b_s = fit_samples["b"]
            summ = summarize(b_s) if errs else None
            label, unit = self._meta("impact_parameter")
            if summ:
                v, lo, hi = summ
                rv, rl, ru, disp = format_measurement(v, lo, hi)
                unc = Uncertainty(rl, ru, "monte_carlo")
            else:
                rv, _, _, disp = format_measurement(p["b"])
                unc = None
            rel, reason = base_rel, base_reason or no_cov_reason
            if summ and (hi + lo) > 0.5:
                rel = worst_reliability(rel, LOW)
                reason = (reason + " " if reason else "") + ("Impact parameter poorly constrained (b - a/R* "
                          "degeneracy at this SNR/cadence); dependent geometry is uncertain.")
            self._put(Parameter(name="impact_parameter", label=label, value=rv, unit=unit, provenance=FITTED,
                                reliability=rel, uncertainty=unc, method="Transit-model fit (fitted as b^2).",
                                source="transit_fit", assumptions=fit_assumptions, reason=reason, display=disp),
                      b_s, set() if unc else {"impact_parameter"})
            if not fit.get("period_constrained"):
                for name in ("a_over_rstar",):
                    self.params[name].reliability = UNRELIABLE
                    self.params[name].reason = ("Only one transit was observed, so the period was not fitted and "
                                                "a/R* (degenerate with it) is not constrained.")

        self._apply_override("transit_epoch")
        self._apply_override("impact_parameter")

        # Orbital period: fitted from repeated transits > catalogue > unavailable.
        if self.fit_ok and fit.get("period_constrained"):
            self._input("orbital_period", p["period"], FITTED, errs.get("period"), errs.get("period"),
                        method=f"Transit-model fit across {fit.get('n_transits_with_data')} observed transits.",
                        source="transit_fit", assumptions=["time_in_days"], reliability=base_rel,
                        reason=base_reason or no_cov_reason, uncertainty_method="fit_covariance",
                        samples=fit_samples["period"])
        elif reference.get("orbital_period"):
            ref = reference["orbital_period"]
            self._input("orbital_period", ref["value"], CATALOG, ref.get("err_plus"), ref.get("err_minus"),
                        method="KOI catalogue period (the light curve does not contain two transits).",
                        source="koi_period", round_value=False)
            self.warnings.append("The orbital period comes from the KOI catalogue because the light curve does not "
                                 "constrain it (fewer than two transits with data).")
        else:
            self._unavailable("orbital_period", "Requires at least two transits with data in the light curve "
                                                "(or a catalogue period); the transit-search period is not a "
                                                "measurement when only one event is observed.")
        self._apply_override("orbital_period")

        # Radius ratio: fitted > sqrt(BLS depth) approximation > unavailable.
        if self.fit_ok:
            self._input("radius_ratio", p["k"], FITTED, errs.get("k"), errs.get("k"),
                        method="Transit-model fit with quadratic limb darkening.", source="transit_fit",
                        assumptions=fit_assumptions, reliability=base_rel, reason=base_reason or no_cov_reason,
                        uncertainty_method="fit_covariance", samples=fit_samples["k"])
        elif fit.get("status") == "failed" and self._ok("transit_depth_bls"):
            # A transit was detected but could not be modelled: fall back to
            # the first-order relation. Never used when no transit was found.
            d = self._value("transit_depth_bls") * 1e-6
            self._input("radius_ratio", math.sqrt(d), DERIVED, method="Rp/R* ~ sqrt(depth) from the BLS box depth "
                        "(non-grazing, no limb darkening, no dilution).", source="sqrt(transit_depth_bls)",
                        assumptions=["no_dilution"], reliability=LOW,
                        reason="First-order approximation from the box depth because the transit-model fit failed.")
        else:
            self._unavailable("radius_ratio", "Requires a transit fit or a positive transit depth.")
        self._apply_override("radius_ratio")

        snr = fit.get("snr") if self.fit_ok else None
        if snr is not None:
            label, unit = self._meta("transit_snr")
            rv, _, _, disp = format_measurement(snr)
            self._put(Parameter(
                name="transit_snr", label=label, value=rv, unit=unit, provenance=OBSERVED,
                reliability=RELIABLE if snr >= cfg.snr_detection_threshold else UNRELIABLE,
                method="SNR = depth / (sigma_1 * beta) * sqrt(N_in): model depth over per-point noise inflated by "
                       "the red-noise factor, times the square root of the number of in-transit points.",
                equation="SNR = delta / (sigma_1 beta) sqrt(N_in)", source="transit_fit",
                validation=[f"{'Above' if snr >= cfg.snr_detection_threshold else 'Below'} the "
                            f"{cfg.snr_detection_threshold} detection threshold."],
                reason=self.fit_reason, display=disp), None, set())
        else:
            self._unavailable("transit_snr", "Requires a transit-model fit.")

        # Eccentricity / argument of periastron: assumed circular unless overridden.
        label, unit = self._meta("eccentricity")
        # Reliability is "not assessed" (an assumption has none); its effect is
        # carried by the circular_orbit assumption on every dependent output.
        self._put(Parameter(name="eccentricity", label=label, value=0.0, unit=unit, provenance=ASSUMED,
                            reliability=NOT_ASSESSED, method="Assumed circular; not constrained by transit photometry.",
                            assumptions=["circular_orbit"], display="0 (assumed circular)",
                            reason="Assumption, not a measurement."), np.zeros(self.n), set())
        label, unit = self._meta("arg_periastron")
        self._put(Parameter(name="arg_periastron", label=label, value=90.0, unit=unit, provenance=ASSUMED,
                            reliability=NOT_ASSESSED, method="Undefined for a circular orbit; 90° makes all "
                            "eccentricity factors unity.", assumptions=["circular_orbit"],
                            display="Undefined (circular orbit)"), np.full(self.n, 90.0), set())
        self._apply_override("eccentricity")
        self._apply_override("arg_periastron")

    def _sample_fit(self, fit: dict | None = None) -> dict[str, np.ndarray]:
        """Joint samples of the fitted parameters from the fit covariance,
        restricted to the physical domain (k > 0, a/R* > 1, 0 <= b^2 <
        (1+k)^2). Falls back to the best fit (no spread) without covariance.
        `fit` defaults to the fit in use; the prior-free fit is passed for
        the independent transit-only stellar density."""
        fit = fit or self.fit
        names = fit.get("fitted_names") or []
        p = fit["params"]
        cov = fit.get("covariance")
        out = {n: np.full(self.n, p[n] if n != "b2" else p["b"] ** 2) for n in ("t0", "period", "k", "a_rs", "b2")}
        if cov:
            mean = np.array([p[n] for n in names])
            cov_arr = np.array(cov)
            accepted = []
            total, n_acc = 0, 0
            for _ in range(20):
                draws = multivariate_normal(mean, cov_arr, self.n, self.rng)
                d = dict(zip(names, draws.T))
                k = d.get("k", out["k"][: draws.shape[0]])
                a = d.get("a_rs", out["a_rs"][: draws.shape[0]])
                b2 = d.get("b2", out["b2"][: draws.shape[0]])
                ok = (k > 0) & (a > 1) & (b2 >= 0) & (b2 < (1 + k) ** 2)
                total += draws.shape[0]
                accepted.append(draws[ok])
                n_acc += int(ok.sum())
                if n_acc >= self.n:
                    break
            good = np.concatenate(accepted)[: self.n]
            if good.shape[0] < self.n:
                self.warnings.append("Fit-parameter sampling accepted too few physical samples; uncertainties are "
                                     "approximate.")
                extra = multivariate_normal(mean, cov_arr, self.n - good.shape[0], self.rng)
                good = np.vstack([good, extra])
            for i, n in enumerate(names):
                out[n] = good[:, i]
            out["k"] = np.clip(out["k"], 1e-6, None)
            out["a_rs"] = np.clip(out["a_rs"], 1.0 + 1e-6, None)
            out["b2"] = np.clip(out["b2"], 0.0, None)
        out["b"] = np.sqrt(out["b2"])
        return out

    # -- derived -----------------------------------------------------------
    def build_derived(self):
        cfg = self.cfg
        f_redis = physics.HEAT_REDISTRIBUTION_FACTORS[cfg.heat_redistribution]
        u1, u2 = self.ld["u1"], self.ld["u2"]

        # Star: stellar mass = local catalogue > verified Archive (DR25) > log g + R* > unavailable
        self._stellar_mass()
        self._derive(
            "stellar_luminosity", ["stellar_radius", "stellar_teff"],
            lambda S: physics.stellar_luminosity(S["stellar_radius"], S["stellar_teff"]),
            "Stefan-Boltzmann law relative to the IAU nominal Sun.", "L* = (R*/R☉)^2 (Teff/5772 K)^4",
            assumptions=["blackbody"],
            analytic=lambda v: (float(physics.stellar_luminosity(v["stellar_radius"], v["stellar_teff"])),
                                analytic_power_law(float(physics.stellar_luminosity(v["stellar_radius"], v["stellar_teff"])),
                                                   [(v["stellar_radius"], 2, self._sym("stellar_radius")),
                                                    (v["stellar_teff"], 4, self._sym("stellar_teff"))])),
        )
        self._derive(
            "stellar_density", ["stellar_mass", "stellar_radius"],
            lambda S: physics.stellar_density_from_mass_radius(S["stellar_mass"], S["stellar_radius"]),
            "Mean density from stellar mass and radius (Monte Carlo: mass and radius are correlated when the mass "
            "is derived from log g).", "rho* = M* / (4/3 pi R*^3)",
        )

        # Orbit geometry (fit space)
        a_circ_ok = self._ok("a_over_rstar") and self.params["a_over_rstar"].provenance != MANUAL_OVERRIDE
        e_ov = "eccentricity" in self.overrides
        if a_circ_ok and e_ov:
            a_circ = self.params["a_over_rstar"]
            # Convert the circular-equivalent fitted a/R* into the true value
            # for the supplied eccentricity (Kipping 2010 photo-eccentric factor).
            e_s, w_s = self.samples["eccentricity"], self.samples["arg_periastron"]
            factor = np.sqrt(1 - e_s ** 2) / (1 + e_s * np.sin(np.radians(w_s)))
            new_s = self.samples["a_over_rstar"] * factor
            summ = summarize(new_s)
            if summ:
                v, lo, hi = summ
                rv, rl, ru, disp = format_measurement(v, lo, hi)
                a_circ.original = {"value": a_circ.value, "provenance": a_circ.provenance, "display": a_circ.display,
                                   "uncertainty": asdict(a_circ.uncertainty) if a_circ.uncertainty else None}
                a_circ.value, a_circ.display, a_circ.provenance = rv, disp, DERIVED
                a_circ.uncertainty = Uncertainty(rl, ru, "monte_carlo")
                a_circ.method = ("Circular-equivalent fitted a/R* scaled by sqrt(1-e^2)/(1+e sin w) for the "
                                 "supplied eccentricity (Kipping 2010).")
                a_circ.depends_on = ["eccentricity", "arg_periastron"]
                a_circ.depends_on_override = sorted({"eccentricity", "arg_periastron"} & set(self.overrides))
                self.samples["a_over_rstar"] = new_s
        self._apply_override("a_over_rstar")

        geom_deps = ["orbital_period", "radius_ratio", "a_over_rstar", "impact_parameter"]
        if self.fit_ok or all(self._ok(d) for d in geom_deps):
            self._derive(
                "transit_depth", ["radius_ratio", "impact_parameter"],
                lambda S: central_depth(S["radius_ratio"], S["impact_parameter"], u1, u2) * 1e6,
                "Depth of the limb-darkened model at mid-transit (differs from k^2 by limb darkening and "
                "grazing geometry).", "delta = F_blocked(z = b; k, u1, u2)",
                assumptions=["limb_darkening_fixed"], provenance=FITTED if self.fit_ok else DERIVED,
                alternate=lambda v, lo, hi: [{"value": v / 1e6, "unit": "fraction",
                                              "uncertainty": [lo / 1e6 if lo else None, hi / 1e6 if hi else None]}],
            )
        else:
            if not self._apply_override("transit_depth"):
                if self.fit.get("status") == "failed" and self._ok("transit_depth_bls"):
                    bls_p = self.params["transit_depth_bls"]
                    self._input("transit_depth", bls_p.value, OBSERVED, method="BLS box depth (the transit-model "
                                "fit is unavailable).", source="box_least_squares", reliability=LOW,
                                reason="Box depth without limb darkening; the transit-model fit failed.")
                else:
                    self._unavailable("transit_depth", "No transit was detected.")
        self.params["transit_depth"].alternate_units = self.params["transit_depth"].alternate_units or (
            [{"value": self.params["transit_depth"].value / 1e6, "unit": "fraction", "uncertainty": None}]
            if self._ok("transit_depth") else [])

        def t14(S):
            return physics.transit_durations(S["orbital_period"], S["radius_ratio"], S["a_over_rstar"],
                                             S["impact_parameter"])[0] * 24.0

        def t23(S):
            return physics.transit_durations(S["orbital_period"], S["radius_ratio"], S["a_over_rstar"],
                                             S["impact_parameter"])[1] * 24.0

        prov_geom = FITTED if self.fit_ok else DERIVED
        self._derive("transit_duration", geom_deps, t14,
                     "First-to-fourth-contact duration of the fitted circular-orbit model (Winn 2010, eq. 14).",
                     "T14 = P/pi asin( sqrt((1+k)^2 - b^2) / (a/R* sin i) )", provenance=prov_geom,
                     alternate=lambda v, lo, hi: [{"value": round(v / 24.0, 6), "unit": "days", "uncertainty": None}])
        if not self._ok("transit_duration") and "transit_duration" not in self.overrides \
                and self.fit.get("status") == "failed" and bls_duration(self.fit):
            self._input("transit_duration", bls_duration(self.fit), OBSERVED, method="BLS box duration (fit "
                        "unavailable).", source="box_least_squares", reliability=LOW,
                        reason="Box duration; not a model T14.")
        grazing = self._grazing()
        if grazing:
            self._unavailable("transit_duration_full", "Grazing transit: there is no full-depth (second-to-third "
                                                       "contact) phase.")
        else:
            self._derive("transit_duration_full", geom_deps, t23,
                         "Second-to-third-contact duration (Winn 2010, eq. 15).",
                         "T23 = P/pi asin( sqrt((1-k)^2 - b^2) / (a/R* sin i) )", provenance=prov_geom)
        if self._ok("transit_duration") and self._ok("transit_duration_full") \
                and self.samples.get("transit_duration") is not None and self.samples.get("transit_duration_full") is not None:
            self._derive("ingress_duration", ["transit_duration", "transit_duration_full"],
                         lambda S: (S["transit_duration"] - S["transit_duration_full"]) / 2.0 * 60.0,
                         "Half the difference between T14 and T23.", "tau = (T14 - T23) / 2", provenance=prov_geom)
        else:
            self._unavailable("ingress_duration", "Requires both T14 and T23 from the transit model.",
                              depends_on=["transit_duration", "transit_duration_full"])

        if grazing and self._ok("radius_ratio") and self.params["radius_ratio"].provenance == FITTED:
            rr = self.params["radius_ratio"]
            rr.reliability = worst_reliability(rr.reliability, LOW)
            rr.validation.append("Grazing geometry (b > 1 - k): k is strongly degenerate with b.")
            rr.reason = (rr.reason + " " if rr.reason else "") + "Grazing transit: the radius ratio is poorly " \
                        "constrained and may be underestimated."
            self.warnings.append("The best-fit transit is grazing (b > 1 - Rp/R*): the planet radius is poorly "
                                 "constrained, and grazing geometries are also typical of eclipsing binaries.")

        # Planet radius
        self._derive("planet_radius", ["radius_ratio", "stellar_radius"],
                     lambda S: physics.planet_radius_earth(S["radius_ratio"], S["stellar_radius"]),
                     "Rp = (Rp/R*) x R*, using the fitted radius ratio (not the sqrt(depth) approximation).",
                     "Rp = k R* (R☉ -> R⊕: x 109.2)", assumptions=["no_dilution"],
                     validate=self._validate_radius,
                     alternate=lambda v, lo, hi: [{"value": round(v * physics.R_EARTH_M / physics.R_JUP_M, 4),
                                                   "unit": "R_Jup", "uncertainty": None}])

        # Planet mass: expert override > Archive measurement > model estimate
        # Planet mass: expert override > Archive measurement > Archive estimate
        # with an uncertainty > Chen & Kipping (2017) from the radius > unavailable
        archive_mass = ((self.inputs.get("catalog") or {}).get("archive") or {}).get("planet", {}).get("planet_mass")
        if self._apply_override("planet_mass"):
            pass
        elif archive_mass and archive_mass.get("kind", "measured") == "measured":
            self._input("planet_mass", archive_mass["value"], CATALOG, archive_mass["err_plus"],
                        archive_mass["err_minus"], method=archive_mass.get("method") or (
                            "Measured planet mass (radial velocities or transit-timing variations) from the NASA "
                            "Exoplanet Archive."), source=archive_mass["source"], round_value=False)
            self.params["planet_mass"].evidence = MEASURED
        elif archive_mass and archive_mass.get("kind") == "catalogue_estimate":
            self._input("planet_mass", archive_mass["value"], MODEL_ESTIMATED, archive_mass["err_plus"],
                        archive_mass["err_minus"], method=archive_mass["method"], source=archive_mass["source"],
                        reliability=LOW, round_value=False,
                        reason="A catalogue estimate, not a measurement: a radial-velocity or transit-timing mass "
                               "measurement would replace it.")
        else:
            if self._ok("planet_radius") and self._value("planet_radius") > physics.CK17_R_NEPTUNIAN_MAX:
                self._unavailable("planet_mass", f"Radius above ~{physics.CK17_R_NEPTUNIAN_MAX:.1f} R⊕ is in the "
                                  "giant-planet regime where radius barely depends on mass; mass cannot be estimated "
                                  "from radius. A radial-velocity mass can be supplied through Expert Override.",
                                  depends_on=["planet_radius"])
            else:
                scatter = self.rng.standard_normal(self.n)
                self._derive("planet_mass", ["planet_radius"],
                             lambda S: physics.mass_from_radius_ck17(S["planet_radius"], scatter),
                             "Chen & Kipping (2017) empirical mass-radius relation (Terran/Neptunian branches), "
                             "including its intrinsic scatter. An estimate, not a measurement.",
                             "log10 R = C + S log10 M  (S = 0.279 / 0.589)", assumptions=["ck17_mass_radius"],
                             provenance=MODEL_ESTIMATED, reliability_floor=LOW,
                             extra_reason=self._no_measured_mass_reason())

        # Semi-major axis: Kepler's third law (stellar mass) > transit geometry (a/R* x R*)
        measured_mass = self._ok("planet_mass") and self.params["planet_mass"].evidence in (MEASURED, "expert_override")
        if self._ok("stellar_mass") and self._ok("orbital_period"):
            self._derive("semi_major_axis", ["orbital_period", "stellar_mass"],
                         lambda S: physics.semi_major_axis_kepler(S["orbital_period"], S["stellar_mass"],
                                                                  S.get("planet_mass", 0.0)),
                         "Kepler's third law with the stellar mass" + (" plus the measured planet mass." if measured_mass
                                                                       else " (planet mass neglected)."),
                         "a = (G (M* + Mp) P^2 / 4 pi^2)^(1/3)",
                         assumptions=[] if measured_mass else ["negligible_planet_mass"],
                         optional=["planet_mass"] if measured_mass else [])
        else:
            self._derive("semi_major_axis", ["a_over_rstar", "stellar_radius"],
                         lambda S: physics.semi_major_axis_from_ratio(S["a_over_rstar"], S["stellar_radius"]),
                         "Transit geometry: a = (a/R*) x R* (used because the stellar mass or period is unavailable).",
                         "a = (a/R*) R*")
        self._derive("inclination", ["impact_parameter", "a_over_rstar", "eccentricity", "arg_periastron"],
                     lambda S: physics.inclination_deg(S["impact_parameter"], S["a_over_rstar"], S["eccentricity"],
                                                       S["arg_periastron"]),
                     "From the impact parameter and scaled semi-major axis (Winn 2010, eq. 7).",
                     "cos i = (b R*/a) (1 + e sin w) / (1 - e^2)")
        # With a stellar-density prior, the fitted a/R* already encodes the
        # catalogue density, so the transit-only density comes from the
        # prior-free fit's profile likelihood -- never from the constrained
        # fit (that comparison would be circular). Expert overrides of a/R*
        # or P take precedence and use the ordinary derivation.
        free = self.fit.get("unconstrained") if self.fit_ok else None
        profile = ((free or {}).get("density_profile") or self.fit.get("density_profile")) if self.fit_ok else None
        if profile and not ({"a_over_rstar", "orbital_period"} & set(self.overrides)):
            self._density_from_profile(profile)
        else:
            self._derive("stellar_density_transit", ["orbital_period", "a_over_rstar"],
                         lambda S: physics.stellar_density_from_transit(S["orbital_period"], S["a_over_rstar"]),
                         "Mean stellar density implied by the transit shape and period (Seager & Mallen-Ornelas 2003).",
                         "rho* = 3 pi (a/R*)^3 / (G P^2)", assumptions=["negligible_planet_mass"])
        self._derive("orbital_velocity", ["semi_major_axis", "orbital_period"],
                     lambda S: physics.orbital_velocity_kms(S["semi_major_axis"], S["orbital_period"]),
                     "Mean orbital speed 2 pi a / P.", "v = 2 pi a / P")

        # Thermal environment
        self._derive("insolation", ["stellar_luminosity", "semi_major_axis", "eccentricity"],
                     lambda S: physics.insolation_earth(S["stellar_luminosity"], S["semi_major_axis"], S["eccentricity"]),
                     "Orbit-averaged incident flux relative to Earth.", "S = (L*/L☉) / (a/AU)^2 / sqrt(1 - e^2)",
                     assumptions=["blackbody"])
        self._derive("equilibrium_temperature", ["stellar_teff", "stellar_radius", "semi_major_axis", "eccentricity"],
                     lambda S: physics.equilibrium_temperature(S["stellar_teff"], S["stellar_radius"],
                                                               S["semi_major_axis"], cfg.bond_albedo, f_redis,
                                                               S["eccentricity"]),
                     f"Radiative equilibrium with assumed Bond albedo {cfg.bond_albedo:g} and "
                     f"'{cfg.heat_redistribution}' heat redistribution.",
                     "Teq = Teff sqrt(R*/a) [f (1 - A)]^(1/4) (1 - e^2)^(-1/8)",
                     assumptions=["bond_albedo", "heat_redistribution", "blackbody"])
        teq = self.params["equilibrium_temperature"]
        if teq.status == STATUS_COMPUTED and teq.provenance != MANUAL_OVERRIDE:
            t, r, a, e = (self._value(n) for n in ("stellar_teff", "stellar_radius", "semi_major_axis", "eccentricity"))
            lo_t = physics.equilibrium_temperature(t, r, a, 0.7, physics.HEAT_REDISTRIBUTION_FACTORS["full"], e)
            hi_t = physics.equilibrium_temperature(t, r, a, 0.0, physics.HEAT_REDISTRIBUTION_FACTORS["dayside"], e)
            teq.systematic_range = {"min": round(float(lo_t)), "max": round(float(hi_t)), "unit": "K",
                                    "basis": "Bond albedo 0-0.7 and full vs dayside-only heat redistribution "
                                             "(central inputs). Not included in the statistical interval."}
            if teq.uncertainty:
                teq.uncertainty.systematic = ["Bond albedo and heat redistribution are assumed (see systematic_range)."]

        for name, boundary in (("hz_inner_conservative", "runaway_greenhouse"),
                               ("hz_outer_conservative", "maximum_greenhouse"),
                               ("hz_inner_optimistic", "recent_venus"), ("hz_outer_optimistic", "early_mars")):
            self._derive(name, ["stellar_teff", "stellar_luminosity"],
                         lambda S, bnd=boundary: physics.hz_distance_au(
                             S["stellar_luminosity"], physics.hz_effective_flux(S["stellar_teff"], bnd)),
                         f"Kopparapu et al. (2014) '{boundary.replace('_', ' ')}' boundary, d = sqrt(L*/S_eff).",
                         "S_eff = S0 + aT + bT^2 + cT^3 + dT^4, T = Teff - 5780 K", assumptions=["kopparapu_hz"])

        # Planet bulk properties (need a mass)
        for name, fn, method, eq, unit_note in (
            ("planet_density", physics.planet_density, "Bulk density from mass and radius.", "rho = Mp / (4/3 pi Rp^3)", ""),
            ("planet_surface_gravity", physics.planet_surface_gravity, "Surface gravity from mass and radius.",
             "g = G Mp / Rp^2", ""),
            ("escape_velocity", physics.escape_velocity_kms, "Escape velocity from mass and radius.",
             "v_esc = sqrt(2 G Mp / Rp)", ""),
        ):
            self._derive(name, ["planet_mass", "planet_radius"],
                         lambda S, f=fn: f(S["planet_mass"], S["planet_radius"]), method, eq)
        self._explain_mass_dependents()

    def _stellar_mass(self):
        """Stellar mass, best evidence first:
          1. expert override;
          2. local KOI catalogue (koi_smass, when the snapshot has it);
          3. the Archive's Kepler DR25 isochrone mass, already identity-checked
             against the local catalogue (archive_enrichment.lookup);
          4. Newtonian gravity M* = g R*^2 / G from catalogue log g and R*;
          5. unavailable -- Teff, R* or luminosity alone do not determine it."""
        if self._apply_override("stellar_mass"):
            return
        catalog = self.inputs.get("catalog") or {}
        local = (catalog.get("stellar") or {}).get("stellar_mass")
        archive = ((catalog.get("archive") or {}).get("stellar") or {}).get("stellar_mass")
        for rec, method, source in (
            (local, "Local NASA Exoplanet Archive KOI catalogue stellar mass (koi_smass).", "koi_smass"),
            (archive, (archive or {}).get("method", ""), (archive or {}).get("source", "")),
        ):
            if rec and rec.get("value") and rec.get("err_plus") and rec.get("err_minus"):
                self._input("stellar_mass", rec["value"], CATALOG, rec["err_plus"], rec["err_minus"], method=method,
                            source=source, assumptions=["catalog_stellar_parameters"], round_value=False)
                return
        if self._ok("stellar_logg") and self._ok("stellar_radius"):
            self._derive(
                "stellar_mass", ["stellar_logg", "stellar_radius"],
                lambda S: physics.stellar_mass_from_logg_radius(S["stellar_logg"], S["stellar_radius"]),
                "Newtonian gravity g = G M / R^2 with catalogue log g and radius.", "M* = 10^logg R*^2 / G",
                analytic=lambda v: (float(physics.stellar_mass_from_logg_radius(v["stellar_logg"], v["stellar_radius"])),
                                    self._analytic_mass_sigma(v)),
                validate=lambda v, s: ((LOW, ["Spectroscopic/photometric log g is typically uncertain by ~0.1 dex, "
                                              "i.e. ~25% in mass."], "") if self._rel_err("stellar_logg") is None else
                                       (RELIABLE, [], "")),
            )
            return
        have = [self.params[n].label for n in ("stellar_teff", "stellar_radius", "stellar_luminosity", "stellar_logg")
                if self._ok(n)]
        self._unavailable(
            "stellar_mass",
            "No stellar mass in the catalogues, and log g with R* (which give M* = g R*^2 / G) is not available"
            + (f"; the available {', '.join(have)} do not determine the mass on their own" if have else "")
            + ". A catalogue or spectroscopic log g with its uncertainty, or an isochrone mass, is needed.",
            missing=[n for n in ("stellar_logg", "stellar_radius") if not self._ok(n)])

    # Power-law exponents (alpha, beta) of q = M^alpha R^beta for the
    # mass-dependent quantities, used for their uncertainty budgets.
    MASS_RADIUS_EXPONENTS = {"planet_density": (1.0, -3.0), "planet_surface_gravity": (1.0, -2.0),
                             "escape_velocity": (0.5, -0.5)}

    def _explain_mass_dependents(self):
        """States what each mass-dependent quantity rests on and where its
        uncertainty comes from: the share of var(ln q) contributed by the
        mass and by the radius, from the same (correlated) Monte Carlo
        samples the values were computed from."""
        mass = self.params.get("planet_mass")
        if not (self._ok("planet_mass") and self._ok("planet_radius")):
            return
        basis = {
            "model_estimated": ("Uses the model-estimated planet mass (Chen & Kipping 2017), not a measured one."
                                if "Chen & Kipping" in (mass.method or "") else
                                "Uses a catalogue planet-mass estimate, not a measured one."),
            MEASURED: "Uses the measured planet mass from the NASA Exoplanet Archive.",
            "expert_override": "Uses the expert-supplied planet mass.",
        }.get(mass.evidence, "")
        with np.errstate(all="ignore"):
            ln_m = np.log(self.samples["planet_mass"])
            ln_r = np.log(self.samples["planet_radius"])
        ok = np.isfinite(ln_m) & np.isfinite(ln_r)
        var_m, var_r = (float(np.var(ln_m[ok])), float(np.var(ln_r[ok]))) if ok.sum() > 10 else (0.0, 0.0)
        corr = float(np.corrcoef(ln_m[ok], ln_r[ok])[0, 1]) if var_m > 0 and var_r > 0 else 0.0
        corr_note = (f" (Mass and radius are correlated, r = {corr:.2f}, because the mass is computed from the radius; "
                     "the reported interval includes that correlation, the split above does not.)"
                     if abs(corr) > 0.1 else "")
        for name, (alpha, beta) in self.MASS_RADIUS_EXPONENTS.items():
            p = self.params.get(name)
            if not self._ok(name):
                continue
            tm, tr = alpha ** 2 * var_m, beta ** 2 * var_r
            budget = (f" The mass contributes {100 * tm / (tm + tr):.0f}% of its uncertainty and the radius "
                      f"{100 * tr / (tm + tr):.0f}%." if tm + tr > 0 else "")
            wide = (f" Relative uncertainty exceeds {self.cfg.low_confidence_relative_uncertainty:.0%}."
                    if "Relative uncertainty exceeds" in (p.reason or "") else "")
            improve = (" A measured mass would make it a measurement." if mass.evidence == "model_estimated" else "")
            p.reason = (basis + budget + corr_note + wide + improve).strip()

    def _no_measured_mass_reason(self) -> str:
        """Why the mass is a radius-based estimate, and what would replace it."""
        archive = (self.inputs.get("catalog") or {}).get("archive")
        notes = " ".join((archive or {}).get("notes") or [])
        if archive is None:
            where = "No mass measurement is in the local KOI catalogue (the NASA Exoplanet Archive was not queried)."
        elif "M-R relationship" in notes or "not a measurement" in notes:
            where = ("The NASA Exoplanet Archive has no measured mass for this planet: its listed mass is itself a "
                     "mass-radius estimate.")
        else:
            where = "The NASA Exoplanet Archive lists no measured mass for this target."
        return ("Model estimate from radius only (Chen & Kipping 2017 mass-radius relation, including its intrinsic "
                f"scatter). {where} A radial-velocity or transit-timing mass measurement would make the mass, and "
                "the bulk density, surface gravity and escape velocity derived from it, measurements.")

    def _density_from_profile(self, profile: dict) -> None:
        """Transit-only stellar density from the prior-free profile
        likelihood (transit_fit.stellar_density_profile). Its 68% interval is
        reported as measured; when the light curve does not bound rho* on one
        side, the value is unreliable and the bound that is known is stated."""
        label, unit = self._meta("stellar_density_transit")
        best, lo, hi = profile.get("best"), profile.get("lower_68"), profile.get("upper_68")
        method = ("Mean stellar density from the transit shape and period alone: profile likelihood of the "
                  "prior-free transit fit (each density refitted with a/R* fixed, Delta chi^2 <= 1). Independent "
                  "of the catalogue density used as the fit prior (Seager & Mallen-Ornelas 2003).")
        common = dict(name="stellar_density_transit", label=label, unit=unit, provenance=DERIVED, method=method,
                      equation="rho* = 3 pi (a/R*)^3 / (G P^2)", source="transit_fit (prior-free)",
                      assumptions=["circular_orbit", "negligible_planet_mass", "limb_darkening_fixed", "no_dilution"],
                      depends_on=["orbital_period", "a_over_rstar"])
        # When the ingress is much shorter than one exposure, the light curve
        # does not resolve the transit shape: b and a/R* stay degenerate and the
        # exposure-integrated model's discretisation error can favour the wrong
        # (grazing) branch, so the transit-only density is not trustworthy.
        exposure_min = (self.fit.get("exposure_days") or 0.0) * 1440.0
        ingress = self.params.get("ingress_duration")
        unresolved = profile.get("resolved") is False or (
            exposure_min > 0 and self._ok("ingress_duration") and ingress.value < INGRESS_RESOLUTION_FRACTION * exposure_min)
        if unresolved:
            if not self._ok("ingress_duration"):
                ingress = Parameter(name="ingress_duration", label="", value=profile.get("ingress_minutes"), unit="min",
                                    provenance=FITTED, display=f"{profile.get('ingress_minutes', 0):.2g}")
            self.density_bound = (f"ingress {ingress.display} min is shorter than half the {exposure_min:.1f}-min exposure, "
                                  "so the transit shape is not resolved")
            self._unavailable(
                "stellar_density_transit",
                f"Not constrained by the light curve alone: the ingress ({ingress.display} min) is shorter than half "
                f"the {exposure_min:.1f}-minute exposure, so the transit shape cannot separate the impact parameter "
                "from a/R*. Shorter-cadence photometry (e.g. Kepler 1-minute data) is needed for an independent "
                "stellar density.", depends_on=["ingress_duration"])
            return
        if not profile.get("bounded"):
            if lo is None and hi is None:
                bound, side = "not bounded on either side within 0.01-100 g/cm³", None
            elif lo is None:
                bound, side = f"below {hi:.2g} g/cm³ (no lower bound)", "upper"
            else:
                bound, side = f"above {lo:.2g} g/cm³ (no upper bound)", "lower"
            disp = f"< {hi:.2g}" if side == "upper" else f"> {lo:.2g}" if side == "lower" else "unconstrained"
            self.density_bound = f"68% range: {bound}"
            self._put(Parameter(**common, value=round(best, 3), reliability=UNRELIABLE, uncertainty=None, display=disp,
                                reason=f"The light curve alone constrains the stellar density only to {bound} (68%). "
                                       "Higher-SNR or shorter-cadence photometry that resolves ingress and egress is "
                                       "needed for an independent value."),
                      np.full(self.n, np.nan), {"stellar_density_transit"})
            return
        sig_up, sig_lo = math.log(hi / best), math.log(best / lo)
        z = self.rng.standard_normal(self.n)
        samples = best * np.exp(np.where(z > 0, z * sig_up, z * sig_lo))
        rv, rl, ru, disp = format_measurement(best, best - lo, hi - best)
        rel = max(hi - best, best - lo) / best
        reliable = rel <= self.cfg.low_confidence_relative_uncertainty
        reason = "" if reliable else (
            f"The light curve alone constrains it only to {lo:.2g}-{hi:.2g} g/cm³ (68%): b and a/R* are degenerate "
            f"at this SNR/cadence. Relative uncertainty exceeds {self.cfg.low_confidence_relative_uncertainty:.0%}; "
            "higher-SNR or shorter-cadence photometry would tighten it.")
        self._put(Parameter(**common, value=rv, reliability=RELIABLE if reliable else LOW,
                            uncertainty=Uncertainty(rl, ru, "profile_likelihood", "68% (Delta chi^2 <= 1)"),
                            reason=reason, display=disp), samples, set())

    # -- validation helpers -------------------------------------------------
    def _sym(self, name):
        p = self.params[name]
        return symmetric_sigma(p.uncertainty.upper, p.uncertainty.lower) if p.uncertainty else None

    def _rel_err(self, name):
        s = self._sym(name)
        v = self._value(name)
        return None if s is None or not v else s / abs(v)

    def _analytic_mass_sigma(self, v):
        m = float(physics.stellar_mass_from_logg_radius(v["stellar_logg"], v["stellar_radius"]))
        g = 10 ** v["stellar_logg"]
        sl = self._sym("stellar_logg")
        return analytic_power_law(m, [(g, 1, log10_sigma(g, sl) if sl is not None else None),
                                      (v["stellar_radius"], 2, self._sym("stellar_radius"))])

    def _grazing(self) -> bool:
        if not (self._ok("radius_ratio") and self._ok("impact_parameter")):
            return False
        return self._value("impact_parameter") > 1 - self._value("radius_ratio")

    def _validate_radius(self, value, samples):
        msgs, rel, reason = [], RELIABLE, ""
        if value > 22.4:
            rel, reason = UNRELIABLE, ("Radius exceeds ~2 R_Jup, larger than any known planet: likely a stellar "
                                       "companion, a blend, or an incorrect stellar radius.")
            msgs.append("Rp > 22.4 R⊕: outside the planetary regime.")
        elif value < 0.3:
            rel, reason = LOW, "Radius below 0.3 R⊕ is at the edge of Kepler sensitivity; verify the detection."
        else:
            msgs.append("Radius within the planetary regime (0.3-22.4 R⊕).")
        return rel, msgs, reason

    # -- consistency checks ---------------------------------------------------
    def consistency_checks(self):
        cfg = self.cfg
        # Transit-derived vs catalogue stellar density -- only for a
        # significant transit (a non-detection has no geometry to test).
        detected = self._ok("transit_snr") and self.params["transit_snr"].reliability == RELIABLE
        if not detected and self._ok("stellar_density"):
            if self._ok("transit_snr"):
                self.checks.append({
                    "check": "stellar_density", "label": "Transit-derived vs catalogue stellar density",
                    "consistent": None,
                    "note": f"Not evaluated: the transit is not significant (model-fit SNR "
                            f"{self.params['transit_snr'].display} < {cfg.snr_detection_threshold}), so its shape "
                            "says nothing reliable about the stellar density.",
                })
        elif self._ok("stellar_density_transit") and self._ok("stellar_density") \
                and self.params["stellar_density_transit"].reliability != UNRELIABLE:
            a, b = self.samples["stellar_density_transit"], self.samples["stellar_density"]
            ratio = summarize(a / b)
            if ratio:
                v, lo, hi = ratio
                sig = (v - 1) / (lo if v > 1 else hi) if (lo and hi) else None
                consistent = sig is None or abs(sig) < cfg.tension_sigma
                self.checks.append({
                    "check": "stellar_density", "label": "Transit-derived vs catalogue stellar density",
                    "ratio": round(v, 3), "ratio_interval": [round(v - lo, 3), round(v + hi, 3)],
                    "tension_sigma": None if sig is None else round(sig, 1), "consistent": consistent,
                    # A loosely bounded transit-only density can only detect large discrepancies.
                    "strength": "strong" if self.params["stellar_density_transit"].reliability == RELIABLE else "weak",
                    "note": (("Weak test: the light curve alone only loosely constrains the stellar density, so only a "
                              "large discrepancy could be detected. "
                              if self.params["stellar_density_transit"].reliability != RELIABLE else "") +
                             f"Transit-only density {self.params['stellar_density_transit'].display} g/cm³ vs "
                             f"catalogue {self.params['stellar_density'].display} g/cm³. "
                             "Agreement supports a circular orbit around the catalogued star. A discrepancy can indicate "
                             "an eccentric orbit (photo-eccentric effect), a diluted/blended signal, a wrong host star, "
                             "or inaccurate catalogue stellar parameters. Neither value is overwritten."),
                })
                if not consistent:
                    self.warnings.append(f"Transit-derived stellar density differs from the catalogue value by "
                                         f"{abs(sig):.1f} sigma (ratio {v:.2f}); stellar parameters flagged for review.")
        elif self._ok("stellar_density") and (getattr(self, "density_bound", None)
                                              or self._ok("stellar_density_transit")):
            self.checks.append({
                "check": "stellar_density", "label": "Transit-derived vs catalogue stellar density",
                "consistent": None,
                "note": "Not evaluated: the light curve alone does not bound the stellar density at this "
                        f"SNR/cadence ({getattr(self, 'density_bound', 'b and a/R* are degenerate')}), "
                        "so no independent comparison with the catalogue is possible. The catalogue density is "
                        "neither confirmed nor contradicted.",
            })
        # Overridden stellar mass vs log g / radius
        if ("stellar_mass" in self.overrides or (self._ok("stellar_mass") and self.params["stellar_mass"].provenance == CATALOG)) \
                and self._ok("stellar_logg") and self._ok("stellar_radius"):
            implied = float(physics.logg_from_mass_radius(self._value("stellar_mass"), self._value("stellar_radius")))
            catalog_logg = self._value("stellar_logg")
            sl = self._sym("stellar_logg") or 0.1
            diff = (implied - catalog_logg) / sl
            ok = abs(diff) < cfg.tension_sigma
            overridden = "stellar_mass" in self.overrides
            self.checks.append({"check": "stellar_mass_logg",
                                "label": "Override mass vs log g and radius" if overridden else
                                         "Catalogue stellar mass vs log g and radius",
                                "implied_logg": round(implied, 3), "logg": catalog_logg,
                                "tension_sigma": round(diff, 1), "consistent": ok,
                                "note": f"log g implied by the {'overridden' if overridden else 'catalogue'} mass and "
                                        "the stellar radius, compared with the log g in use."})
            if not ok:
                self.warnings.append(f"The {'overridden' if overridden else 'catalogue'} stellar mass is inconsistent "
                                     "with log g and radius; flagged for review.")
        if "stellar_luminosity" in self.overrides and self._ok("stellar_radius") and self._ok("stellar_teff"):
            sb = float(physics.stellar_luminosity(self._value("stellar_radius"), self._value("stellar_teff")))
            ratio = self._value("stellar_luminosity") / sb
            ok = 0.67 < ratio < 1.5
            self.checks.append({"check": "stellar_luminosity", "label": "Override luminosity vs Stefan-Boltzmann",
                                "ratio": round(ratio, 3), "consistent": ok,
                                "note": "Overridden luminosity divided by R*^2 Teff^4 (tolerance 0.67-1.5)."})
            if not ok:
                self.warnings.append("The overridden luminosity is inconsistent with the stellar radius and Teff.")
        # Period from individual transit times vs global fit
        eph = self.fit.get("ephemeris")
        if eph and self.fit_ok and self.fit.get("errors", {}).get("period"):
            dp = eph["period"] - self.fit["params"]["period"]
            sig = math.hypot(eph["period_error"], self.fit["errors"]["period"])
            ok = abs(dp) < cfg.tension_sigma * sig
            self.checks.append({"check": "ephemeris_period", "label": "Linear-ephemeris vs global-fit period",
                                "difference_days": dp, "tension_sigma": round(dp / sig, 1), "consistent": ok,
                                "note": "Period from individually timed transits compared with the global fit."})

    def catalog_comparison(self) -> list[dict]:
        reference = (self.inputs.get("catalog") or {}).get("reference") or {}
        if not reference:
            return []
        out = []
        pairs = [("orbital_period", "koi_period"), ("transit_depth", "koi_depth"),
                 ("transit_duration", "koi_duration"), ("impact_parameter", "koi_impact"),
                 ("planet_radius", "koi_prad"), ("equilibrium_temperature", "koi_teq"), ("insolation", "koi_insol")]
        for name, column in pairs:
            ref = reference.get(name)
            mine = self.params.get(name)
            if not ref or ref.get("value") is None or mine is None or mine.status != STATUS_COMPUTED:
                continue
            if mine.provenance == CATALOG:
                continue  # this value *is* the catalogue value
            cv, mv = ref["value"], mine.value
            sig_c = symmetric_sigma(ref.get("err_plus"), ref.get("err_minus"))
            sig_m = symmetric_sigma(mine.uncertainty.upper, mine.uncertainty.lower) if mine.uncertainty else None
            sig = math.hypot(sig_c or 0.0, sig_m or 0.0)
            tension = (mv - cv) / sig if sig > 0 else None
            entry = {"parameter": name, "label": mine.label, "unit": mine.unit, "engine_value": mv,
                     "catalog_value": cv, "catalog_column": column,
                     "catalog_uncertainty": [ref.get("err_minus"), ref.get("err_plus")],
                     "ratio": round(mv / cv, 4) if cv else None,
                     "tension_sigma": None if tension is None else round(tension, 1),
                     "consistent": None if tension is None else abs(tension) < self.cfg.tension_sigma, "note": ""}
            if name == "orbital_period" and cv:
                r = mv / cv
                for m in (2, 3, 0.5, 1 / 3):
                    if abs(r - m) < 0.01 * m:
                        entry["note"] = (f"Light-curve period is ~{m:g}x the catalogue period: a likely period alias "
                                         "of the same signal.")
                        self.warnings.append("The light-curve period appears to be an alias of the catalogue period "
                                             f"({r:.3f}x); dependent quantities use the light-curve period.")
                        break
                else:
                    if entry["consistent"] is False and abs(r - 1) > 0.01:
                        entry["note"] = "The light-curve period does not match the catalogue object's period."
                        self.warnings.append("The light-curve period does not match the KOI catalogue period of the "
                                             "resolved object: verify the Object ID and the detected signal.")
            if name == "equilibrium_temperature":
                entry["note"] = ("NASA koi_teq assumes Bond albedo 0.3 and full redistribution"
                                 + ("" if (self.cfg.bond_albedo == 0.3 and self.cfg.heat_redistribution == "full")
                                    else "; this report uses different assumptions") + ".")
            if name == "transit_depth":
                entry["note"] = "Catalogue depth is from NASA's own transit fit; the BLS-seeded fit here is independent."
            out.append(entry)
        return out


def _dedupe_sentences(reasons: list[str]) -> str:
    """Joins reasons inherited from several inputs, keeping each sentence once."""
    sentences = re.split(r"(?<=[.;])\s+", " ".join(r for r in reasons if r))
    return " ".join(dict.fromkeys(s for s in sentences if s))


def bls_duration(fit: dict) -> float | None:
    d = (fit.get("bls") or {}).get("duration_hours")
    return d if d and d > 0 else None


CORE_PARAMETERS = ("orbital_period", "radius_ratio", "planet_radius", "semi_major_axis",
                   "equilibrium_temperature", "insolation")


def compute_report(inputs: dict, overrides: dict | None = None, config: dict | CharacterizationConfig | None = None) -> dict:
    """Public, deterministic computation: input snapshot + overrides +
    config -> serialisable report dict."""
    cfg = config if isinstance(config, CharacterizationConfig) else CharacterizationConfig.from_dict(config)
    ovs = normalize_overrides(overrides)
    eng = _Engine(inputs, ovs, cfg)
    eng.build_stellar_inputs()
    eng.build_transit_inputs()
    eng.build_derived()
    eng.consistency_checks()
    comparison = eng.catalog_comparison()

    values = {n: eng._value(n) for n in eng.params}
    samples = {n: (eng.samples.get(n) if eng._ok(n) else None) for n in eng.params}
    mass_prov = eng.params["planet_mass"].provenance if "planet_mass" in eng.params else None
    classifications = [c.to_dict() for c in classify(values, samples, mass_prov)]

    # Overrides bookkeeping
    overridden = set(ovs)
    recomputed = sorted(n for n, p in eng.params.items() if p.depends_on_override and n not in overridden)
    recomputed_cls = sorted(c["name"] for c in classifications
                            if set(c["depends_on"]) & (overridden | set(recomputed)))

    # Missing-input explanations
    texts = assumption_texts(cfg)
    missing_inputs = []
    for name, p in eng.params.items():
        if p.status == STATUS_COMPUTED or p.missing_inputs:
            continue  # computed, or unavailable only because of an upstream gap (explained there)
        required_for = sorted(n for n, q in eng.params.items() if name in _transitive_missing(eng.params, n))
        missing_inputs.append({"parameter": name, "label": p.label, "reason": p.reason,
                               "required_for": required_for, "overridable": name in OVERRIDABLE})

    fit = inputs.get("transit_fit") or {}
    status, message = _overall_status(eng, fit)
    core = [eng.params[n] for n in CORE_PARAMETERS if n in eng.params and eng._ok(n)]
    reliability = worst_reliability(*(p.reliability for p in core)) if core else NOT_ASSESSED
    used_assumptions = sorted({a for p in eng.params.values() for a in p.assumptions})

    warnings = list(dict.fromkeys(list(fit.get("warnings") or []) + eng.warnings +
                                  ([eng.fit_reason] if eng.fit_reason else [])))
    report = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": inputs.get("candidate") or {},
        "status": status,
        "status_message": message,
        "reliability": reliability,
        "parameters": {n: p.to_dict() for n, p in eng.params.items()},
        "sections": SECTIONS,
        "classifications": classifications,
        "transit_fit": _fit_diagnostics(fit),
        "transit_timing": _timing(fit),
        "consistency_checks": eng.checks,
        "catalog_comparison": comparison,
        "assumptions": [{"id": a, "text": texts[a]} for a in used_assumptions if a in texts],
        "missing_inputs": missing_inputs,
        "warnings": warnings,
        "overrides": {
            "applied": {n: {"value": v["value"], "err_plus": v["err_plus"], "err_minus": v["err_minus"],
                            "note": v["note"]} for n, v in ovs.items()},
            "recomputed_outputs": recomputed,
            "recomputed_classifications": recomputed_cls,
            "overridable_parameters": {n: {"min": lo, "max": hi, "unit": PARAM_META[n][1],
                                           "label": PARAM_META[n][0]} for n, (lo, hi) in OVERRIDABLE.items()},
        },
        "config": {"bond_albedo": cfg.bond_albedo, "heat_redistribution": cfg.heat_redistribution,
                   "mc_samples": cfg.mc_samples, "random_seed": cfg.random_seed,
                   "snr_detection_threshold": cfg.snr_detection_threshold},
        "provenance_categories": {
            "catalog": "Local NASA Exoplanet Archive KOI catalogue value.",
            "observed": "Measured directly from the light curve without a physical model.",
            "fitted": "Parameter of (or computed directly from) the transit-model fit.",
            "derived": "Computed from other parameters through a physical relation.",
            "model_estimated": "From an empirical/statistical model; an estimate, not a measurement.",
            "manual_override": "Supplied by an expert, replacing the automatic value.",
            "assumed": "Adopted by assumption; never measured.",
            "unavailable": "Could not be determined; reported as null.",
        },
    }
    return report


def _transitive_missing(params: dict[str, Parameter], name: str, seen=None) -> set[str]:
    seen = seen or set()
    p = params.get(name)
    if p is None or name in seen:
        return set()
    seen.add(name)
    out = set(p.missing_inputs)
    for m in p.missing_inputs:
        out |= _transitive_missing(params, m, seen)
    return out


def _overall_status(eng: _Engine, fit: dict) -> tuple[str, str]:
    if fit.get("status") == "no_transit":
        return "no_transit", ("No transit signal was detected, so planetary properties cannot be characterized. "
                              "Stellar properties are still reported where available.")
    missing = [eng.params[n].label for n in CORE_PARAMETERS if n in eng.params and not eng._ok(n)]
    if not fit.get("status") == "fitted":
        prefix = f"The transit-model fit failed ({fit.get('message', 'unknown reason')}). "
    else:
        prefix = ""
    if not missing:
        return "complete", prefix + "All core characterization parameters were computed."
    return "partial", prefix + f"Computed with gaps: {', '.join(missing)} unavailable (see missing inputs)."


def _fit_diagnostics(fit: dict) -> dict:
    keys = ("status", "message", "converged", "n_function_evals", "n_points", "n_in_transit", "n_transits_with_data",
            "chi2", "dof", "reduced_chi2", "beta_red_noise", "noise_per_point_ppm", "residual_rms_ppm",
            "params_at_bounds", "limb_darkening", "exposure_days", "supersample", "decimated", "period_constrained",
            "bls", "snr", "seed_source", "folded")
    out = {k: fit.get(k) for k in keys}
    out["method"] = ("Bounded least-squares fit of a quadratic-limb-darkened circular-orbit transit model to locally "
                     "detrended windows around each transit; covariance from the Jacobian, inflated by reduced chi^2 "
                     "and the red-noise factor beta.")
    if fit.get("bls"):
        out["bls_note"] = ("The transit-search (BLS) SNR is the box-depth signal-to-noise ratio, depth / (sigma "
                           "sqrt(1/N_in + 1/N_out)), assuming white noise. The model-fit SNR above uses the fitted "
                           "limb-darkened mid-transit depth (deeper than the box average) and inflates the noise by "
                           "the red-noise factor beta, so the two differ; neither is a probability.")
    return out


def _timing(fit: dict) -> dict:
    times = fit.get("transit_times") or []
    eph = fit.get("ephemeris")
    return {
        "available": bool(eph),
        "n_timed_transits": len(times),
        "transits": [{"epoch": t["epoch"], "time": t["time"], "error_minutes": t["error"] * 1440.0,
                      "o_minus_c_minutes": None if t.get("o_minus_c") is None else t["o_minus_c"] * 1440.0,
                      "n_points": t["n_points"]} for t in times],
        "ephemeris": eph,
        "ttv_test_available": bool(eph and eph.get("dof", 0) > 0),
        "assessment": fit.get("timing_assessment", "") or "Transit timing requires a successful transit fit.",
    }
