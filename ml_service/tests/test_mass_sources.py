"""
Stellar- and planet-mass source priority, identity checks and propagation.

Stellar mass:  override > local KOI catalogue (koi_smass) > Archive DR25
               isochrone mass (identity-checked) > M* = g R*^2 / G > unavailable.
Planet mass:   override > Archive measurement > Archive estimate with an
               uncertainty > Chen & Kipping (2017) from the radius > unavailable.

Archive responses are synthetic (monkeypatched query functions); engine
inputs are the real characterization snapshot of the project's Kepler-227 b
test light curve.
"""
import copy
import math

import pytest

from app.characterization import archive_enrichment, recompute_characterization
from app.characterization.physics import stellar_mass_from_logg_radius

DR25_ROW = {"kepid": 10797460, "feh": 0.14, "feh_err1": 0.15, "feh_err2": -0.15, "dist": 1014.0, "dist_err1": 131.0,
            "dist_err2": -84.0, "mass": 0.919, "mass_err1": 0.052, "mass_err2": -0.046, "prov_sec": "DSEP",
            "radius": 0.927, "logg": 4.467, "teff": 5455}
LOCAL_STELLAR = {"stellar_radius": {"value": 0.927}, "stellar_logg": {"value": 4.467}, "stellar_teff": {"value": 5455.0}}
PLANET_ROW = {"pl_name": "Kepler-227 b", "pl_orbper": 9.48803557, "pl_bmasse": 9.85, "pl_bmasseerr1": None,
              "pl_bmasseerr2": None, "pl_bmassprov": "M-R relationship", "sy_dist": 1083.06, "sy_disterr1": 29.67,
              "sy_disterr2": -29.67}


@pytest.fixture(scope="module")
def inputs():
    import sys
    sys.path.insert(0, "tests")
    from test_planet_characterization import _lightcurve
    from app.characterization import characterize_light_curve
    from app.lightcurve_extraction import compute_feature_vector
    from app.stellar_catalog_service import resolve_object_id
    t, f = _lightcurve()
    return characterize_light_curve(t, f, compute_feature_vector(t, f).bls, resolve_object_id("K00752.01"),
                                    "K00752.01")["inputs"]


def with_catalog(inputs, stellar=None, archive=None, drop=()):
    inp = copy.deepcopy(inputs)
    inp["catalog"]["stellar"].update(stellar or {})
    for name in drop:
        inp["catalog"]["stellar"].pop(name, None)
    if archive is not None:
        inp["catalog"]["archive"] = archive
    return inp


def P(rep, name):
    return rep["parameters"][name]


@pytest.fixture
def archive(monkeypatch):
    monkeypatch.setattr(archive_enrichment, "_CACHE", {})
    calls = {"stellar": [], "planet": []}

    def setup(dr25_rows=None, planet_rows=None, fail=False):
        def dr25(kepid):
            calls["stellar"].append(kepid)
            if fail:
                raise archive_enrichment.NasaApiError("network down")
            return copy.deepcopy(dr25_rows if dr25_rows is not None else [DR25_ROW])

        def planet(name):
            calls["planet"].append(name)
            if fail:
                raise archive_enrichment.NasaApiError("network down")
            return copy.deepcopy(planet_rows if planet_rows is not None else [PLANET_ROW])
        monkeypatch.setattr(archive_enrichment, "query_dr25_stellar", dr25)
        monkeypatch.setattr(archive_enrichment, "query_confirmed_planet", planet)
        return calls
    return setup


# ---- stellar mass -----------------------------------------------------------------

def test_1_local_catalogue_stellar_mass_comes_first(inputs):
    rep = recompute_characterization(with_catalog(
        inputs, stellar={"stellar_mass": {"value": 0.95, "err_plus": 0.05, "err_minus": 0.05, "column": "koi_smass"}},
        archive={"stellar": {"stellar_mass": {"value": 0.80, "err_plus": 0.04, "err_minus": 0.04, "source": "x",
                                              "method": "archive"}}, "planet": {}, "notes": []}))
    m = P(rep, "stellar_mass")
    assert m["value"] == 0.95 and m["source"] == "koi_smass"
    assert m["provenance"] == "catalog" and m["evidence"] == "catalogue_derived"


def test_2_archive_isochrone_mass_when_missing_locally(inputs, archive):
    archive()
    found = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    rec = found["stellar"]["stellar_mass"]
    assert rec["value"] == 0.919 and rec["err_plus"] == 0.052 and rec["err_minus"] == 0.046
    assert rec["kind"] == "catalogue_derived" and "DSEP" in rec["method"] and "not a direct" in rec["method"]
    rep = recompute_characterization(with_catalog(inputs, archive=found))
    m = P(rep, "stellar_mass")
    assert m["value"] == 0.919 and m["evidence"] == "catalogue_derived" and m["reliability"] == "reliable"
    assert "isochrone" in m["method"].lower()
    check = next(c for c in rep["consistency_checks"] if c["check"] == "stellar_mass_logg")
    assert check["label"].startswith("Catalogue stellar mass") and check["consistent"] is True
    # The more precise isochrone mass tightens the semi-major axis relative to the log g estimate.
    base = recompute_characterization(inputs)
    rel = lambda p: p["uncertainty"]["upper"] / p["value"]
    assert rel(P(rep, "semi_major_axis")) < rel(P(base, "semi_major_axis"))


