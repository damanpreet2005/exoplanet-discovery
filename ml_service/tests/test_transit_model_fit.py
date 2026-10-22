"""
Injection-recovery tests for the transit-model fit (app/characterization/
transit_fit.py). Light curves are generated with the engine's own validated
transit model (see test_characterization_physics.py for its check against
the analytic uniform-disk solution) plus seeded Gaussian noise, so every
"truth" value is known exactly. Tolerances are stated per assertion.
"""
import math

import numpy as np
import pytest

from app.characterization.transit_fit import FIT_FAILED, FIT_FITTED, FIT_NO_TRANSIT, fit_transit
from app.characterization.transit_model import transit_flux
from app.lightcurve_extraction import compute_feature_vector

LD = (0.4, 0.26)
CADENCE = 0.0204  # Kepler long cadence, days


def _lightcurve(t0=2.3, period=6.1, k=0.03, a_rs=15.0, b=0.3, noise=1e-4, baseline=90.0, seed=1,
                cadence=CADENCE, timing_offsets=None):
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, baseline, cadence)
    if timing_offsets is None:
        f = transit_flux(t, t0, period, k, a_rs, b, *LD, cadence, 7)
    else:
        # Shift each transit individually (transit timing variations).
        f = np.ones_like(t)
        n = np.round((t - t0) / period)
        for epoch in np.unique(n):
            sel = n == epoch
            shift = timing_offsets(int(epoch))
            f[sel] = transit_flux(t[sel], t0 + shift, period, k, a_rs, b, *LD, cadence, 7)
    return t, f + rng.normal(0.0, noise, t.size)


def _fit(t, f, **kw):
    ext = compute_feature_vector(t, f)
    b = ext.bls
    return fit_transit(t, f, b.period_days, b.transit_epoch, b.duration_hours / 24.0, b.depth_fraction, b.snr, **kw)


def test_recovers_injected_parameters_within_uncertainties():
    truth = dict(t0=2.3, period=6.1, k=0.03, a_rs=15.0, b=0.3)
    t, f = _lightcurve(**truth)
    r = _fit(t, f)
    assert r.status == FIT_FITTED and r.converged
    assert r.period_constrained and r.n_transits_with_data == 15
    # Period and radius ratio: within 3 sigma of truth, and tightly constrained.
    assert abs(r.params["period"] - truth["period"]) < 3 * r.errors["period"]
    assert r.errors["period"] < 1e-3
    assert abs(r.params["k"] - truth["k"]) < 3 * r.errors["k"]
    assert r.params["k"] == pytest.approx(truth["k"], rel=0.1)
    # Epoch refers to the reference transit nearest the data midpoint.
    n_ref = round((r.params["t0"] - truth["t0"]) / truth["period"])
    assert abs(r.params["t0"] - (truth["t0"] + n_ref * truth["period"])) < 3 * r.errors["t0"]
    # White Gaussian noise: reduced chi^2 ~ 1, no red-noise inflation.
    assert r.reduced_chi2 == pytest.approx(1.0, abs=0.15)
    assert r.beta_red_noise == pytest.approx(1.0, abs=0.2)
    assert r.noise_per_point_ppm == pytest.approx(100.0, rel=0.1)
    # Model depth vs the limb-darkened expectation at the true geometry.
    assert r.depth == pytest.approx(0.03 ** 2 * 1.1, rel=0.15)


def test_snr_definition_scales_with_noise():
    t, f_lo = _lightcurve(noise=1e-4, seed=2)
    _, f_hi = _lightcurve(noise=4e-4, seed=2)
    snr_lo, snr_hi = _fit(t, f_lo).snr, _fit(t, f_hi).snr
    # SNR = depth / sigma * sqrt(N_in): 4x the noise -> ~1/4 the SNR.
    assert snr_lo / snr_hi == pytest.approx(4.0, rel=0.25)
    assert snr_lo > 50


