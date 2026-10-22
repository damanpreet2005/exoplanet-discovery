"""
Planet Characterization Engine: engine, provenance, overrides, catalogue
integration, serialisation and API tests.

Fixture: a synthetic light curve of a Kepler-227 b-like transit (injected
with the engine's validated transit model at the KOI catalogue's period and
epoch, k = 0.0225, b = 0.15, and a/R* = 19.78 -- the value Kepler's third
law gives for the catalogue star, so the injected orbit is physically
consistent with it -- Kepler long cadence, 150 ppm white noise) characterized
against the real KOI catalogue row K00752.01 (Teff 5455 K, log g 4.467,
R* 0.927 R☉). The injected k, b, period and the catalogue's stellar values
are the reference truth.
"""
import copy
import io
import json
import math
import re

import numpy as np
import pytest

from app.characterization import (
    CharacterizationInputError, OverrideValidationError, characterize_light_curve, recompute_characterization,
)
from app.characterization.engine import (
    DEPENDENCY_GRAPH, OVERRIDABLE, _assert_acyclic, downstream_of, overrides_from_model_features,
)
from app.characterization.models import PROVENANCES
from app.characterization.planet_characterization import build_inputs, catalog_stellar_density
from app.characterization.transit_model import transit_flux
from app.lightcurve_extraction import compute_feature_vector
from app.stellar_catalog_service import resolve_object_id

TRUTH = dict(t0=170.5387, period=9.488036, k=0.0225, a_rs=19.78, b=0.15)
R_SUN_IN_EARTH = 6.957e8 / 6.371e6
REQUIRED_KEYS = {"name", "label", "value", "unit", "provenance", "status", "reliability", "uncertainty", "method",
                 "assumptions", "depends_on", "validation", "missing_inputs", "reason", "depends_on_override",
                 "original", "display"}


def _lightcurve(seed=3, baseline=100.0):
    rng = np.random.default_rng(seed)
    t = np.arange(130.0, 130.0 + baseline, 0.0204)
    f = transit_flux(t, TRUTH["t0"], TRUTH["period"], TRUTH["k"], TRUTH["a_rs"], TRUTH["b"], 0.4, 0.26, 0.0204, 7)
    return t, f + rng.normal(0.0, 1.5e-4, t.size)


@pytest.fixture(scope="module")
def lc():
    t, f = _lightcurve()
    return t, f, compute_feature_vector(t, f).bls


@pytest.fixture(scope="module")
def sc_lc():
    """Short-cadence (1-min, 40-day) version of the same planet: the ~5-min
    ingress spans several exposures, so the transit shape is resolved and the
    light-curve-only stellar density is constrained."""
    rng = np.random.default_rng(7)
    t = np.arange(150.0, 190.0, 0.000694)
    f = transit_flux(t, TRUTH["t0"], TRUTH["period"], TRUTH["k"], TRUTH["a_rs"], TRUTH["b"], 0.4, 0.26)
    f = f + rng.normal(0.0, 1.5e-4, t.size)
    return t, f, compute_feature_vector(t, f).bls


@pytest.fixture(scope="module")
def sc_report(sc_lc):
    t, f, bls = sc_lc
    return characterize_light_curve(t, f, bls, resolve_object_id("K00752.01"), "K00752.01")


@pytest.fixture(scope="module")
def report(lc):
    t, f, bls = lc
    return characterize_light_curve(t, f, bls, resolve_object_id("K00752.01"), "K00752.01")


def P(rep, name):
    return rep["parameters"][name]


# ---- report structure, provenance, serialisation -------------------------------

def test_complete_report_with_every_parameter_fully_attributed(report):
    assert report["status"] == "complete"
    assert report["candidate"]["kepoi_name"] == "K00752.01"
    for name, p in report["parameters"].items():
        assert REQUIRED_KEYS <= set(p), name
        assert p["provenance"] in PROVENANCES, name
        if p["status"] == "computed":
            assert p["value"] is not None and p["unit"] is not None
        else:
            assert p["value"] is None and p["provenance"] == "unavailable"  # never 0 for missing data
    assert {s["id"] for s in report["sections"]} == {"transit_signal", "planet", "orbit", "thermal", "host_star"}


def test_report_is_json_serialisable_and_round_trips(report):
    text = json.dumps(report)
    back = json.loads(text)
    assert back["parameters"]["planet_radius"]["value"] == report["parameters"]["planet_radius"]["value"]
    assert "NaN" not in text and "Infinity" not in text


def test_provenance_categories(report):
    assert P(report, "stellar_teff")["provenance"] == "catalog"
    assert P(report, "orbital_period")["provenance"] == "fitted"
    assert P(report, "radius_ratio")["provenance"] == "fitted"
    assert P(report, "transit_depth_bls")["provenance"] == "observed"
    assert P(report, "planet_radius")["provenance"] == "derived"
    assert P(report, "planet_mass")["provenance"] == "model_estimated"
    assert P(report, "eccentricity")["provenance"] == "assumed"
    assert P(report, "stellar_metallicity")["provenance"] == "unavailable"


def test_ml_features_are_not_characterization_parameters(report):
    # The 17-feature ML vector is a separate representation.
    assert not any(name.startswith("koi_") for name in report["parameters"])


def test_deterministic_with_fixed_seed(lc):
    t, f, bls = lc
    a = characterize_light_curve(t, f, bls, resolve_object_id("K00752.01"), "K00752.01")
    b = characterize_light_curve(t, f, bls, resolve_object_id("K00752.01"), "K00752.01")
    for name in a["parameters"]:
        assert a["parameters"][name]["value"] == b["parameters"][name]["value"]
        assert a["parameters"][name]["uncertainty"] == b["parameters"][name]["uncertainty"]


# ---- scientific values against the injected truth / catalogue -------------------