def test_3_stellar_mass_estimated_from_log_g_and_radius(inputs):
    rep = recompute_characterization(inputs)              # no catalogue mass anywhere
    m = P(rep, "stellar_mass")
    assert m["provenance"] == "derived" and m["evidence"] == "derived"
    assert m["value"] == pytest.approx(float(stellar_mass_from_logg_radius(4.467, 0.927)), rel=0.01)
    assert m["uncertainty"]["upper"] / m["value"] == pytest.approx(0.21, abs=0.06)   # ~0.08 dex in log g -> ~20%


def test_4_insufficient_information_gives_no_stellar_mass(inputs):
    rep = recompute_characterization(with_catalog(inputs, drop=("stellar_logg",)))
    m = P(rep, "stellar_mass")
    assert m["status"] == "unavailable" and m["value"] is None
    assert "do not determine the mass on their own" in m["reason"]
    # Downstream: the orbit falls back to transit geometry instead of an invented mass.
    assert "a/R*" in P(rep, "semi_major_axis")["method"]


# ---- planet mass ------------------------------------------------------------------

def test_5_measured_planet_mass_takes_precedence(inputs):
    arch = {"stellar": {}, "notes": [], "planet": {"planet_mass": {
        "value": 7.0, "err_plus": 0.7, "err_minus": 0.7, "source": "Archive", "kind": "measured",
        "method": "Measured planet mass (radial velocities or transit-timing variations) from the NASA Exoplanet Archive."}}}
    rep = recompute_characterization(with_catalog(inputs, archive=arch))
    m = P(rep, "planet_mass")
    assert m["value"] == 7.0 and m["evidence"] == "measured" and "Chen & Kipping" not in m["method"]


def test_6_missing_planet_mass_uses_chen_kipping(inputs):
    rep = recompute_characterization(inputs)
    m = P(rep, "planet_mass")
    assert m["evidence"] == "model_estimated" and "Chen & Kipping" in m["method"]
    assert m["uncertainty"]["method"] == "monte_carlo"


def test_7_missing_planet_radius_prevents_a_mass_estimate(inputs):
    rep = recompute_characterization(with_catalog(inputs, drop=("stellar_radius",)))
    assert P(rep, "planet_radius")["status"] == "unavailable"
    m = P(rep, "planet_mass")
    assert m["status"] == "unavailable" and m["value"] is None
    for n in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        assert P(rep, n)["status"] == "unavailable"


def test_8_estimate_uncertainty_propagates_into_all_derived_properties(inputs):
    rep = recompute_characterization(inputs)
    mass = P(rep, "planet_mass")
    rel = lambda p: 0.5 * (p["uncertainty"]["upper"] + p["uncertainty"]["lower"]) / p["value"]
    # g ~ M / R^2 and rho ~ M / R^3 inherit the ~50% mass spread; v_esc ~ sqrt(M / R) about half of it.
    assert rel(P(rep, "planet_surface_gravity")) == pytest.approx(rel(mass), rel=0.3)
    assert rel(P(rep, "planet_density")) == pytest.approx(rel(mass), rel=0.3)
    assert rel(P(rep, "escape_velocity")) == pytest.approx(0.5 * rel(mass), rel=0.35)
    for n in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        assert P(rep, n)["evidence"] == "model_estimated" and P(rep, n)["reliability"] != "reliable"


def test_9_derived_property_values_and_units(inputs):
    arch = {"stellar": {}, "notes": [], "planet": {"planet_mass": {"value": 6.0, "err_plus": 0.3, "err_minus": 0.3,
            "source": "Archive", "kind": "measured", "method": "measured"}}}
    rep = recompute_characterization(with_catalog(inputs, archive=arch))
    r_m = P(rep, "planet_radius")["value"] * 6.371e6
    m_kg = 6.0 * 5.9722e24
    G = 6.67430e-11
    assert P(rep, "planet_density")["value"] == pytest.approx(m_kg / (4 / 3 * math.pi * r_m ** 3) / 1000, rel=0.04)
    assert P(rep, "planet_surface_gravity")["value"] == pytest.approx(G * m_kg / r_m ** 2, rel=0.04)
    assert P(rep, "escape_velocity")["value"] == pytest.approx(math.sqrt(2 * G * m_kg / r_m) / 1000, rel=0.03)
    assert [P(rep, n)["unit"] for n in ("planet_density", "planet_surface_gravity", "escape_velocity")] == \
        ["g/cm³", "m/s²", "km/s"]
    for n in ("planet_density", "planet_surface_gravity", "escape_velocity"):
        assert P(rep, n)["evidence"] == "derived"            # computed from a measured mass, not "measured"


