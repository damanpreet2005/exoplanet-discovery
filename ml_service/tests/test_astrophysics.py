import pytest

from app.astrophysics import (
    equilibrium_temperature_k,
    insolation_earth_flux,
    planet_radius_earth,
    semi_major_axis_au,
    stellar_mass_from_logg_radius,
)


class TestStellarMass:
    def test_sun_like_star(self):
        # log10(g_sun) ~= 4.438 (cgs), R = 1 Rsun -> M ~= 1 Msun
        mass = stellar_mass_from_logg_radius(4.438, 1.0)
        assert mass == pytest.approx(1.0, rel=0.05)

    def test_non_positive_radius_returns_none(self):
        assert stellar_mass_from_logg_radius(4.438, 0.0) is None
        assert stellar_mass_from_logg_radius(4.438, -1.0) is None


class TestSemiMajorAxis:
    def test_earth_sun_recovers_one_au(self):
        a = semi_major_axis_au(365.25, 1.0)
        assert a == pytest.approx(1.0, rel=0.01)

    def test_non_positive_period_returns_none(self):
        assert semi_major_axis_au(0, 1.0) is None
        assert semi_major_axis_au(-5, 1.0) is None

    def test_non_positive_mass_returns_none(self):
        assert semi_major_axis_au(365.25, 0.0) is None


class TestPlanetRadius:
    def test_earth_like_depth_around_sun_like_star(self):
        # (Rearth/Rsun)^2 ~= 8.4e-5
        rp = planet_radius_earth(8.4e-5, 1.0)
        assert rp == pytest.approx(1.0, rel=0.05)

    def test_non_positive_depth_returns_none(self):
        assert planet_radius_earth(0.0, 1.0) is None
        assert planet_radius_earth(-0.001, 1.0) is None

    def test_non_positive_radius_returns_none(self):
        assert planet_radius_earth(0.01, 0.0) is None


class TestEquilibriumTemperature:
    def test_earth_at_one_au_from_sun_like_star(self):
        # Zero-albedo, full-redistribution equilibrium temperature at 1 AU
        # from a Sun-like star is the textbook ~278-279K (Earth's commonly
        # cited ~255K already bakes in its real ~0.3 bond albedo -- see the
        # albedo test below for that case).
        teq = equilibrium_temperature_k(5772.0, 1.0, 1.0)
        assert teq == pytest.approx(278.3, rel=0.02)

    def test_earth_at_one_au_with_earths_real_albedo(self):
        teq = equilibrium_temperature_k(5772.0, 1.0, 1.0, albedo=0.3)
        assert teq == pytest.approx(255.0, rel=0.02)

    def test_non_positive_inputs_return_none(self):
        assert equilibrium_temperature_k(0, 1.0, 1.0) is None
        assert equilibrium_temperature_k(5772.0, 1.0, 0.0) is None

    def test_higher_albedo_lowers_temperature(self):
        low_albedo = equilibrium_temperature_k(5772.0, 1.0, 1.0, albedo=0.0)
        high_albedo = equilibrium_temperature_k(5772.0, 1.0, 1.0, albedo=0.5)
        assert high_albedo < low_albedo


class TestInsolation:
    def test_earth_at_one_au_from_sun_like_star_is_one(self):
        s = insolation_earth_flux(5772.0, 1.0, 1.0)
        assert s == pytest.approx(1.0, rel=0.02)

    def test_closer_orbit_gets_more_flux(self):
        near = insolation_earth_flux(5772.0, 1.0, 0.5)
        far = insolation_earth_flux(5772.0, 1.0, 2.0)
        assert near > far

    def test_non_positive_inputs_return_none(self):
        assert insolation_earth_flux(5772.0, 1.0, 0.0) is None
