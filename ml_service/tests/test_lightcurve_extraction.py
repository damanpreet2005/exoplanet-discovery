import numpy as np
import pytest

from app.lightcurve_extraction import (
    LightCurveValidationError,
    compute_feature_vector,
    parse_time_flux_csv,
    run_box_least_squares,
)

TRUE_PERIOD = 5.0
TRUE_DURATION_DAYS = 0.12
TRUE_DEPTH = 0.01


def make_synthetic_light_curve(seed=0, n_points=3000, baseline_days=40.0):
    rng = np.random.default_rng(seed)
    time = np.linspace(0, baseline_days, n_points)
    flux = np.ones_like(time)
    phase = np.mod(time, TRUE_PERIOD)
    in_transit = (phase < TRUE_DURATION_DAYS / 2) | (phase > TRUE_PERIOD - TRUE_DURATION_DAYS / 2)
    flux[in_transit] -= TRUE_DEPTH
    flux += rng.normal(0, 0.0008, size=time.shape)
    return time, flux


def make_csv_bytes(time, flux, extra_cols=False):
    lines = ["time,flux" + (",flux_err" if extra_cols else "")]
    for t, f in zip(time, flux):
        row = f"{t},{f}"
        if extra_cols:
            row += ",0.001"
        lines.append(row)
    return ("\n".join(lines) + "\n").encode("utf-8")


class TestParseTimeFluxCsv:
    def test_parses_valid_light_curve(self):
        time, flux = make_synthetic_light_curve()
        t_arr, f_arr, dropped = parse_time_flux_csv(make_csv_bytes(time, flux))
        assert len(t_arr) == len(time)
        assert dropped == 0

    def test_ignores_extra_columns(self):
        time, flux = make_synthetic_light_curve()
        t_arr, f_arr, dropped = parse_time_flux_csv(make_csv_bytes(time, flux, extra_cols=True))
        assert len(t_arr) == len(time)

    def test_case_insensitive_headers(self):
        raw = b"TIME,FLUX\n0.0,1.0\n" + b"\n".join(
            f"{i * 0.1},{1.0 + 0.001 * i}".encode() for i in range(1, 40)
        )
        t_arr, f_arr, dropped = parse_time_flux_csv(raw)
        assert len(t_arr) == 40

    def test_missing_flux_and_brightness_column_raises(self):
        with pytest.raises(LightCurveValidationError):
            parse_time_flux_csv(b"time,magnitude\n1,2\n")

    def test_brightness_is_accepted_as_a_flux_alias(self):
        time, flux = make_synthetic_light_curve()
        lines = ["time,brightness"] + [f"{t},{f}" for t, f in zip(time, flux)]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        t_arr, f_arr, dropped = parse_time_flux_csv(raw)
        assert len(t_arr) == len(time)
        assert dropped == 0

    def test_brightness_column_name_is_case_insensitive(self):
        time, flux = make_synthetic_light_curve(n_points=40, baseline_days=1.0)
        lines = ["TIME,BRIGHTNESS"] + [f"{t},{f}" for t, f in zip(time, flux)]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        t_arr, f_arr, dropped = parse_time_flux_csv(raw)
        assert len(t_arr) == 40

    def test_empty_file_raises(self):
        with pytest.raises(LightCurveValidationError):
            parse_time_flux_csv(b"")

    def test_too_few_points_raises(self):
        raw = b"time,flux\n" + b"\n".join(f"{i},1.0".encode() for i in range(5))
        with pytest.raises(LightCurveValidationError):
            parse_time_flux_csv(raw)

    def test_too_many_points_raises(self):
        from app.lightcurve_extraction import MAX_POINTS

        time, flux = make_synthetic_light_curve(n_points=MAX_POINTS + 1, baseline_days=200)
        with pytest.raises(LightCurveValidationError):
            parse_time_flux_csv(make_csv_bytes(time, flux))

    def test_drops_rows_with_nan_or_bad_values(self):
        time, flux = make_synthetic_light_curve(n_points=100, baseline_days=10)
        lines = ["time,flux"]
        for t, f in zip(time, flux):
            lines.append(f"{t},{f}")
        lines.append("5.0,not_a_number")
        lines.append("6.0,nan")
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        t_arr, f_arr, dropped = parse_time_flux_csv(raw)
        assert dropped == 2

    def test_tiny_time_range_is_not_rejected_by_any_baseline_check(self):
        # There is no observation-baseline/minimum-duration validation at all
        # -- only column presence and point-count sufficiency are checked.
        time = np.linspace(0, 0.0005, 40)
        raw = b"time,flux\n" + b"\n".join(f"{t},1.0".encode() for t in time)
        # Should not raise for baseline reasons; may still raise if BLS itself
        # can't find a candidate period, which is a different, unrelated path.
        try:
            t_arr, f_arr, dropped = parse_time_flux_csv(raw)
        except LightCurveValidationError as exc:
            assert "baseline" not in str(exc).lower()
        else:
            assert (t_arr[-1] - t_arr[0]) == pytest.approx(0.0005, rel=0.05)