def test_transit_parameters_recover_injection(report):
    period = P(report, "orbital_period")
    assert abs(period["value"] - TRUTH["period"]) < 3 * period["uncertainty"]["upper"]
    k = P(report, "radius_ratio")
    assert abs(k["value"] - TRUTH["k"]) < 3 * max(k["uncertainty"]["lower"], k["uncertainty"]["upper"])
    assert P(report, "transit_snr")["value"] > 20
    assert P(report, "transit_snr")["reliability"] == "reliable"


def test_stellar_density_prior_constrains_geometry(report):
    """Without a prior the impact parameter is degenerate with a/R* at this
    SNR and cadence; the catalogue stellar density breaks the degeneracy."""
    fit = report["inputs"]["transit_fit"]
    assert fit["stellar_density_prior"]["value"] == pytest.approx(1.63, rel=0.02)
    assert fit["unconstrained"]["errors"]["a_rs"] > 5 * fit["errors"]["a_rs"]
    b = P(report, "impact_parameter")
    assert b["reliability"] == "reliable"
    assert abs(b["value"] - TRUTH["b"]) < 2.5 * b["uncertainty"]["upper"]
    t14_true = TRUTH["period"] / math.pi * math.asin(
        math.sqrt((1 + TRUTH["k"]) ** 2 - TRUTH["b"] ** 2) / TRUTH["a_rs"]) * 24
    t14 = P(report, "transit_duration")
    assert t14["reliability"] == "reliable"
    assert t14["value"] == pytest.approx(t14_true, rel=0.05)
    for name in ("transit_duration_full", "ingress_duration", "inclination", "a_over_rstar", "transit_depth"):
        assert P(report, name)["reliability"] == "reliable", name
    assert "stellar_density_prior" in P(report, "impact_parameter")["assumptions"]


def test_density_check_uses_the_prior_free_fit(sc_report):
    """The transit-vs-catalogue density check must not read the
    prior-constrained a/R* (that would agree by construction)."""
    report = sc_report
    rho_t = P(report, "stellar_density_transit")
    assert "prior-free" in rho_t["method"]
    check = next(c for c in report["consistency_checks"] if c["check"] == "stellar_density")
    if rho_t["reliability"] == "unreliable":
        assert check["consistent"] is None and "Not evaluated" in check["note"]
    else:
        assert isinstance(check["consistent"], bool)


def test_no_prior_without_stellar_uncertainties(lc):
    t, f, bls = lc
    res = resolve_object_id("K00752.01")
    inputs = build_inputs(t, f, bls, res, "K00752.01")
    stellar = inputs["catalog"]["stellar"]
    stellar["stellar_logg"] = {**stellar["stellar_logg"], "err_plus": None, "err_minus": None}
    assert catalog_stellar_density(inputs["catalog"]) is None


def test_archive_values_fill_metallicity_distance_and_measured_mass(report):
    inputs = copy.deepcopy(report["inputs"])
    src = "NASA Exoplanet Archive (test)"
    inputs["catalog"]["archive"] = {
        "stellar": {"stellar_metallicity": {"value": 0.14, "err_plus": 0.15, "err_minus": 0.15, "source": src},
                    "distance": {"value": 1083.06, "err_plus": 29.67, "err_minus": 29.67, "source": src}},
        "planet": {"planet_mass": {"value": 8.0, "err_plus": 1.0, "err_minus": 1.0, "source": src}},
        "notes": [],
    }
    rep = recompute_characterization(inputs)
    assert P(rep, "stellar_metallicity")["status"] == "computed"
    assert P(rep, "stellar_metallicity")["provenance"] == "catalog"
    assert P(rep, "distance")["value"] == pytest.approx(1083.06)
    mass = P(rep, "planet_mass")
    assert mass["provenance"] == "catalog" and mass["reliability"] == "reliable"
    for name in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        assert "model-estimated" not in P(rep, name)["reason"]
    assert all(m["parameter"] not in ("stellar_metallicity", "distance") for m in rep["missing_inputs"])


def test_archive_estimated_mass_is_not_used_as_a_measurement(monkeypatch):
    from app.characterization import archive_enrichment
    monkeypatch.setattr(archive_enrichment, "_CACHE", {})
    monkeypatch.setattr(archive_enrichment, "query_dr25_stellar",
                        lambda kepid: [{"kepid": kepid, "feh": 0.14, "feh_err1": 0.15, "feh_err2": -0.15,
                                        "dist": 1014.0, "dist_err1": 131.0, "dist_err2": -84.0}])
    monkeypatch.setattr(archive_enrichment, "query_confirmed_planet",
                        lambda name: [{"pl_name": name, "pl_bmasse": 9.85, "pl_bmasseerr1": None, "pl_bmasseerr2": None,
                                       "pl_bmassprov": "M-R relationship", "sy_dist": 1083.06, "sy_disterr1": 29.67,
                                       "sy_disterr2": -29.67}])
    out = archive_enrichment.lookup(10797460, "Kepler-227 b")
    assert "planet_mass" not in out["planet"]
    assert any("M-R relationship" in n for n in out["notes"])
    assert out["stellar"]["distance"]["value"] == pytest.approx(1083.06)       # Gaia distance preferred
    assert out["stellar"]["stellar_metallicity"]["err_minus"] == pytest.approx(0.15)


def test_archive_failure_leaves_values_unavailable(monkeypatch):
    from app.characterization import archive_enrichment
    from app.nasa_exoplanet_archive_client import NasaApiTimeoutError

    def boom(*_):
        raise NasaApiTimeoutError("timed out")
    monkeypatch.setattr(archive_enrichment, "_CACHE", {})
    monkeypatch.setattr(archive_enrichment, "query_dr25_stellar", boom)
    monkeypatch.setattr(archive_enrichment, "query_confirmed_planet", boom)
    out = archive_enrichment.lookup(10797460, "Kepler-227 b")
    assert out["stellar"] == {} and out["planet"] == {}
    assert len(out["notes"]) == 2


