"""
Physical and orbital relations used by the characterization engine.

Every function accepts floats or numpy arrays (so the Monte Carlo can push
thousands of samples through the same code that produces the central value)
and returns NaN -- never 0 or a fabricated fallback -- where an input is
outside the relation's domain. Units are in each docstring. Constants are
shared with app/astrophysics.py so the physics-validation stage and this
engine can never disagree about, e.g., the size of the Sun.

References
  Winn 2010, "Transits and Occultations" (arXiv:1001.2010)       -- transit geometry
  Seager & Mallen-Ornelas 2003, ApJ 585, 1038                    -- stellar density from transits
  Mamajek et al. 2015, IAU 2015 Resolution B3                    -- nominal solar values
  Chen & Kipping 2017, ApJ 834, 17                               -- probabilistic mass-radius relation
  Kopparapu et al. 2014, ApJL 787, L29                           -- habitable-zone boundaries
"""
from __future__ import annotations

import math

import numpy as np

from app.astrophysics import AU_M, DAY_S, G, M_SUN_KG, R_EARTH_M, R_SUN_M, T_SUN_EFF_K

M_EARTH_KG = 5.9722e24
M_JUP_KG = 1.89813e27
R_JUP_M = 7.1492e7
L_SUN_W = 3.828e26           # IAU nominal solar luminosity
SIGMA_SB = 5.670374419e-8

HEAT_REDISTRIBUTION_FACTORS = {
    # f in Teq = Teff * sqrt(Rstar/a) * [f (1 - A)]^(1/4)  (Cowan & Agol 2011 convention)
    "full": 0.25,       # incident energy re-radiated uniformly over the whole sphere
    "dayside": 2.0 / 3.0,  # no redistribution; instantaneous re-radiation from the dayside
}


def _arr(x):
    return np.asarray(x, dtype=float)


def _nan_where(cond, values):
    out = np.where(cond, np.nan, values)
    return out if out.ndim else float(out)


# ---- star ------------------------------------------------------------------

def stellar_mass_from_logg_radius(logg_cgs, r_star_solar):
    """M [Msun] = g R^2 / G, with g = 10**logg in cm/s^2."""
    logg, r = _arr(logg_cgs), _arr(r_star_solar)
    g_si = 10.0 ** logg / 100.0
    mass = g_si * (r * R_SUN_M) ** 2 / G / M_SUN_KG
    return _nan_where(~(r > 0) | ~np.isfinite(logg), mass)


def logg_from_mass_radius(m_star_solar, r_star_solar):
    """log10(g [cm/s^2]) for a star of the given mass and radius."""
    m, r = _arr(m_star_solar), _arr(r_star_solar)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = G * m * M_SUN_KG / (r * R_SUN_M) ** 2 * 100.0
        return _nan_where(~(m > 0) | ~(r > 0), np.log10(g))


def stellar_luminosity(r_star_solar, teff_k):
    """L [Lsun] = (R/Rsun)^2 (Teff/Teff_sun)^4 (Stefan-Boltzmann, blackbody)."""
    r, t = _arr(r_star_solar), _arr(teff_k)
    return _nan_where(~(r > 0) | ~(t > 0), r ** 2 * (t / T_SUN_EFF_K) ** 4)


def stellar_density_from_mass_radius(m_star_solar, r_star_solar):
    """Mean stellar density [g/cm^3] = M / (4/3 pi R^3)."""
    m, r = _arr(m_star_solar), _arr(r_star_solar)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = m * M_SUN_KG / (4.0 / 3.0 * math.pi * (r * R_SUN_M) ** 3) / 1000.0
    return _nan_where(~(m > 0) | ~(r > 0), rho)


def stellar_density_from_transit(period_days, a_over_rstar):
    """Transit-derived mean stellar density [g/cm^3] (Seager & Mallen-Ornelas
    2003, eq. 9, with Mp << Mstar):  rho = 3 pi (a/Rstar)^3 / (G P^2).
    Valid for a circular orbit; for an eccentric one this is biased by
    ((1 + e sin w) / sqrt(1 - e^2))^3 (Kipping 2010)."""
    p, a = _arr(period_days), _arr(a_over_rstar)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = 3.0 * math.pi * a ** 3 / (G * (p * DAY_S) ** 2) / 1000.0
    return _nan_where(~(p > 0) | ~(a > 1), rho)


# ---- orbit -----------------------------------------------------------------

def semi_major_axis_kepler(period_days, m_star_solar, m_planet_earth=0.0):
    """Kepler's third law: a [AU] = (G (M* + Mp) P^2 / 4 pi^2)^(1/3)."""
    p, m = _arr(period_days), _arr(m_star_solar)
    mp = np.nan_to_num(_arr(m_planet_earth), nan=0.0)
    total = m * M_SUN_KG + mp * M_EARTH_KG
    with np.errstate(invalid="ignore"):
        a = np.cbrt(G * total * (p * DAY_S) ** 2 / (4.0 * math.pi ** 2)) / AU_M
    return _nan_where(~(p > 0) | ~(m > 0), a)


