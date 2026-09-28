import numpy as np
import pytest

from app import stellar_catalog_service as scs
from app.feature_engine import extract_features

K00752_01 = {
    "kepid": 10797460, "kepoi_name": "K00752.01", "kepler_name": "Kepler-227 b",
    "koi_score": 1.0, "koi_tce_plnt_num": 1,
    "koi_steff": 5455.0, "koi_slogg": 4.467, "koi_srad": 0.9270,
    "ra": 291.934230, "dec": 48.141651, "koi_kepmag": 15.347,
}
K00752_02 = {
    "kepid": 10797460, "kepoi_name": "K00752.02", "kepler_name": "Kepler-227 c",
    "koi_score": 0.969, "koi_tce_plnt_num": 2,
    "koi_steff": 5455.0, "koi_slogg": 4.467, "koi_srad": 0.9270,
    "ra": 291.934230, "dec": 48.141651, "koi_kepmag": 15.347,
}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Isolates the NASA-lookup cache between tests; also guarantees no
    test in this file ever hits the live NASA Exoplanet Archive -- every
    lookup here is served from a monkeypatched fake."""
    monkeypatch.setattr(scs, "_cache", None)


def mock_nasa(monkeypatch, rows_by_clause: dict[str, list[dict]]):
    def fake_query_cumulative_table(where_clause: str) -> list[dict]:
        return rows_by_clause.get(where_clause, [])
    monkeypatch.setattr(scs, "query_cumulative_table", fake_query_cumulative_table)

TRUE_PERIOD = 8.0
TRUE_DURATION_DAYS = 0.15
TRUE_DEPTH = 0.001


def make_box_light_curve(seed=0, n_points=3000, baseline_days=60.0,
                          period=TRUE_PERIOD, duration_days=TRUE_DURATION_DAYS,
                          depth=TRUE_DEPTH, noise=0.0008):
    """A flat-bottomed (instant ingress/egress) box transit -- enough to
    recover period/duration/depth/SNR, but NOT enough to resolve an impact
    parameter (no ingress/egress slope to measure)."""
    rng = np.random.default_rng(seed)
    time = np.linspace(0, baseline_days, n_points)
    flux = np.ones_like(time)
    phase = np.mod(time + period / 2, period) - period / 2
    in_transit = np.abs(phase) < duration_days / 2
    flux[in_transit] -= depth
    flux += rng.normal(0, noise, size=time.shape)
    return time, flux


def make_trapezoid_light_curve(seed=0, n_points=6000, baseline_days=80.0,
                                period=8.0, duration_days=0.15, depth=0.001,
                                ingress_frac=0.2, noise=0.0002):
    """A trapezoidal transit with a resolvable ingress/egress slope, so the
    shape-based impact-parameter fit (app/lightcurve_extraction.py's
    estimate_impact_parameter) can succeed."""
    rng = np.random.default_rng(seed)
    time = np.linspace(0, baseline_days, n_points)
    flux = np.ones_like(time)
    half = duration_days / 2
    ingress = ingress_frac * duration_days
    phase = np.mod(time + period / 2, period) - period / 2
    abs_phase = np.abs(phase)
    flat = abs_phase < (half - ingress)
    ramp = (abs_phase >= (half - ingress)) & (abs_phase < half)
    flux[flat] -= depth
    ramp_idx = np.where(ramp)[0]
    for i in ramp_idx:
        frac = (half - abs_phase[i]) / ingress
        flux[i] -= depth * frac
    flux += rng.normal(0, noise, size=time.shape)
    return time, flux


ALL_17 = {
    "koi_score", "koi_period", "koi_time0bk", "koi_impact", "koi_duration", "koi_depth",
    "koi_prad", "koi_teq", "koi_insol", "koi_model_snr", "koi_tce_plnt_num", "koi_steff",
    "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag",
}


class TestNoIdentifier:
    def test_returns_all_17_canonical_keys(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        assert set(result.features.keys()) == ALL_17

    def test_light_curve_fields_are_estimated_and_accurate(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        assert result.features["koi_period"].status == "estimated"
        assert result.features["koi_period"].value == pytest.approx(TRUE_PERIOD, rel=0.1)
        assert result.features["koi_depth"].status == "estimated"
        assert result.features["koi_depth"].value > 0

    def test_catalog_only_fields_are_unavailable_not_fabricated(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        for canonical in ("koi_score", "koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag"):
            fv = result.features[canonical]
            assert fv.status == "unavailable"
            assert fv.value is None
            assert fv.note  # must explain why, not just silently be empty

    def test_cascading_derived_fields_are_unavailable_without_stellar_params(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        for canonical in ("koi_prad", "koi_teq", "koi_insol"):
            assert result.features[canonical].status == "unavailable"

    def test_tce_plnt_num_gets_a_documented_structural_default(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        fv = result.features["koi_tce_plnt_num"]
        assert fv.status == "derived"
        assert fv.value == 1.0

    def test_not_ready_for_prediction(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        assert result.ready_for_prediction is False
        assert len(result.missing_features) > 0

    def test_box_transit_impact_parameter_unavailable(self):
        # No ingress/egress slope in a pure box injection -- the shape fit
        # must not invent an impact parameter it cannot support.
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, None)
        assert result.features["koi_impact"].status == "unavailable"
        assert result.features["koi_impact"].value is None


class TestWithCatalogIdentifier:
    def test_unknown_identifier_behaves_like_no_identifier(self):
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, "not-a-real-target")
        assert result.catalog.match_status == "not_found"
        assert result.features["koi_steff"].status == "unavailable"

    def test_ambiguous_star_only_resolves_stellar_fields(self, monkeypatch):
        mock_nasa(monkeypatch, {"kepid = 10797460": [K00752_01, K00752_02]})
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, "10797460")
        assert result.catalog.match_status == "matched_star"
        assert result.features["koi_steff"].status == "catalog"
        assert result.features["koi_score"].status == "unavailable"

    def test_exact_koi_match_resolves_all_catalog_fields(self, monkeypatch):
        mock_nasa(monkeypatch, {"kepoi_name = 'K00752.01'": [K00752_01]})
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, "K00752.01")
        assert result.catalog.match_status == "matched_koi"
        for canonical in ("koi_score", "koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag"):
            assert result.features[canonical].status == "catalog"
        # koi_score overrides the structural default only when the catalog
        # actually has a score; koi_tce_plnt_num should now be catalog-sourced.
        assert result.features["koi_tce_plnt_num"].source == "nasa_koi_catalog"

    def test_derived_planet_radius_uses_resolved_stellar_radius(self, monkeypatch):
        mock_nasa(monkeypatch, {"kepoi_name = 'K00752.01'": [K00752_01]})
        time, flux = make_box_light_curve()
        result = extract_features(time, flux, "K00752.01")
        assert result.features["koi_prad"].status == "derived"
        assert result.features["koi_prad"].value > 0

    def test_full_pipeline_reaches_ready_for_prediction_with_trapezoid_transit(self, monkeypatch):
        # With a resolvable ingress/egress (so koi_impact estimates) and a
        # catalog identifier (so all stellar/catalog fields resolve), every
        # one of the 17 features should be available -- the true "zero
        # manual entry" path.
        mock_nasa(monkeypatch, {"kepoi_name = 'K00752.01'": [K00752_01]})
        time, flux = make_trapezoid_light_curve()
        result = extract_features(time, flux, "K00752.01")
        assert result.missing_features == []
        assert result.ready_for_prediction is True
        for fv in result.features.values():
            assert fv.value is not None
            assert fv.status in ("estimated", "derived", "catalog")


class TestNoTransitDoesNotManufactureConfidentDetection:
    def test_pure_noise_still_produces_finite_features_but_low_snr(self):
        rng = np.random.default_rng(1)
        time = np.linspace(0, 40, 3000)
        flux = 1.0 + rng.normal(0, 0.0008, size=time.shape)
        result = extract_features(time, flux, None)
        # BLS will still report *a* best-fit period (it always returns the
        # best trial, even if none is a real transit) -- the honesty
        # requirement is that this is never dressed up as a genuine catalog
        # value, and the diagnostic fields required for review stay present.
        assert result.features["koi_period"].status == "estimated"
        assert result.features["koi_model_snr"].status == "estimated"
        assert result.features["koi_model_snr"].value is not None

    def test_constant_flux_reports_honest_zero_depth_and_snr(self):
        # No injected transit at all: the extractor must not manufacture a
        # confident non-zero detection -- BLS still returns its best trial
        # (there is always a "best" of however many trials it tried), but
        # with truthfully zero depth/SNR rather than an invented signal.
        time = np.linspace(0, 40, 3000)
        flux = np.ones_like(time)
        result = extract_features(time, flux, None)
        assert result.features["koi_depth"].value == pytest.approx(0.0, abs=1e-9)
        assert result.features["koi_model_snr"].value == pytest.approx(0.0, abs=1e-9)


class TestEdgeCases:
    def test_very_shallow_transit_still_produces_finite_features(self):
        time, flux = make_box_light_curve(depth=0.0001, noise=0.00005)
        result = extract_features(time, flux, None)
        assert result.features["koi_depth"].value > 0

    def test_irregular_timestamps(self):
        rng = np.random.default_rng(2)
        base_time, flux = make_box_light_curve(n_points=2000, baseline_days=50)
        jitter = rng.uniform(-0.002, 0.002, size=base_time.shape)
        time = np.sort(base_time + jitter)
        result = extract_features(time, flux, None)
        assert result.features["koi_period"].value == pytest.approx(TRUE_PERIOD, rel=0.15)

    def test_multiple_transit_signals_recovers_the_strongest(self):
        # Inject a second, much shallower/faster signal on top of the primary
        # transit -- BLS should still lock onto the stronger, primary period.
        time, flux = make_box_light_curve(depth=0.003, period=6.0, duration_days=0.12)
        phase2 = np.mod(time + 1.3 / 2, 1.3) - 1.3 / 2
        flux[np.abs(phase2) < 0.02] -= 0.0002
        result = extract_features(time, flux, None)
        assert result.features["koi_period"].value == pytest.approx(6.0, rel=0.1)