def test_planet_radius_uses_fitted_ratio_and_catalog_radius(report):
    rp = P(report, "planet_radius")
    expected = P(report, "radius_ratio")["value"] * 0.927 * R_SUN_IN_EARTH
    # The Monte Carlo median sits ~3% above k x R*: R*'s asymmetric catalogue
    # interval (+0.105 / -0.061) skews the product upward.
    assert rp["value"] == pytest.approx(expected, rel=0.04)
    assert set(rp["depends_on"]) == {"radius_ratio", "stellar_radius"}
    # Stellar-radius uncertainty (+0.105/-0.061) dominates: interval is asymmetric.
    assert rp["uncertainty"]["upper"] > rp["uncertainty"]["lower"]
    assert rp["uncertainty"]["complete"] is True


def test_depth_reported_in_ppm_and_fraction(report):
    d = P(report, "transit_depth")
    assert d["unit"] == "ppm"
    frac = d["alternate_units"][0]
    assert frac["unit"] == "fraction" and frac["value"] == pytest.approx(d["value"] / 1e6)


def test_orbit_and_thermal_match_nasa_conventions(report):
    # NASA koi_teq for K00752.01 is 793 K (A = 0.3, full redistribution).
    teq = P(report, "equilibrium_temperature")
    assert teq["value"] == pytest.approx(793, rel=0.03)
    assert "bond_albedo" in teq["assumptions"] and "heat_redistribution" in teq["assumptions"]
    assert teq["systematic_range"]["min"] < teq["value"] < teq["systematic_range"]["max"]
    assert P(report, "insolation")["value"] == pytest.approx(93.6, rel=0.1)
    assert P(report, "semi_major_axis")["value"] == pytest.approx(0.0852, rel=0.03)
    assert P(report, "stellar_mass")["uncertainty"]["method"] == "analytic_first_order"
    assert P(report, "semi_major_axis")["uncertainty"]["method"] == "monte_carlo"


def test_circular_orbit_is_recorded_not_silent(report):
    ecc = P(report, "eccentricity")
    assert ecc["value"] == 0.0 and ecc["provenance"] == "assumed"
    assert "circular_orbit" in P(report, "inclination")["assumptions"]
    assert any(a["id"] == "circular_orbit" for a in report["assumptions"])


def test_model_mass_is_labelled_estimate(report):
    m = P(report, "planet_mass")
    assert m["provenance"] == "model_estimated" and m["reliability"] != "reliable"
    assert "ck17_mass_radius" in m["assumptions"]
    assert P(report, "planet_density")["provenance"] == "model_estimated"
    comp = next(c for c in report["classifications"] if c["name"] == "composition_candidate")
    assert any("mass is not measured" in c for c in comp["caveats"])


def test_classifications(report):
    cls = {c["name"]: c for c in report["classifications"]}
    assert cls["size_category"]["category"] == "Neptune-size"            # ~2.3 R_earth
    assert cls["thermal_regime"]["category"] == "Warm (400-1000 K)"
    assert cls["habitable_zone"]["category"].startswith("Interior")
    assert any("not evidence of habitability" in c for c in cls["habitable_zone"]["caveats"])
    probs = cls["size_category"]["probabilities"]
    assert sum(probs.values()) == pytest.approx(1.0, abs=0.02)


def test_catalog_comparison_and_consistency(report):
    comp = {c["parameter"]: c for c in report["catalog_comparison"]}
    assert comp["orbital_period"]["consistent"] is True
    assert comp["planet_radius"]["catalog_value"] == pytest.approx(2.26)
    checks = {c["check"]: c for c in report["consistency_checks"]}
    # Long cadence: the ~5-min ingress is far shorter than the 29.4-min exposure,
    # so the light curve cannot independently constrain the stellar density.
    assert checks["stellar_density"]["consistent"] is None
    assert "not resolved" in checks["stellar_density"]["note"]


def test_transit_timing_section(report):
    timing = report["transit_timing"]
    assert timing["available"] and timing["n_timed_transits"] >= 8
    assert timing["ttv_test_available"]
    assert all(t["error_minutes"] > 0 for t in timing["transits"])


def test_folded_light_curve_for_display(report):
    folded = report["transit_fit"]["folded"]
    n = len(folded["phase_hours"])
    assert n >= 5 and len(folded["flux_ppm"]) == len(folded["flux_err_ppm"]) == len(folded["n_per_bin"]) == n
    assert all(c >= 3 for c in folded["n_per_bin"])
    assert len(folded["model_phase_hours"]) == len(folded["model_flux_ppm"])
    # Binned data and model both dip at mid-transit by roughly the best-fit depth (ppm; the
    # reported transit_depth parameter is the Monte Carlo median, so it is not used here).
    depth_ppm = report["inputs"]["transit_fit"]["depth"] * 1e6
    mid = min(range(n), key=lambda i: abs(folded["phase_hours"][i]))
    assert folded["flux_ppm"][mid] < -0.5 * depth_ppm
    assert min(folded["model_flux_ppm"]) == pytest.approx(-depth_ppm, rel=0.05)
    assert max(folded["model_flux_ppm"]) == pytest.approx(0.0, abs=1e-6)
    json.dumps(folded, allow_nan=False)


def test_folded_light_curve_survives_recompute(report):
    rep = recompute_characterization(report["inputs"], {"stellar_radius": {"value": 1.1}})
    assert rep["transit_fit"]["folded"] == report["transit_fit"]["folded"]


def test_missing_inputs_explained(report):
    missing = {m["parameter"]: m for m in report["missing_inputs"]}
    assert "stellar_metallicity" in missing and missing["stellar_metallicity"]["overridable"]
    assert "distance" in missing


# ---- missing / invalid inputs -------------------------------------------------