def test_10_catalogue_estimates_stay_low_confidence(inputs, archive):
    archive(planet_rows=[{**PLANET_ROW, "pl_bmasseerr1": 4.0, "pl_bmasseerr2": -2.5}])   # M-R estimate with interval
    found = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert found["planet"]["planet_mass"]["kind"] == "catalogue_estimate"
    rep = recompute_characterization(with_catalog(inputs, archive=found))
    m = P(rep, "planet_mass")
    assert m["evidence"] == "model_estimated" and m["reliability"] == "low_confidence"
    assert m["value"] == 9.85 and m["uncertainty"]["upper"] == 4.0 and m["uncertainty"]["lower"] == 2.5
    assert "catalogue planet-mass estimate" in P(rep, "planet_density")["reason"]
    # Without an interval the Archive's estimate is not used (it would look exact).
    archive_enrichment._CACHE.clear()
    archive()
    plain = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert "planet_mass" not in plain["planet"] and any("no quoted uncertainty" in n for n in plain["notes"])


def test_11_network_failure_is_safe(inputs, archive):
    archive(fail=True)
    found = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert found["stellar"] == {} and found["planet"] == {} and len(found["notes"]) == 2
    rep = recompute_characterization(with_catalog(inputs, archive=found))
    assert P(rep, "stellar_mass")["provenance"] == "derived"          # falls back to log g + R*
    assert P(rep, "planet_mass")["evidence"] == "model_estimated"     # falls back to Chen & Kipping
    assert archive_enrichment._CACHE == {}                            # failures are not cached


def test_12_ambiguous_or_mismatched_targets_return_nothing(archive):
    archive(dr25_rows=[DR25_ROW, {**DR25_ROW, "mass": 1.3}])
    out = archive_enrichment.lookup(10797460, None, LOCAL_STELLAR)
    assert out["stellar"] == {} and any("ambiguous" in n for n in out["notes"])

    archive_enrichment._CACHE.clear()
    archive(dr25_rows=[{**DR25_ROW, "radius": 1.6}])                  # another star's DR25 row
    out = archive_enrichment.lookup(10797460, None, LOCAL_STELLAR)
    assert out["stellar"] == {} and any("disagrees with the local catalogue" in n for n in out["notes"])

    archive_enrichment._CACHE.clear()
    archive(planet_rows=[{**PLANET_ROW, "pl_name": "Kepler-227 c", "pl_bmasseerr1": 1, "pl_bmasseerr2": -1,
                          "pl_bmassprov": "Mass"}])
    out = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert "planet_mass" not in out["planet"]                         # a sibling planet's mass is never used

    archive_enrichment._CACHE.clear()
    archive(planet_rows=[{**PLANET_ROW, "pl_orbper": 54.4, "pl_bmasseerr1": 1, "pl_bmasseerr2": -1,
                          "pl_bmassprov": "Mass"}])
    out = archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert "planet_mass" not in out["planet"] and any("does not match this transit" in n for n in out["notes"])


def test_12b_multi_koi_star_uses_only_the_period_matched_planet(monkeypatch):
    """KIC 10797460 hosts two KOIs; only the KOI whose catalogue period matches
    the light curve may supply the planet name sent to the Archive."""
    import sys
    sys.path.insert(0, "tests")
    from test_planet_characterization import _lightcurve
    from app.characterization import planet_characterization as pc
    from app.lightcurve_extraction import compute_feature_vector
    from app.stellar_catalog_service import resolve_object_id
    seen = []
    monkeypatch.setattr(pc.archive_enrichment, "lookup",
                        lambda kepid, name, *a: seen.append((kepid, name)) or {"stellar": {}, "planet": {}, "notes": []})
    t, f = _lightcurve()
    res = resolve_object_id("KIC 10797460")
    assert res.match_status == "matched_star" and res.n_candidate_rows > 1
    inputs = pc.build_inputs(t, f, compute_feature_vector(t, f).bls, res, "KIC 10797460", archive_lookup=True)
    assert inputs["catalog"]["reference_source"] == "period_matched"
    assert seen == [(10797460, inputs["catalog"]["reference_koi"]["kepler_name"])]
    assert seen[0][1] == "Kepler-227 b"


def test_13_cache_avoids_repeated_requests(archive):
    calls = archive()
    for _ in range(3):
        archive_enrichment.lookup(10797460, "Kepler-227 b", LOCAL_STELLAR, 9.4879)
    assert len(calls["stellar"]) == 1 and len(calls["planet"]) == 1


def test_13b_offline_default_needs_no_network(inputs):
    """The engine runs from local data alone when the Archive lookup is off."""
    rep = recompute_characterization(inputs)
    assert "archive" not in inputs["catalog"]
    assert P(rep, "stellar_mass")["status"] == "computed" and P(rep, "planet_mass")["status"] == "computed"
