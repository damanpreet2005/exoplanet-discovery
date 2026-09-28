"""
Astrophysical formulas used to derive planet/orbit quantities from a transit
signal (period, depth) plus stellar parameters (temperature, surface gravity,
radius). Every function here is a standard, textbook relation -- nothing is
fit, tuned, or invented to match the trained model's output distribution.

All formulas assume:
  - A circular orbit (eccentricity = 0). The light curve alone (a single
    period + duration) does not constrain eccentricity, and no eccentricity
    value is available from the catalog fields this pipeline resolves, so
    this is the same simplifying assumption NASA's own koi_teq/koi_insol
    pipeline documentation uses.
  - The planet's mass is negligible next to the star's (true for anything
    planet-sized), so Kepler's third law is applied with the stellar mass
    alone.
  - Zero Bond albedo (A = 0) and full (day-night) heat redistribution for
    equilibrium temperature -- again matching the NASA Exoplanet Archive's
    stated convention for koi_teq, not an arbitrary choice made here.

Units in / out are explicit in every function's docstring. Internal
computation is done in SI (meters, kilograms, seconds) and converted at the
boundary, so intermediate rounding never depends on the unit the caller
happens to be thinking in.
"""
import math

# ---- physical constants (SI) -----------------------------------------------
G = 6.67430e-11          # gravitational constant, m^3 kg^-1 s^-2
M_SUN_KG = 1.98892e30     # solar mass, kg
R_SUN_M = 6.957e8         # solar radius, m
R_EARTH_M = 6.371e6       # Earth radius, m
AU_M = 1.495978707e11     # astronomical unit, m
DAY_S = 86400.0
T_SUN_EFF_K = 5772.0      # IAU nominal solar effective temperature, K


def stellar_mass_from_logg_radius(logg_cgs: float, r_star_solar: float) -> float | None:
    """Stellar mass (solar masses) from surface gravity and radius:
    g = G*M/R^2  =>  M = g*R^2/G.

    `logg_cgs` is log10(g) with g in cm/s^2 (the koi_slogg convention).
    Returns None if either input is non-positive/non-finite -- never a
    fabricated fallback mass.
    """
    if not (math.isfinite(logg_cgs) and math.isfinite(r_star_solar)) or r_star_solar <= 0:
        return None
    g_cgs = 10 ** logg_cgs
    g_si = g_cgs / 100.0  # cm/s^2 -> m/s^2
    r_m = r_star_solar * R_SUN_M
    mass_kg = g_si * r_m ** 2 / G
    if not math.isfinite(mass_kg) or mass_kg <= 0:
        return None
    return mass_kg / M_SUN_KG


def semi_major_axis_au(period_days: float, stellar_mass_solar: float) -> float | None:
    """Orbital semi-major axis (AU) from Kepler's third law:
    a^3 = G*M*T^2 / (4*pi^2), with T the orbital period and M the stellar
    mass (planet mass neglected -- see module docstring)."""
    if not (math.isfinite(period_days) and math.isfinite(stellar_mass_solar)):
        return None
    if period_days <= 0 or stellar_mass_solar <= 0:
        return None
    period_s = period_days * DAY_S
    mass_kg = stellar_mass_solar * M_SUN_KG
    a_m3 = G * mass_kg * period_s ** 2 / (4 * math.pi ** 2)
    if a_m3 <= 0:
        return None
    a_m = a_m3 ** (1 / 3)
    return a_m / AU_M


def planet_radius_earth(depth_fraction: float, r_star_solar: float) -> float | None:
    """Planet radius (Earth radii) from the transit depth and stellar radius:
    Rp/Rstar ~= sqrt(depth), so Rp = Rstar * sqrt(depth).

    This is the standard first-order relation (ignores limb darkening); it
    is the same approximation the koi_prad catalog values themselves are
    ultimately built from. Requires a positive transit depth and a positive
    stellar radius -- returns None otherwise rather than guessing."""
    if not (math.isfinite(depth_fraction) and math.isfinite(r_star_solar)):
        return None
    if depth_fraction <= 0 or r_star_solar <= 0:
        return None
    rp_over_rstar = math.sqrt(depth_fraction)
    rp_m = rp_over_rstar * r_star_solar * R_SUN_M
    return rp_m / R_EARTH_M


def equilibrium_temperature_k(steff_k: float, r_star_solar: float, a_au: float,
                               albedo: float = 0.0) -> float | None:
    """Planetary equilibrium temperature (K):
    Teq = Steff * sqrt(Rstar / (2*a)) * (1 - A)^0.25

    Assumes zero albedo and full heat redistribution (see module docstring).
    """
    if not all(math.isfinite(v) for v in (steff_k, r_star_solar, a_au)):
        return None
    if steff_k <= 0 or r_star_solar <= 0 or a_au <= 0:
        return None
    r_m = r_star_solar * R_SUN_M
    a_m = a_au * AU_M
    teq = steff_k * math.sqrt(r_m / (2 * a_m)) * (1 - albedo) ** 0.25
    return teq if math.isfinite(teq) and teq > 0 else None


def insolation_earth_flux(steff_k: float, r_star_solar: float, a_au: float) -> float | None:
    """Stellar insolation received by the planet, in units of Earth's
    insolation (S_earth = 1 at 1 AU from a Sun-like star):

    S = (Rstar/Rsun)^2 * (Steff/Tsun)^4 / (a/AU)^2
    """
    if not all(math.isfinite(v) for v in (steff_k, r_star_solar, a_au)):
        return None
    if steff_k <= 0 or r_star_solar <= 0 or a_au <= 0:
        return None
    insol = (r_star_solar ** 2) * (steff_k / T_SUN_EFF_K) ** 4 / (a_au ** 2)
    return insol if math.isfinite(insol) and insol > 0 else None