def test_invalid_object_id_characterizes_transit_only(lc):
    t, f, bls = lc
    rep = characterize_light_curve(t, f, bls, resolve_object_id("KIC 999999999"), "KIC 999999999")
    assert rep["status"] == "partial"
    rp = P(rep, "planet_radius")
    assert rp["value"] is None and "stellar_radius" in rp["missing_inputs"]
    # Transit-only quantities survive.
    for name in ("orbital_period", "radius_ratio", "a_over_rstar", "inclination"):
        assert P(rep, name)["status"] == "computed", name
    # At long cadence the ingress is unresolved, so even the transit-only density is not claimed.
    assert P(rep, "stellar_density_transit")["status"] == "unavailable"
    assert "shorter than half" in P(rep, "stellar_density_transit")["reason"]
    for name in ("semi_major_axis", "equilibrium_temperature", "insolation", "planet_mass"):
        assert P(rep, name)["value"] is None, name
    assert next(c for c in rep["classifications"] if c["name"] == "size_category")["status"] == "unavailable"
    missing = {m["parameter"]: m for m in rep["missing_inputs"]}
    assert "planet_radius" in missing["stellar_radius"]["required_for"]


def test_missing_stellar_mass_falls_back_to_transit_geometry(report):
    inputs = copy.deepcopy(report["inputs"])
    del inputs["catalog"]["stellar"]["stellar_logg"]
    rep = recompute_characterization(inputs)
    assert P(rep, "stellar_mass")["value"] is None
    a = P(rep, "semi_major_axis")
    assert a["status"] == "computed" and set(a["depends_on"]) == {"a_over_rstar", "stellar_radius"}
    assert a["value"] == pytest.approx(P(report, "semi_major_axis")["value"], rel=0.3)


def test_missing_stellar_radius_uncertainty_flags_incomplete_interval(report):
    inputs = copy.deepcopy(report["inputs"])
    inputs["catalog"]["stellar"]["stellar_radius"].update(err_plus=None, err_minus=None)
    rep = recompute_characterization(inputs)
    unc = P(rep, "planet_radius")["uncertainty"]
    assert unc["complete"] is False and "stellar_radius" in unc["excluded_inputs"]
    assert unc["upper"] < P(report, "planet_radius")["uncertainty"]["upper"]


def test_no_transit_status(report):
    inputs = copy.deepcopy(report["inputs"])
    inputs["transit_fit"] = {"status": "no_transit", "message": "No positive depth.", "bls": {}}
    inputs["light_curve"]["bls"]["depth_ppm"] = 0.0
    rep = recompute_characterization(inputs)
    assert rep["status"] == "no_transit"
    assert P(rep, "planet_radius")["value"] is None
    assert P(rep, "stellar_luminosity")["status"] == "computed"   # stellar part still characterized


def test_low_snr_marks_results_unreliable(report):
    inputs = copy.deepcopy(report["inputs"])
    inputs["transit_fit"]["snr"] = 4.0
    rep = recompute_characterization(inputs)
    assert P(rep, "transit_snr")["reliability"] == "unreliable"
    assert P(rep, "planet_radius")["reliability"] == "unreliable"
    assert P(rep, "planet_radius")["status"] == "computed"   # executed, but not reliable
    assert rep["reliability"] == "unreliable"


def test_single_transit_uses_catalog_period(report):
    inputs = copy.deepcopy(report["inputs"])
    fit = inputs["transit_fit"]
    idx = fit["fitted_names"].index("period")
    fit["fitted_names"].pop(idx)
    cov = np.delete(np.delete(np.array(fit["covariance"]), idx, 0), idx, 1)
    fit["covariance"] = cov.tolist()
    fit["errors"].pop("period")
    fit["period_constrained"] = False
    rep = recompute_characterization(inputs)
    assert P(rep, "orbital_period")["provenance"] == "catalog"
    assert P(rep, "a_over_rstar")["reliability"] == "unreliable"


def test_grazing_geometry_is_flagged(report):
    inputs = copy.deepcopy(report["inputs"])
    inputs["transit_fit"]["params"]["b"] = 0.99
    inputs["transit_fit"]["params"]["b2"] = 0.99 ** 2
    inputs["transit_fit"]["covariance"] = None
    inputs["transit_fit"]["errors"] = {}
    rep = recompute_characterization(inputs)
    assert P(rep, "transit_duration_full")["value"] is None
    assert P(rep, "radius_ratio")["reliability"] != "reliable"
    assert any("grazing" in w.lower() for w in rep["warnings"])


def test_failed_fit_falls_back_to_box_depth(report):
    inputs = copy.deepcopy(report["inputs"])
    inputs["transit_fit"] = {"status": "failed", "message": "Optimisation failed.", "bls": inputs["light_curve"]["bls"]}
    rep = recompute_characterization(inputs)
    k = P(rep, "radius_ratio")
    assert k["provenance"] == "derived" and k["reliability"] == "low_confidence"
    assert k["value"] == pytest.approx(math.sqrt(inputs["light_curve"]["bls"]["depth_ppm"] * 1e-6), rel=0.01)
    assert P(rep, "inclination")["value"] is None


def test_malformed_snapshot_rejected():
    with pytest.raises(CharacterizationInputError):
        recompute_characterization({"schema_version": 1})
    with pytest.raises(CharacterizationInputError):
        recompute_characterization([])


# ---- expert overrides -----------------------------------------------------------

def test_stellar_radius_override_recomputes_dependents(report):
    rep = recompute_characterization(report["inputs"], {"stellar_radius": {"value": 1.2, "uncertainty": 0.05}})
    sr = P(rep, "stellar_radius")
    assert sr["provenance"] == "manual_override" and sr["value"] == 1.2
    assert sr["original"]["value"] == 0.927 and sr["original"]["provenance"] == "catalog"
    rp = P(rep, "planet_radius")
    assert rp["value"] == pytest.approx(P(report, "radius_ratio")["value"] * 1.2 * R_SUN_IN_EARTH, rel=0.01)
    assert rp["depends_on_override"] == ["stellar_radius"]
    recomputed = set(rep["overrides"]["recomputed_outputs"])
    assert {"planet_radius", "stellar_luminosity", "stellar_mass", "semi_major_axis",
            "equilibrium_temperature"} <= recomputed
    assert "orbital_period" not in recomputed and "radius_ratio" not in recomputed
    assert "stellar_radius" not in recomputed  # overridden, not recomputed
    assert recomputed <= downstream_of({"stellar_radius"}) | {"planet_mass", "planet_density",
                                                              "planet_surface_gravity", "escape_velocity",
                                                              "orbital_velocity", "insolation"}


