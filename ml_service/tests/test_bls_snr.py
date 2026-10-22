"""
Transit-search (BLS) signal-to-noise ratio.

The statistic is astropy BoxLeastSquares' depth_snr at the best box, with the
per-point noise supplied:

    SNR = depth / (sigma sqrt(1/N_in + 1/N_out))  ~  (depth / sigma) sqrt(N_in)

combined over every observed transit. Before the fix no `dy` was passed, so
astropy used sigma = 1 (flux units) and the "SNR" was depth x sqrt(N_in)
(0.00432 for Kepler-227 b instead of ~29).

Light curves are synthetic box transits for exact scaling checks (white
noise, no limb darkening), plus the project's limb-darkened Kepler-227 b test
file for the real pipeline.
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.lightcurve_extraction import _phase, robust_point_noise, run_box_least_squares

REPO = Path(__file__).resolve().parents[2]


def box_lc(depth=1e-3, noise=1e-4, period=3.0, baseline=60.0, cadence=0.0204, duration=0.12, seed=0):
    t = np.arange(0.0, baseline, cadence)
    f = np.ones_like(t)
    f[np.abs(((t - 1.0 + 0.5 * period) % period) - 0.5 * period) < duration / 2] -= depth
    return t, f + np.random.default_rng(seed).normal(0.0, noise, t.size)


def reference_snr(t, f, bls):
    """Independent calculation from the definition, with the injected noise."""
    ph = _phase(t, bls.period_days, bls.transit_epoch) * bls.period_days
    inn = np.abs(ph) < 0.5 * bls.duration_hours / 24
    depth = np.mean(f[~inn]) - np.mean(f[inn])
    sigma = robust_point_noise(f)
    return depth / (sigma * math.sqrt(1 / inn.sum() + 1 / (~inn).sum())), int(inn.sum())


def test_matches_an_independent_reference_calculation():
    t, f = box_lc()
    bls = run_box_least_squares(t, f)
    ref, n_in = reference_snr(t, f, bls)
    assert bls.n_in_transit == n_in
    assert bls.snr == pytest.approx(ref, rel=0.02)
    # Order of magnitude from the simplified formula: (depth/sigma) sqrt(N_in).
    assert bls.snr == pytest.approx(1e-3 / 1e-4 * math.sqrt(n_in), rel=0.1)


def test_noise_estimate_recovers_the_injected_sigma_and_ignores_transits():
    t, f = box_lc(depth=5e-3, noise=2e-4)
    assert robust_point_noise(f) == pytest.approx(2e-4, rel=0.05)


def test_scales_linearly_with_depth():
    s1 = run_box_least_squares(*box_lc(depth=1e-3)).snr
    s2 = run_box_least_squares(*box_lc(depth=2e-3)).snr
    assert s2 / s1 == pytest.approx(2.0, rel=0.1)


def test_scales_inversely_with_noise():
    s1 = run_box_least_squares(*box_lc(noise=1e-4)).snr
    s2 = run_box_least_squares(*box_lc(noise=2e-4)).snr
    assert s1 / s2 == pytest.approx(2.0, rel=0.15)


def test_grows_as_sqrt_of_in_transit_points_across_transits():
    """Four times the baseline -> four times the transits -> ~2x the SNR."""
    short = run_box_least_squares(*box_lc(baseline=30.0))
    long_ = run_box_least_squares(*box_lc(baseline=120.0))
    assert long_.n_in_transit / short.n_in_transit == pytest.approx(4.0, rel=0.1)
    assert long_.snr / short.snr == pytest.approx(2.0, rel=0.15)


def test_is_dimensionless_and_independent_of_flux_units():
    t, f = box_lc()
    a = run_box_least_squares(t, f)
    b = run_box_least_squares(t, f * 1.0)      # already normalized
    c = run_box_least_squares(t, (f * 3.7e4) / np.median(f * 3.7e4))   # electrons/s, renormalized
    assert a.snr == pytest.approx(b.snr) and a.snr == pytest.approx(c.snr, rel=1e-6)


def test_constant_flux_gives_no_snr_rather_than_zero():
    t = np.arange(0.0, 30.0, 0.0204)
    bls = run_box_least_squares(t, np.ones_like(t))
    assert bls.snr is None and bls.noise_ppm is None


def test_pure_noise_stays_below_the_detection_threshold_typically():
    snrs = [run_box_least_squares(*box_lc(depth=0.0, seed=s)).snr for s in range(4)]
    # The best of many trial boxes in pure noise is biased upward, but well below a real transit.
    assert all(s is not None for s in snrs) and max(snrs) < 15
    assert run_box_least_squares(*box_lc(depth=1e-3)).snr > 25


def test_snr_power_and_sde_are_different_statistics():
    t, f = box_lc()
    lo = run_box_least_squares(t, f)
    # Doubling the noise halves the SNR, quarters the likelihood power, and
    # leaves the SDE (a normalised peak height) roughly unchanged.
    t2, f2 = box_lc(noise=2e-4)
    hi = run_box_least_squares(t2, f2)
    assert lo.snr / hi.snr == pytest.approx(2.0, rel=0.15)
    assert lo.power / hi.power == pytest.approx(4.0, rel=0.3)
    assert lo.sde > 5 and hi.sde > 5
    assert lo.snr != pytest.approx(lo.power) and lo.snr != pytest.approx(lo.sde)


def test_project_confirmed_planet_file():
    """Kepler-227 b test light curve (limb-darkened, 150 ppm, 29.4-min cadence):
    the previous value was 0.00432 (sigma = 1); with sigma = 150 ppm it is ~29,
    above Kepler's 7.1 detection threshold."""
    d = pd.read_csv(REPO / "test_light_curves" / "1_confirmed_planet_Kepler-227b_KIC10797460.csv")
    f = d.flux.values / np.median(d.flux.values)
    bls = run_box_least_squares(d.time.values, f)
    assert bls.noise_ppm == pytest.approx(150, rel=0.05)
    assert 20 < bls.snr < 40
    ref, _ = reference_snr(d.time.values, f, bls)
    assert bls.snr == pytest.approx(ref, rel=0.05)
    # The unit-weight value it used to report:
    assert bls.depth_fraction / math.sqrt(1 / bls.n_in_transit + 1 / (len(f) - bls.n_in_transit)) == \
        pytest.approx(0.00432, rel=0.05)