def semi_major_axis_from_ratio(a_over_rstar, r_star_solar):
    """a [AU] = (a/Rstar) * Rstar -- the transit-geometry route, independent
    of the stellar mass."""
    a, r = _arr(a_over_rstar), _arr(r_star_solar)
    return _nan_where(~(a > 1) | ~(r > 0), a * r * R_SUN_M / AU_M)


def a_over_rstar(a_au, r_star_solar):
    a, r = _arr(a_au), _arr(r_star_solar)
    with np.errstate(divide="ignore", invalid="ignore"):
        return _nan_where(~(a > 0) | ~(r > 0), a * AU_M / (r * R_SUN_M))


def inclination_deg(impact, a_over_rs, ecc=0.0, omega_deg=90.0):
    """Orbital inclination from the impact parameter (Winn 2010, eq. 7):
    b = (a cos i / Rstar) * (1 - e^2) / (1 + e sin w)."""
    b, a = _arr(impact), _arr(a_over_rs)
    e, w = _arr(ecc), np.radians(_arr(omega_deg))
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_i = b / a * (1.0 + e * np.sin(w)) / (1.0 - e ** 2)
        inc = np.degrees(np.arccos(cos_i))
    return _nan_where(~(a > 1) | ~(b >= 0) | ~(np.abs(cos_i) <= 1) | ~(e < 1), inc)


def orbital_velocity_kms(a_au, period_days, ecc=0.0):
    """Mean orbital speed [km/s]. Circular: 2 pi a / P. Eccentric: the
    time-averaged speed is approximated by 2 pi a / P (exact to O(e^2))."""
    a, p = _arr(a_au), _arr(period_days)
    return _nan_where(~(a > 0) | ~(p > 0), 2.0 * math.pi * a * AU_M / (p * DAY_S) / 1000.0)


def transit_durations(period_days, k, a_over_rs, impact):
    """(T14, T23) in days for a circular orbit (Winn 2010, eqs. 14-15),
    vectorised. T23 is NaN for grazing geometry, T14 NaN if no transit."""
    p, k, a, b = _arr(period_days), _arr(k), _arr(a_over_rs), _arr(impact)
    with np.errstate(invalid="ignore", divide="ignore"):
        sin_i = np.sqrt(1.0 - (b / a) ** 2)
        arg14 = np.sqrt((1 + k) ** 2 - b ** 2) / (a * sin_i)
        arg23 = np.sqrt((1 - k) ** 2 - b ** 2) / (a * sin_i)
        t14 = np.where(arg14 <= 1, p / math.pi * np.arcsin(arg14), np.nan)
        t23 = np.where(arg23 <= 1, p / math.pi * np.arcsin(arg23), np.nan)
    return t14, t23


# ---- planet ----------------------------------------------------------------

def planet_radius_earth(k, r_star_solar):
    """Rp [R_earth] = (Rp/Rstar) * Rstar."""
    k, r = _arr(k), _arr(r_star_solar)
    return _nan_where(~(k > 0) | ~(r > 0), k * r * R_SUN_M / R_EARTH_M)


def insolation_earth(l_star_solar, a_au, ecc=0.0):
    """Orbit-averaged incident flux relative to Earth's:
    S = (L/Lsun) / (a/AU)^2 / sqrt(1 - e^2)."""
    l, a, e = _arr(l_star_solar), _arr(a_au), _arr(ecc)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = l / a ** 2 / np.sqrt(1.0 - e ** 2)
    return _nan_where(~(l > 0) | ~(a > 0) | ~(e < 1), s)


def equilibrium_temperature(teff_k, r_star_solar, a_au, albedo=0.3, redistribution=0.25, ecc=0.0):
    """Teq [K] = Teff sqrt(Rstar / a) [f (1 - A)]^(1/4), with f = 1/4 for
    full heat redistribution and 2/3 for dayside-only re-radiation; the
    orbit-averaged flux of an eccentric orbit adds a (1 - e^2)^(-1/8)
    factor. Assumes blackbody star and planet, no internal heat."""
    t, r, a = _arr(teff_k), _arr(r_star_solar), _arr(a_au)
    alb, f, e = _arr(albedo), _arr(redistribution), _arr(ecc)
    with np.errstate(invalid="ignore", divide="ignore"):
        teq = t * np.sqrt(r * R_SUN_M / (a * AU_M)) * (f * (1.0 - alb)) ** 0.25 * (1.0 - e ** 2) ** (-0.125)
    return _nan_where(~(t > 0) | ~(r > 0) | ~(a > 0) | ~(alb >= 0) | ~(alb < 1) | ~(e < 1), teq)


def planet_density(m_earth, r_earth):
    """Bulk density [g/cm^3]."""
    m, r = _arr(m_earth), _arr(r_earth)
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = m * M_EARTH_KG / (4.0 / 3.0 * math.pi * (r * R_EARTH_M) ** 3) / 1000.0
    return _nan_where(~(m > 0) | ~(r > 0), rho)