def test_individual_transit_times_and_linear_ephemeris():
    t, f = _lightcurve(noise=1e-4, seed=3)
    r = _fit(t, f)
    assert len(r.transit_times) >= 12
    eph = r.ephemeris
    assert eph["period"] == pytest.approx(6.1, abs=3 * eph["period_error"])
    assert eph["p_value"] > 0.001  # no timing variations injected
    assert "consistent with a linear ephemeris" in r.timing_assessment
    errors_min = [tt.error * 1440 for tt in r.transit_times]
    assert 0.5 < np.median(errors_min) < 10  # minute-level timing at this SNR


def test_injected_ttvs_are_flagged():
    amp = 15.0 / 1440.0  # 15-minute sinusoidal TTVs
    t, f = _lightcurve(noise=5e-5, seed=4, timing_offsets=lambda n: amp * math.sin(2 * math.pi * n / 7.0))
    r = _fit(t, f)
    assert r.ephemeris is not None and r.ephemeris["p_value"] < 1e-3
    assert "deviate from a linear ephemeris" in r.timing_assessment
    assert r.ephemeris["oc_rms_minutes"] == pytest.approx(15.0 / math.sqrt(2), rel=0.35)


def test_single_transit_does_not_constrain_period():
    t, f = _lightcurve(period=60.0, t0=20.0, baseline=50.0, k=0.05, a_rs=60.0, seed=5)
    r = fit_transit(t, f, 60.0, 20.0, 0.26, 0.0027)
    assert r.status == FIT_FITTED
    assert not r.period_constrained
    assert "period" not in r.errors
    assert r.n_transits_with_data == 1
    assert any("one transit" in w for w in r.warnings)
    assert r.ephemeris is None


def test_no_positive_depth_is_reported_as_no_transit():
    t, f = _lightcurve(k=0.0001, seed=6)
    r = fit_transit(t, f, 6.1, 2.3, 0.1, 0.0)
    assert r.status == FIT_NO_TRANSIT
    assert r.params == {} and r.depth is None and r.snr is None


def test_pure_noise_gives_insignificant_snr():
    rng = np.random.default_rng(7)
    t = np.arange(0.0, 60.0, CADENCE)
    f = 1.0 + rng.normal(0.0, 1e-4, t.size)
    r = _fit(t, f)
    # Whatever the search latches onto, the fitted signal is not significant.
    assert r.status in (FIT_FITTED, FIT_FAILED, FIT_NO_TRANSIT)
    if r.status == FIT_FITTED:
        assert r.snr < 7.1


def test_grazing_transit_is_recovered_as_grazing():
    t, f = _lightcurve(k=0.1, b=1.0, a_rs=12.0, noise=1e-4, seed=8)
    r = _fit(t, f)
    assert r.status == FIT_FITTED
    assert r.params["b"] > 1 - r.params["k"]
    assert r.t23_days is None


def test_red_noise_inflates_uncertainties():
    t, f_white = _lightcurve(noise=1e-4, seed=9)
    rng = np.random.default_rng(10)
    # Add noise correlated on ~1-hour timescales (comparable to ingress/T14),
    # twice the white-noise level.
    kernel = np.exp(-np.arange(-10, 11) ** 2 / (2 * 2.0 ** 2))
    red = np.convolve(rng.normal(0, 1, t.size), kernel / kernel.sum(), mode="same")
    f_red = f_white + red / red.std() * 2e-4
    r_white, r_red = _fit(t, f_white), _fit(t, f_red)
    assert r_red.beta_red_noise > 1.2
    # Period precision is insensitive to the b-k degeneracy, so it isolates
    # the noise inflation: the red-noise fit must report a larger error ...
    assert r_red.errors["period"] > 1.5 * r_white.errors["period"]
    # ... and the truth must still lie inside it.
    assert abs(r_red.params["period"] - 6.1) < 3 * r_red.errors["period"]