def test_restoring_automatic_values(report):
    overridden = recompute_characterization(report["inputs"], {"stellar_teff": 6000})
    restored = recompute_characterization(report["inputs"], {})
    assert P(overridden, "equilibrium_temperature")["value"] != P(report, "equilibrium_temperature")["value"]
    for name in report["parameters"]:
        assert P(restored, name)["value"] == P(report, name)["value"], name
    assert restored["overrides"]["applied"] == {}


def test_measured_mass_override(report):
    rep = recompute_characterization(report["inputs"], {"planet_mass": {"value": 8.0, "uncertainty": 1.0}})
    assert P(rep, "planet_mass")["provenance"] == "manual_override"
    dens = P(rep, "planet_density")
    assert dens["provenance"] == "derived"
    rp = P(rep, "planet_radius")["value"]
    assert dens["value"] == pytest.approx(5.51 * 8.0 / rp ** 3, rel=0.05)
    assert "negligible_planet_mass" not in P(rep, "semi_major_axis")["assumptions"]


def test_override_does_not_propagate_backwards(report):
    rep = recompute_characterization(report["inputs"], {"planet_radius": 3.0})
    assert P(rep, "stellar_radius")["value"] == P(report, "stellar_radius")["value"]
    assert P(rep, "radius_ratio")["value"] == P(report, "radius_ratio")["value"]
    assert P(rep, "planet_mass")["depends_on_override"] == ["planet_radius"]


def test_eccentricity_override_changes_geometry_and_flux(report):
    rep = recompute_characterization(report["inputs"], {"eccentricity": 0.3, "arg_periastron": 90.0})
    a_rs = P(rep, "a_over_rstar")
    assert a_rs["provenance"] == "derived" and a_rs["original"] is not None
    # a/R*_true = a/R*_circ * sqrt(1-e^2)/(1+e sin w)
    assert a_rs["value"] == pytest.approx(P(report, "a_over_rstar")["value"] * math.sqrt(1 - 0.09) / 1.3, rel=0.1)
    assert P(rep, "insolation")["value"] == pytest.approx(P(report, "insolation")["value"] / math.sqrt(1 - 0.09), rel=0.03)


def test_albedo_configuration(report):
    rep = recompute_characterization(report["inputs"], config={"bond_albedo": 0.0})
    ratio = P(rep, "equilibrium_temperature")["value"] / P(report, "equilibrium_temperature")["value"]
    assert ratio == pytest.approx((1 / 0.7) ** 0.25, rel=0.01)
    assert rep["config"]["bond_albedo"] == 0.0
    assert any("A = 0" in a["text"] for a in rep["assumptions"] if a["id"] == "bond_albedo")


@pytest.mark.parametrize("overrides", [
    {"stellar_radius": -1.0},
    {"stellar_radius": float("nan")},
    {"eccentricity": 1.0},
    {"transit_snr": 10.0},          # observed quantity, not overridable
    {"planet_density": 5.0},        # derived output with no override semantics
    {"stellar_teff": "hot"},
])
def test_invalid_overrides_rejected(report, overrides):
    with pytest.raises(OverrideValidationError):
        recompute_characterization(report["inputs"], overrides)


def test_invalid_config_rejected(report):
    with pytest.raises(OverrideValidationError):
        recompute_characterization(report["inputs"], config={"bond_albedo": 1.5})
    with pytest.raises(OverrideValidationError):
        recompute_characterization(report["inputs"], config={"heat_redistribution": "partial"})


def test_stellar_mass_override_inconsistent_with_logg_is_flagged(report):
    rep = recompute_characterization(report["inputs"], {"stellar_mass": 3.0})
    check = next(c for c in rep["consistency_checks"] if c["check"] == "stellar_mass_logg")
    assert check["consistent"] is False
    assert P(rep, "stellar_logg")["value"] == 4.467  # catalogue value preserved, not overwritten


def test_model_feature_form_edits_become_overrides():
    auto = {"koi_srad": 0.927, "koi_period": 9.488, "koi_steff": None, "koi_score": 0.9}
    submitted = {"koi_srad": 1.1, "koi_period": 9.488, "koi_steff": 5600, "koi_score": 0.5}
    ov = overrides_from_model_features(submitted, auto)
    assert set(ov) == {"stellar_radius", "stellar_teff"}   # unchanged/non-physical fields ignored
    assert ov["stellar_radius"]["value"] == 1.1


def test_dependency_graph_is_acyclic_and_cycles_are_detected():
    _assert_acyclic(DEPENDENCY_GRAPH)
    with pytest.raises(RuntimeError):
        _assert_acyclic({"a": ["b"], "b": ["a"]})
    assert set(OVERRIDABLE) - set(DEPENDENCY_GRAPH) - {"orbital_period", "transit_epoch", "radius_ratio",
                                                       "impact_parameter", "stellar_radius", "stellar_teff",
                                                       "stellar_logg", "stellar_metallicity", "distance",
                                                       "eccentricity", "arg_periastron"} == set()


# ---- catalogue identifiers ----------------------------------------------------

@pytest.mark.parametrize("identifier", ["010797460-01", "10797460-1", "TCE 010797460-01", "KIC 10797460 TCE 1"])
def test_tce_identifiers_resolve_to_single_koi(identifier):
    res = resolve_object_id(identifier)
    assert res.identifier_type == "tce"
    assert res.match_status == "matched_koi"
    assert res.matched_kepoi_name == "K00752.01"
    assert len(res.matched_rows) == 1


def test_tce_second_planet_and_missing_tce():
    assert resolve_object_id("010797460-02").matched_kepoi_name == "K00752.02"
    assert resolve_object_id("010797460-09").match_status == "not_found"