class TestBoxLeastSquares:
    def test_recovers_injected_period_and_positive_depth(self):
        time, flux = make_synthetic_light_curve()
        normalized = flux / np.median(flux)
        result = run_box_least_squares(time, normalized)
        assert result.period_days == pytest.approx(TRUE_PERIOD, rel=0.1)
        assert result.depth_ppm > 0
        assert result.duration_hours > 0
        assert result.snr > 0

    def test_large_realistic_light_curve_stays_fast_and_accurate(self):
        """Regression test for the bug that caused real (larger) uploads to
        time out: astropy's default period grid can reach hundreds of
        millions of trial periods for a long-baseline light curve, taking
        minutes. This must stay bounded regardless of input size."""
        import time as time_module

        time, flux = make_synthetic_light_curve(n_points=40000, baseline_days=300)
        normalized = flux / np.median(flux)
        start = time_module.perf_counter()
        result = run_box_least_squares(time, normalized)
        elapsed = time_module.perf_counter() - start
        assert elapsed < 5.0, f"BLS search took {elapsed:.2f}s, expected well under 5s"
        assert result.period_days == pytest.approx(TRUE_PERIOD, rel=0.1)


class TestComputeFeatureVector:
    def test_produces_17_finite_features_with_only_time_and_flux(self):
        time, flux = make_synthetic_light_curve()
        extraction = compute_feature_vector(time, flux)
        assert len(extraction.features) == 17
        assert all(np.isfinite(v) for v in extraction.features)

    def test_recovers_period_end_to_end(self):
        time, flux = make_synthetic_light_curve()
        extraction = compute_feature_vector(time, flux)
        assert extraction.features[0] == pytest.approx(TRUE_PERIOD, rel=0.1)

    def test_odd_even_ratio_close_to_one_for_a_real_planet_signal(self):
        # A genuine (non-eclipsing-binary) transit should show consistent
        # depth between odd- and even-numbered transits.
        time, flux = make_synthetic_light_curve()
        extraction = compute_feature_vector(time, flux)
        odd_even_ratio = extraction.characterisation["odd_even_depth_ratio"]
        assert odd_even_ratio == pytest.approx(1.0, abs=0.5)

    def test_no_secondary_eclipse_for_a_symmetric_transit_injection(self):
        time, flux = make_synthetic_light_curve()
        extraction = compute_feature_vector(time, flux)
        # No secondary eclipse was injected, so its depth should be small
        # relative to the primary transit depth.
        assert abs(extraction.characterisation["secondary_eclipse_depth_ppm"]) < extraction.characterisation["bls_depth_ppm"]

    def test_characterisation_has_no_stellar_dependent_fields(self):
        time, flux = make_synthetic_light_curve()
        extraction = compute_feature_vector(time, flux)
        for forbidden_key in ("estimated_planet_radius_rearth", "estimated_equilibrium_temp_k", "stellar_teff_k"):
            assert forbidden_key not in extraction.characterisation
