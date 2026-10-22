"""
Scientific unit tests for the characterization engine's physics, transit
model and uncertainty utilities, against independent reference values:
Solar-system bodies (IAU nominal values), closed-form transit geometry, and
NASA's own KOI catalogue derived columns (koi_teq, koi_insol).
"""
import csv
import math

import numpy as np
import pytest

from app.characterization import physics as P
from app.characterization.transit_model import (
    blocked_fraction, central_depth, t14_t23, transit_flux, uniform_disk_blocked_fraction,
)
from app.characterization.uncertainty import (
    analytic_power_law, format_measurement, split_normal, summarize,
)
from app.config import get_settings

R_SUN_IN_EARTH = 6.957e8 / 6.371e6  # 109.20


# ---- unit conversions / planet radius ----------------------------------------

def test_planet_radius_unit_conversion():
    assert P.planet_radius_earth(0.1, 1.0) == pytest.approx(0.1 * R_SUN_IN_EARTH, rel=1e-9)
    # Jupiter around the Sun: k = R_jup / R_sun -> 71492 km / 6371 km = 11.22 R_earth
    k_jup = P.R_JUP_M / 6.957e8
    assert P.planet_radius_earth(k_jup, 1.0) == pytest.approx(11.22, abs=0.01)


def test_radius_from_depth_approximation_matches_sqrt_depth():
    depth = 0.01  # 1% -> k = 0.1
    assert P.planet_radius_earth(math.sqrt(depth), 0.5) == pytest.approx(0.05 * R_SUN_IN_EARTH)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_invalid_inputs_return_nan_not_zero(bad):
    assert math.isnan(P.planet_radius_earth(bad, 1.0))
    assert math.isnan(P.planet_radius_earth(0.1, bad))
    assert math.isnan(P.semi_major_axis_kepler(10.0, bad))
    assert math.isnan(P.equilibrium_temperature(5772.0, 1.0, bad))
    assert math.isnan(P.stellar_luminosity(bad, 5772.0))


# ---- Kepler's third law / orbits ---------------------------------------------

def test_kepler_third_law_earth_orbit():
    assert P.semi_major_axis_kepler(365.256363, 1.0) == pytest.approx(1.0, abs=2e-4)


def test_kepler_third_law_scaling():
    # a ∝ P^(2/3) M^(1/3)
    a1 = P.semi_major_axis_kepler(10.0, 1.0)
    assert P.semi_major_axis_kepler(80.0, 1.0) == pytest.approx(a1 * 4.0, rel=1e-12)
    assert P.semi_major_axis_kepler(10.0, 8.0) == pytest.approx(a1 * 2.0, rel=1e-12)


def test_planet_mass_term_in_kepler_law():
    # Jupiter's mass changes a by (1 + Mj/Msun)^(1/3) ~ 1.0003
    a0 = P.semi_major_axis_kepler(4332.59, 1.0)
    a1 = P.semi_major_axis_kepler(4332.59, 1.0, P.M_JUP_KG / P.M_EARTH_KG)
    assert a1 / a0 == pytest.approx((1 + P.M_JUP_KG / 1.98892e30) ** (1 / 3), rel=1e-9)


def test_inclination_geometry():
    assert P.inclination_deg(0.0, 10.0) == pytest.approx(90.0)
    assert P.inclination_deg(1.0, 10.0) == pytest.approx(math.degrees(math.acos(0.1)))
    # Eccentric: b = a cos i (1-e^2)/(1+e sin w)
    e, w = 0.3, 30.0
    cos_i = 0.5 / 10.0 * (1 + e * math.sin(math.radians(w))) / (1 - e ** 2)
    assert P.inclination_deg(0.5, 10.0, e, w) == pytest.approx(math.degrees(math.acos(cos_i)))
    assert math.isnan(P.inclination_deg(0.5, 0.9))  # a/R* < 1 is unphysical


def test_transit_duration_formula_matches_small_angle_limit():
    period, k, a, b = 10.0, 0.05, 50.0, 0.3
    t14, t23 = P.transit_durations(period, k, a, b)
    expected_t14 = period / math.pi * math.sqrt((1 + k) ** 2 - b ** 2) / a
    assert t14 == pytest.approx(expected_t14, rel=1e-3)
    assert t23 < t14
    # Same relation in the scalar transit-model helper.
    s14, s23 = t14_t23(period, k, a, b)
    assert s14 == pytest.approx(float(t14), rel=1e-12)
    assert s23 == pytest.approx(float(t23), rel=1e-12)


def test_grazing_geometry_has_no_full_duration():
    t14, t23 = P.transit_durations(10.0, 0.1, 20.0, 0.95)
    assert np.isfinite(t14) and np.isnan(t23)
    assert t14_t23(10.0, 0.1, 20.0, 0.95)[1] is None


def test_orbital_velocity_earth():
    assert P.orbital_velocity_kms(1.0, 365.256363) == pytest.approx(29.78, abs=0.01)


# ---- stellar quantities ----------------------------------------------------