def test_kic_with_multiple_kois_uses_period_matched_reference(lc):
    t, f, bls = lc
    rep = characterize_light_curve(t, f, bls, resolve_object_id("KIC 10797460"), "KIC 10797460")
    assert rep["inputs"]["catalog"]["reference_source"] == "period_matched"
    assert rep["inputs"]["catalog"]["reference_koi"]["kepoi_name"] == "K00752.01"
    assert P(rep, "stellar_radius")["value"] == 0.927


# ---- API integration ------------------------------------------------------------

def _csv_bytes():
    t, f = _lightcurve()
    buf = io.StringIO()
    buf.write("time,flux\n")
    for ti, fi in zip(t, f):
        buf.write(f"{ti:.6f},{fi:.8f}\n")
    return buf.getvalue().encode()


@pytest.fixture(scope="module")
def upload(client):
    r = client.post("/predict/csv", files={"file": ("k227.csv", _csv_bytes(), "text/csv")},
                    data={"object_id": "K00752.01"})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_response_includes_characterization(upload):
    char = upload["characterization"]
    assert char["status"] == "complete"
    assert char["parameters"]["planet_radius"]["value"] > 0
    assert "inputs" in char
    # The ML feature report is untouched and separate.
    assert len(upload["features"]) == 17


def test_recompute_endpoint_with_overrides_and_cache(client, upload):
    body = {"inputs": upload["characterization"]["inputs"], "overrides": {"stellar_radius": 1.1}}
    r1 = client.post("/characterization/recompute", json=body)
    assert r1.status_code == 200, r1.text
    assert r1.json()["parameters"]["stellar_radius"]["provenance"] == "manual_override"
    assert r1.json()["cache_hit"] is False
    r2 = client.post("/characterization/recompute", json=body)
    assert r2.json()["cache_hit"] is True
    # A changed input invalidates the cache key.
    r3 = client.post("/characterization/recompute", json={**body, "overrides": {"stellar_radius": 1.2}})
    assert r3.json()["cache_hit"] is False


def test_recompute_endpoint_accepts_model_form_edits(client, upload):
    auto = {k: v["value"] for k, v in upload["features"].items()}
    submitted = {**auto, "koi_steff": 6000.0}
    r = client.post("/characterization/recompute", json={
        "inputs": upload["characterization"]["inputs"],
        "model_feature_edits": {"submitted": submitted, "automatic": auto}})
    assert r.status_code == 200
    rep = r.json()
    assert list(rep["overrides"]["applied"]) == ["stellar_teff"]
    assert "equilibrium_temperature" in rep["overrides"]["recomputed_outputs"]