def planet_surface_gravity(m_earth, r_earth):
    """g [m/s^2] = G Mp / Rp^2."""
    m, r = _arr(m_earth), _arr(r_earth)
    with np.errstate(invalid="ignore", divide="ignore"):
        g = G * m * M_EARTH_KG / (r * R_EARTH_M) ** 2
    return _nan_where(~(m > 0) | ~(r > 0), g)


def escape_velocity_kms(m_earth, r_earth):
    """v_esc [km/s] = sqrt(2 G Mp / Rp)."""
    m, r = _arr(m_earth), _arr(r_earth)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.sqrt(2.0 * G * m * M_EARTH_KG / (r * R_EARTH_M)) / 1000.0
    return _nan_where(~(m > 0) | ~(r > 0), v)


# ---- Chen & Kipping (2017) mass-radius relation ----------------------------
# log10(R/R_earth) = C_i + S_i log10(M/M_earth), piecewise with continuity.
# Terran / Neptunian segments only: in the Jovian regime (M > 0.414 M_jup)
# the slope is -0.044 -- radius barely depends on mass -- so a radius
# cannot be inverted into a meaningful mass there.
CK17_S_TERRAN = 0.2790
CK17_S_NEPTUNIAN = 0.589
CK17_C_TERRAN = 0.00346
CK17_T_TERRAN_NEPTUNIAN = 2.04                                   # M_earth
CK17_T_NEPTUNIAN_JOVIAN = 0.414 * M_JUP_KG / M_EARTH_KG          # ~131.6 M_earth
CK17_SIGMA_LOG_R = {"terran": 0.0403, "neptunian": 0.146}        # intrinsic scatter in log10 R
CK17_C_NEPTUNIAN = CK17_C_TERRAN + (CK17_S_TERRAN - CK17_S_NEPTUNIAN) * math.log10(CK17_T_TERRAN_NEPTUNIAN)
CK17_R_TERRAN_MAX = 10 ** (CK17_C_TERRAN + CK17_S_TERRAN * math.log10(CK17_T_TERRAN_NEPTUNIAN))      # ~1.23 R_earth
CK17_R_NEPTUNIAN_MAX = 10 ** (CK17_C_NEPTUNIAN + CK17_S_NEPTUNIAN * math.log10(CK17_T_NEPTUNIAN_JOVIAN))  # ~14.3 R_earth


def mass_from_radius_ck17(r_earth, scatter_draws=None):
    """Planet mass [M_earth] from radius by inverting the Chen & Kipping
    (2017) Terran/Neptunian power laws. `scatter_draws` (standard-normal
    samples) adds the relation's intrinsic scatter, propagated into log M
    as sigma_logR / S. NaN above ~14.3 R_earth (Jovian degeneracy)."""
    r = _arr(r_earth)
    with np.errstate(invalid="ignore", divide="ignore"):
        log_r = np.log10(r)
        terran = r <= CK17_R_TERRAN_MAX
        s = np.where(terran, CK17_S_TERRAN, CK17_S_NEPTUNIAN)
        c = np.where(terran, CK17_C_TERRAN, CK17_C_NEPTUNIAN)
        log_m = (log_r - c) / s
        if scatter_draws is not None:
            sig = np.where(terran, CK17_SIGMA_LOG_R["terran"], CK17_SIGMA_LOG_R["neptunian"])
            log_m = log_m + _arr(scatter_draws) * sig / s
        m = 10 ** log_m
    return _nan_where(~(r > 0) | ~(r <= CK17_R_NEPTUNIAN_MAX), m)


# ---- Kopparapu et al. (2014) habitable zone --------------------------------
# S_eff = S_eff_sun + a T + b T^2 + c T^3 + d T^4, T = Teff - 5780 K,
# valid for 2600 K <= Teff <= 7200 K. Coefficients for a 1 M_earth planet
# (Kopparapu et al. 2014, Table 1).
HZ_TEFF_RANGE_K = (2600.0, 7200.0)
HZ_COEFFICIENTS = {
    "recent_venus":        (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse":  (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "maximum_greenhouse":  (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars":          (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
}


def hz_effective_flux(teff_k, boundary: str):
    """Effective stellar flux S_eff (Earth units) at an HZ boundary."""
    s0, a, b, c, d = HZ_COEFFICIENTS[boundary]
    t = _arr(teff_k) - 5780.0
    s = s0 + a * t + b * t ** 2 + c * t ** 3 + d * t ** 4
    teff = _arr(teff_k)
    return _nan_where(~(teff >= HZ_TEFF_RANGE_K[0]) | ~(teff <= HZ_TEFF_RANGE_K[1]), s)


def hz_distance_au(l_star_solar, s_eff):
    """Orbital distance [AU] receiving flux S_eff: d = sqrt(L / S_eff)."""
    l, s = _arr(l_star_solar), _arr(s_eff)
    with np.errstate(invalid="ignore", divide="ignore"):
        return _nan_where(~(l > 0) | ~(s > 0), np.sqrt(l / s))