def test_solar_reference_values():
    assert P.stellar_luminosity(1.0, 5772.0) == pytest.approx(1.0)
    assert P.stellar_mass_from_logg_radius(4.438, 1.0) == pytest.approx(1.0, abs=0.01)
    assert P.logg_from_mass_radius(1.0, 1.0) == pytest.approx(4.438, abs=0.002)
    assert P.stellar_density_from_mass_radius(1.0, 1.0) == pytest.approx(1.41, abs=0.01)


def test_transit_derived_density_reproduces_sun_from_earth_orbit():
    a_over_rsun = 1.495978707e11 / 6.957e8  # 215.03
    assert P.stellar_density_from_transit(365.256363, a_over_rsun) == pytest.approx(1.41, abs=0.01)


# ---- thermal -----------------------------------------------------------------

def test_earth_equilibrium_temperature():
    # Earth: A = 0.3, full redistribution -> ~255 K
    assert P.equilibrium_temperature(5772.0, 1.0, 1.0, 0.3, 0.25) == pytest.approx(254.6, abs=0.5)
    # Zero albedo -> 278.6 K
    assert P.equilibrium_temperature(5772.0, 1.0, 1.0, 0.0, 0.25) == pytest.approx(278.6, abs=0.5)


def test_redistribution_and_albedo_scaling():
    full = P.equilibrium_temperature(5000.0, 0.8, 0.05, 0.0, 0.25)
    day = P.equilibrium_temperature(5000.0, 0.8, 0.05, 0.0, 2 / 3)
    assert day / full == pytest.approx((8 / 3) ** 0.25)
    a3 = P.equilibrium_temperature(5000.0, 0.8, 0.05, 0.3, 0.25)
    assert a3 / full == pytest.approx(0.7 ** 0.25)


def test_insolation_and_eccentricity():
    assert P.insolation_earth(1.0, 1.0) == pytest.approx(1.0)
    assert P.insolation_earth(4.0, 2.0) == pytest.approx(1.0)
    assert P.insolation_earth(1.0, 1.0, 0.6) == pytest.approx(1.25)
    # Teq orbit-averaged factor (1-e^2)^(-1/8)
    ratio = P.equilibrium_temperature(5772.0, 1.0, 1.0, 0.3, 0.25, 0.6) / P.equilibrium_temperature(5772.0, 1.0, 1.0, 0.3, 0.25)
    assert ratio == pytest.approx(0.64 ** -0.125)


def _catalog_rows():
    with open(get_settings().koi_catalog_path, newline="") as fh:
        yield from csv.DictReader(fh)


def _floats(row, keys):
    try:
        vals = [float(row[k]) for k in keys]
    except (ValueError, KeyError):
        return None
    return vals if all(math.isfinite(v) for v in vals) else None


def test_reproduces_nasa_koi_teq_and_insolation_across_catalogue():
    """NASA's koi_teq assumes A = 0.3 and full redistribution, with a from
    Kepler's law and M* from log g and R*. The engine's physics must
    reproduce it for the whole catalogue (not just one hand-picked row)."""
    teq_ratios, insol_ratios = [], []
    for row in _catalog_rows():
        v = _floats(row, ("koi_steff", "koi_slogg", "koi_srad", "koi_period", "koi_teq", "koi_insol"))
        if v is None or v[4] <= 0 or v[5] <= 0:
            continue
        teff, logg, rs, period, teq, insol = v
        a = P.semi_major_axis_kepler(period, P.stellar_mass_from_logg_radius(logg, rs))
        teq_ratios.append(P.equilibrium_temperature(teff, rs, a, 0.3, 0.25) / teq)
        insol_ratios.append(P.insolation_earth(P.stellar_luminosity(rs, teff), a) / insol)
    teq_dev = np.abs(np.array(teq_ratios) - 1)
    insol_dev = np.abs(np.array(insol_ratios) - 1)
    assert len(teq_dev) > 9000
    assert np.median(teq_dev) < 0.002
    assert np.mean(teq_dev < 0.01) > 0.99
    assert np.median(insol_dev) < 0.015
    assert np.mean(insol_dev < 0.05) > 0.99


# ---- mass-radius relation, planet bulk properties ------------------------------

def test_earth_bulk_properties():
    assert P.planet_density(1.0, 1.0) == pytest.approx(5.51, abs=0.01)
    assert P.planet_surface_gravity(1.0, 1.0) == pytest.approx(9.82, abs=0.01)
    assert P.escape_velocity_kms(1.0, 1.0) == pytest.approx(11.19, abs=0.01)