def test_recompute_endpoint_rejects_invalid_override(client, upload):
    r = client.post("/characterization/recompute", json={"inputs": upload["characterization"]["inputs"],
                                                         "overrides": {"stellar_radius": -2}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CHARACTERIZATION_VALIDATION_ERROR"
    r = client.post("/characterization/recompute", json={"inputs": {"bad": 1}})
    assert r.status_code == 422


# ---- impact parameter fed to the ML features and Physics Validation ---------

def test_trapezoid_shape_estimate_is_biased_for_limb_darkened_transits(lc):
    """Why the shape estimate is no longer a feature source: it assumes no
    limb darkening and returns b ~ 0.96 for this b = 0.15 planet."""
    from app.lightcurve_extraction import estimate_impact_parameter
    t, f, bls = lc
    est = estimate_impact_parameter(t, f / np.median(f), bls)
    assert est.value is None or est.value > 0.8


def test_matched_koi_uses_the_catalogue_impact_parameter(lc):
    from app.feature_engine import extract_features
    t, f, _ = lc
    res = extract_features(t, f, "K00752.01")
    assert res.features["koi_impact"].status == "catalog"
    assert res.features["koi_impact"].value == pytest.approx(0.146)


def test_unmatched_star_takes_b_from_the_constrained_fit(lc, report):
    from app.feature_engine import apply_fitted_impact_parameter, extract_features
    t, f, _ = lc
    res = extract_features(t, f, None)               # no Object ID: no catalogue b
    assert res.features["koi_impact"].status == "unavailable"
    apply_fitted_impact_parameter(res, report)       # report used the density prior; b is reliable
    assert res.features["koi_impact"].source == "transit_model_fit"
    assert res.features["koi_impact"].value == pytest.approx(P(report, "impact_parameter")["value"])
    assert "koi_impact" not in res.missing_features


def test_confirmed_planet_passes_transit_duration_validation(lc):
    """End to end: the features extracted for this confirmed planet are
    physically self-consistent, so Stage 2's duration check passes."""
    from app.feature_engine import extract_features
    from app.physics_validation import run_physics_validation
    t, f, _ = lc
    res = extract_features(t, f, "K00752.01")
    report = run_physics_validation({c: fv.value for c, fv in res.features.items()}, "K00752.01").to_dict()
    duration = next(x for x in report["tests"] if x["test_id"] == "transit_duration")
    assert duration["status"] == "PASS", duration["summary"]


# ---- mass-dependent chain, transit-only density, confidence classification ----

def _with_archive_mass(report, value, err):
    inputs = copy.deepcopy(report["inputs"])
    inputs["catalog"]["archive"] = {"stellar": {}, "notes": [], "planet": {"planet_mass": {
        "value": value, "err_plus": err, "err_minus": err, "source": "NASA Exoplanet Archive (test)"}}}
    return recompute_characterization(inputs)


def test_measured_mass_is_catalogue_sourced_and_propagates_correctly(report):
    rep = _with_archive_mass(report, 6.0, 0.6)                 # a precise (10%) RV mass
    mass, radius = P(rep, "planet_mass"), P(rep, "planet_radius")
    assert mass["provenance"] == "catalog" and mass["reliability"] == "reliable"
    assert "Archive" in mass["source"]
    # Measured mass and transit radius are independent: first-order propagation
    # of rho = M / (4/3 pi R^3) gives sigma_rho/rho = sqrt(s_M^2 + 9 s_R^2).
    s_m = 0.1
    s_r = 0.5 * (radius["uncertainty"]["upper"] + radius["uncertainty"]["lower"]) / radius["value"]
    rho = P(rep, "planet_density")
    s_rho = 0.5 * (rho["uncertainty"]["upper"] + rho["uncertainty"]["lower"]) / rho["value"]
    assert s_rho == pytest.approx(math.sqrt(s_m ** 2 + 9 * s_r ** 2), rel=0.15)
    expected = 6.0 * 5.9722e24 / (4 / 3 * math.pi * (radius["value"] * 6.371e6) ** 3) / 1000
    assert rho["value"] == pytest.approx(expected, rel=0.05)
    assert rho["provenance"] == "derived"
    for name in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        assert "measured planet mass" in P(rep, name)["reason"]
        assert "model-estimated" not in P(rep, name)["reason"]


def test_imprecise_measured_mass_is_not_rated_reliable(report):
    """A catalogue value with a large uncertainty is low confidence like any
    other: previously only fitted values and overrides were checked."""
    rep = _with_archive_mass(report, 6.0, 4.0)
    mass = P(rep, "planet_mass")
    assert mass["provenance"] == "catalog"
    assert mass["reliability"] == "low_confidence"
    assert "Relative uncertainty exceeds 30%" in mass["reason"]
    assert P(rep, "planet_density")["reliability"] == "low_confidence"


def test_estimated_mass_is_labelled_and_explained(report):
    mass = P(report, "planet_mass")
    assert mass["provenance"] == "model_estimated" and mass["reliability"] == "low_confidence"
    assert "radial-velocity or transit-timing mass measurement" in mass["reason"]
    # Intrinsic scatter of the Neptunian branch, 0.146 dex in log R / slope 0.589, dominates log M.
    lo, hi = mass["uncertainty"]["lower"], mass["uncertainty"]["upper"]
    half_width_dex = 0.5 * (math.log10(mass["value"] + hi) - math.log10(mass["value"] - lo))
    assert half_width_dex == pytest.approx(0.146 / 0.589, rel=0.2)
    for name in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        p = P(report, name)
        assert p["provenance"] == "model_estimated" and p["reliability"] == "low_confidence"
        assert "model-estimated planet mass" in p["reason"] and "% of its uncertainty" in p["reason"]


def test_missing_mass_makes_dependents_unavailable_with_reason(report):
    rep = recompute_characterization(report["inputs"], {"planet_radius": {"value": 16.0, "uncertainty": 1.0}})
    mass = P(rep, "planet_mass")
    assert mass["status"] == "unavailable" and mass["value"] is None
    assert "radial-velocity mass" in mass["reason"]
    for name in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        p = P(rep, name)
        assert p["status"] == "unavailable" and p["value"] is None and p["reason"]


def test_uncertain_radius_widens_dependents_and_shifts_the_budget(report):
    rep = _with_archive_mass(report, 6.0, 0.6)
    wide = recompute_characterization(
        {**report["inputs"], "catalog": {**report["inputs"]["catalog"], "archive": {"stellar": {}, "notes": [],
         "planet": {"planet_mass": {"value": 6.0, "err_plus": 0.6, "err_minus": 0.6, "source": "test"}}}}},
        {"planet_radius": {"value": 2.3, "uncertainty": 0.6}})
    base_rho, wide_rho = P(rep, "planet_density"), P(wide, "planet_density")
    rel = lambda p: p["uncertainty"]["upper"] / p["value"]
    assert rel(wide_rho) > 2 * rel(base_rho)
    assert wide_rho["reliability"] == "low_confidence"
    assert "radius" in wide_rho["reason"]
    share_r = float(re.search(r"radius (\d+)%", wide_rho["reason"]).group(1))
    assert share_r > 80          # a 26% radius error, cubed, now dominates the density


def test_units_of_mass_dependent_quantities():
    from app.characterization import physics
    assert float(physics.planet_density(1.0, 1.0)) == pytest.approx(5.513, rel=1e-3)          # g/cm^3
    assert float(physics.planet_surface_gravity(1.0, 1.0)) == pytest.approx(9.82, rel=1e-3)   # m/s^2
    assert float(physics.escape_velocity_kms(1.0, 1.0)) == pytest.approx(11.19, rel=1e-3)     # km/s
    # Jupiter, 317.8 M_earth: bulk density uses the mean radius (10.97 R_earth) -> 1.33 g/cm^3;
    # gravity and escape velocity are quoted at the equatorial radius (11.21 R_earth) -> 24.8 m/s^2, 59.5 km/s.
    assert float(physics.planet_density(317.8, 10.97)) == pytest.approx(1.33, rel=0.02)
    assert float(physics.planet_surface_gravity(317.8, 11.21)) == pytest.approx(24.8, rel=0.02)
    assert float(physics.escape_velocity_kms(317.8, 11.21)) == pytest.approx(59.5, rel=0.02)


def test_transit_density_comes_from_the_prior_free_profile(sc_report):
    report = sc_report
    profile = report["inputs"]["transit_fit"]["unconstrained"]["density_profile"]
    rho_t = P(report, "stellar_density_transit")
    assert "profile likelihood" in rho_t["method"] and rho_t["uncertainty"]["method"] == "profile_likelihood"
    assert rho_t["value"] - rho_t["uncertainty"]["lower"] == pytest.approx(profile["lower_68"], abs=0.01)
    # The injected star's density (1.63 g/cm^3) is inside the light-curve-only interval.
    assert profile["lower_68"] < 1.63 < profile["upper_68"] * 1.05
    # Independence: changing the catalogue star changes the catalogue density
    # but not the transit-only estimate it is compared with.
    rep2 = recompute_characterization(report["inputs"], {"stellar_logg": {"value": 4.2, "uncertainty": 0.05}})
    assert P(rep2, "stellar_density_transit")["display"] == rho_t["display"]
    assert P(rep2, "stellar_density")["value"] != P(report, "stellar_density")["value"]


def test_density_check_is_not_evaluated_when_the_profile_is_unbounded(sc_report):
    inputs = copy.deepcopy(sc_report["inputs"])
    prof = inputs["transit_fit"]["unconstrained"]["density_profile"]
    prof.update({"lower_68": None, "bounded": False})
    rep = recompute_characterization(inputs)
    rho_t = P(rep, "stellar_density_transit")
    assert rho_t["reliability"] == "unreliable" and rho_t["display"].startswith("<")
    assert "no lower bound" in rho_t["reason"]
    check = next(c for c in rep["consistency_checks"] if c["check"] == "stellar_density")
    assert check["consistent"] is None
    assert "Not evaluated" in check["note"] and "neither confirmed nor contradicted" in check["note"]


def test_confidence_classes_follow_provenance(report):
    P_ = report["parameters"]
    assert P_["stellar_teff"]["provenance"] == "catalog" and P_["stellar_teff"]["reliability"] == "reliable"
    assert P_["planet_radius"]["provenance"] == "derived" and P_["planet_radius"]["reliability"] == "reliable"
    assert P_["planet_mass"]["provenance"] == "model_estimated" and P_["planet_mass"]["reliability"] != "reliable"
    assert P_["eccentricity"]["provenance"] == "assumed" and P_["eccentricity"]["reliability"] == "not_assessed"
    unavailable = [p for p in P_.values() if p["status"] == "unavailable"]
    assert all(p["value"] is None and p["reason"] for p in unavailable)
    # Log-scale catalogue values are not judged by relative uncertainty.
    from app.characterization.engine import LOG_SCALE_PARAMETERS
    assert {"stellar_logg", "stellar_metallicity"} <= LOG_SCALE_PARAMETERS


def test_density_profile_is_independent_of_the_catalogue_prior(sc_lc, monkeypatch):
    """The prior-free profile must not change when the catalogue density used
    as the fit prior changes -- otherwise the consistency check is circular."""
    from app.characterization import planet_characterization as pc
    t, f, bls = sc_lc
    res = resolve_object_id("K00752.01")
    real = pc.build_inputs(t, f, bls, res, "K00752.01")["transit_fit"]
    monkeypatch.setattr(pc, "catalog_stellar_density",
                        lambda catalog: {"value": 0.4, "sigma": 0.08, "source": "test: a very different star"})
    other = pc.build_inputs(t, f, bls, res, "K00752.01")["transit_fit"]
    assert other["stellar_density_prior"]["value"] == 0.4 != real["stellar_density_prior"]["value"]
    assert other["params"]["a_rs"] != pytest.approx(real["params"]["a_rs"], rel=0.05)   # the prior did act on the fit
    assert real["unconstrained"]["density_profile"]["bounded"] in (True, False)    # a real profile, not skipped
    assert other["unconstrained"]["density_profile"] == real["unconstrained"]["density_profile"]
    assert other["unconstrained"]["params"] == real["unconstrained"]["params"]


def test_loosely_bounded_density_is_labelled_a_weak_test(report):
    check = next(c for c in report["consistency_checks"] if c["check"] == "stellar_density")
    if P(report, "stellar_density_transit")["reliability"] != "reliable" and check["consistent"] is not None:
        assert check["strength"] == "weak" and check["note"].startswith("Weak test")


def test_density_check_not_evaluated_for_a_non_significant_transit(report):
    """No significant transit -> no geometry to compare with the catalogue."""
    inputs = copy.deepcopy(report["inputs"])
    inputs["transit_fit"]["snr"] = 5.0                     # below the 7.1 detection threshold
    rep = recompute_characterization(inputs)
    assert P(rep, "transit_snr")["reliability"] == "unreliable"
    check = next(c for c in rep["consistency_checks"] if c["check"] == "stellar_density")
    assert check["consistent"] is None and "not significant" in check["note"]


def test_unknown_star_density_comes_from_the_profile_not_the_covariance(sc_lc):
    """Without a catalogue match there is no prior, but the transit-only
    density must still come from the profile likelihood."""
    t, f, bls = sc_lc
    inputs = build_inputs(t, f, bls, None, None)
    fit = inputs["transit_fit"]
    assert fit["stellar_density_prior"] is None and fit["unconstrained"] is None
    assert fit["density_profile"] and fit["density_profile"]["bounded"] in (True, False)
    rep = recompute_characterization(inputs)
    rho_t = P(rep, "stellar_density_transit")
    assert "profile likelihood" in rho_t["method"]


def test_unresolved_ingress_makes_the_transit_density_unavailable(report):
    """Long cadence: the ingress is shorter than half an exposure, so no
    light-curve-only density is reported and the profile is not computed."""
    rho_t = P(report, "stellar_density_transit")
    assert rho_t["status"] == "unavailable" and rho_t["value"] is None
    assert "shorter than half" in rho_t["reason"] and "1-minute" in rho_t["reason"]
    assert report["inputs"]["transit_fit"]["unconstrained"]["density_profile"]["resolved"] is False


def test_short_cadence_resolves_the_transit_density_and_contains_the_truth(sc_report):
    rho_t = P(sc_report, "stellar_density_transit")
    assert rho_t["status"] == "computed" and rho_t["uncertainty"]["method"] == "profile_likelihood"
    lo = rho_t["value"] - rho_t["uncertainty"]["lower"]
    hi = rho_t["value"] + rho_t["uncertainty"]["upper"]
    truth = 3 * math.pi * TRUTH["a_rs"] ** 3 / (6.67430e-8 * (TRUTH["period"] * 86400) ** 2)
    assert lo * 0.9 < truth < hi * 1.1
    check = next(c for c in sc_report["consistency_checks"] if c["check"] == "stellar_density")
    assert check["consistent"] is True