def test_chen_kipping_relation():
    # Continuity at the Terran/Neptunian transition (2.04 M_earth)
    assert P.mass_from_radius_ck17(P.CK17_R_TERRAN_MAX) == pytest.approx(2.04, rel=1e-6)
    assert P.mass_from_radius_ck17(P.CK17_R_TERRAN_MAX * 1.000001) == pytest.approx(2.04, rel=1e-4)
    # Earth radius -> slightly below 1 M_earth on the Terran branch
    assert P.mass_from_radius_ck17(1.0) == pytest.approx((1 / 1.008) ** (1 / 0.279), rel=1e-3)
    # Neptunian upper limit ~14.3 R_earth; giant regime is not invertible
    assert P.CK17_R_NEPTUNIAN_MAX == pytest.approx(14.3, abs=0.1)
    assert math.isnan(P.mass_from_radius_ck17(15.0))
    radii = np.linspace(0.5, 14.0, 50)
    assert np.all(np.diff(P.mass_from_radius_ck17(radii)) > 0)


# ---- habitable zone ----------------------------------------------------------

def test_kopparapu_hz_for_the_sun():
    inner = P.hz_distance_au(1.0, P.hz_effective_flux(5780.0, "runaway_greenhouse"))
    outer = P.hz_distance_au(1.0, P.hz_effective_flux(5780.0, "maximum_greenhouse"))
    assert inner == pytest.approx(0.95, abs=0.01)
    assert outer == pytest.approx(1.676, abs=0.01)
    assert math.isnan(P.hz_effective_flux(8000.0, "runaway_greenhouse"))  # outside validity range


# ---- transit model -------------------------------------------------------------

@pytest.mark.parametrize("k", [0.005, 0.01, 0.05, 0.1, 0.3])
def test_numerical_model_matches_analytic_uniform_disk(k):
    z = np.linspace(0.0, 1.0 + 1.01 * k, 2001)
    err = np.abs(uniform_disk_blocked_fraction(z, k) - blocked_fraction(z, k, 0.0, 0.0))
    assert err.max() / k ** 2 < 1e-4


@pytest.mark.parametrize("b", [0.0, 0.5, 0.8])
def test_limb_darkened_central_depth_small_planet_limit(b):
    k, u1, u2 = 0.01, 0.4, 0.26
    mu = math.sqrt(1 - b * b)
    expected = k * k * (1 - u1 * (1 - mu) - u2 * (1 - mu) ** 2) / (1 - u1 / 3 - u2 / 6)
    assert central_depth(k, b, u1, u2) == pytest.approx(expected, rel=1e-3)


def test_transit_flux_out_of_transit_is_unity_and_symmetric():
    t = np.linspace(-0.3, 0.3, 601)
    f = transit_flux(t, 0.0, 10.0, 0.05, 20.0, 0.3, 0.4, 0.26)
    assert f[0] == 1.0 and f[-1] == 1.0
    np.testing.assert_allclose(f, f[::-1], atol=1e-12)
    # Secondary-eclipse phase never shows a transit (planet behind the star).
    assert transit_flux(np.array([5.0]), 0.0, 10.0, 0.05, 20.0, 0.0, 0.4, 0.26)[0] == 1.0


# ---- uncertainty utilities ---------------------------------------------------

def test_split_normal_reproduces_asymmetric_errors():
    s = split_normal(10.0, 2.0, 1.0, 200000, np.random.default_rng(0))
    p16, p50, p84 = np.percentile(s, [16, 50, 84])
    # The split normal's mode is the catalogue value; its percentiles span
    # roughly the quoted -1/+2 interval.
    assert p84 - p16 == pytest.approx(3.0, rel=0.05)
    assert 10.0 < p50 < 11.0


def test_missing_uncertainty_is_held_fixed():
    s = split_normal(3.0, None, None, 100, np.random.default_rng(0))
    assert np.all(s == 3.0)


def test_analytic_and_monte_carlo_agree_for_power_law():
    rng = np.random.default_rng(1)
    r, sr, t, st = 1.1, 0.02, 5800.0, 50.0
    l_mc = P.stellar_luminosity(rng.normal(r, sr, 200000), rng.normal(t, st, 200000))
    _, lo, hi = summarize(l_mc)
    l0 = float(P.stellar_luminosity(r, t))
    sigma = analytic_power_law(l0, [(r, 2, sr), (t, 4, st)])
    assert sigma == pytest.approx((lo + hi) / 2, rel=0.03)
    assert analytic_power_law(l0, [(r, 2, None), (t, 4, None)]) is None


def test_summarize_rejects_mostly_undefined_samples():
    s = np.full(1000, np.nan)
    s[:100] = 1.0
    assert summarize(s) is None


@pytest.mark.parametrize("value,lo,hi,display", [
    (2.34567, 0.123, 0.123, "2.35 ± 0.12"),
    (9.487953, 0.000432, 0.000461, "9.48795 +0.00046 / −0.00043"),
    (804.123, 28.4, 32.1, "804 +32 / −28"),
])
def test_format_measurement_rounds_to_uncertainty(value, lo, hi, display):
    assert format_measurement(value, lo, hi)[3] == display


def test_format_measurement_without_uncertainty_keeps_integer_digits():
    assert format_measurement(1345.678)[3] == "1346"
    assert format_measurement(0.0123456)[0] == pytest.approx(0.0123)
    assert format_measurement(None)[3] == "Unavailable"
