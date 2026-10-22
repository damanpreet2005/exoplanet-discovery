"""
Uncertainty propagation and honest-precision formatting.

Two propagation routes, chosen per quantity by the engine:

  * analytic_first_order -- for power-law products of *independent* inputs
    (e.g. L = R^2 (T/Tsun)^4, M = g R^2 / G): relative variances add,
        (sigma_y / y)^2 = sum_i (n_i * sigma_xi / x_i)^2.
    Asymmetric catalogue errors are symmetrised (mean of + and -) for this
    route; the interval is reported as symmetric.

  * monte_carlo -- for nonlinear chains and correlated inputs (anything
    downstream of the transit fit, whose parameters are strongly
    correlated: b, a/Rstar and k especially). Inputs are sampled jointly:
    fitted parameters from a multivariate normal with the fit covariance
    (correlations preserved), catalogue values from split-normal
    distributions built from their asymmetric err1/err2 columns. Each
    derived quantity is evaluated on every sample, and reported as the
    median with the 16th-84th percentile interval.

Inputs without an uncertainty are held fixed in the Monte Carlo; every
dependent output is then flagged `complete=False` with the missing inputs
listed, because its interval underestimates the true uncertainty.

The random generator is seeded deterministically (engine config), so the
same inputs always give the same report.
"""
from __future__ import annotations

import math

import numpy as np

DEFAULT_SIG_FIGS_NO_UNCERTAINTY = 3


def split_normal(value: float, err_plus: float | None, err_minus: float | None, n: int,
                 rng: np.random.Generator) -> np.ndarray:
    """Samples a split-normal distribution: N(0, err_plus) above the value,
    N(0, err_minus) below it, each side taken with probability proportional
    to its width (so the mode stays at `value`). Missing errors -> fixed."""
    if err_plus is None and err_minus is None:
        return np.full(n, value, dtype=float)
    ep = abs(err_plus) if err_plus is not None else abs(err_minus)
    em = abs(err_minus) if err_minus is not None else ep
    if ep == 0 and em == 0:
        return np.full(n, value, dtype=float)
    upper = rng.random(n) < ep / (ep + em)
    draws = np.abs(rng.standard_normal(n))
    return np.where(upper, value + draws * ep, value - draws * em)


def multivariate_normal(mean: np.ndarray, cov: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Joint samples of correlated fit parameters (n x d)."""
    cov = 0.5 * (cov + cov.T)
    return rng.multivariate_normal(mean, cov, size=n, method="eigh")


def summarize(samples: np.ndarray) -> tuple[float, float, float] | None:
    """Median and 16th/84th-percentile distances of the finite samples, or
    None when fewer than half of the samples are finite (the quantity is
    then undefined for most of the input distribution)."""
    samples = np.asarray(samples, dtype=float)
    finite = samples[np.isfinite(samples)]
    if finite.size < max(10, samples.size // 2):
        return None
    p16, p50, p84 = np.percentile(finite, [16, 50, 84])
    return float(p50), float(p50 - p16), float(p84 - p50)


def analytic_power_law(value: float, terms: list[tuple[float, float, float | None]]) -> float | None:
    """First-order 1-sigma for y = C * prod(x_i ** n_i) with independent x_i.
    `terms` = [(x_i, n_i, sigma_i or None)]. Returns sigma_y, or None when
    every input lacks an uncertainty."""
    rel_var = 0.0
    any_sigma = False
    for x, exponent, sigma in terms:
        if sigma is None:
            continue
        any_sigma = True
        rel_var += (exponent * sigma / x) ** 2
    return abs(value) * math.sqrt(rel_var) if any_sigma else None


def symmetric_sigma(err_plus: float | None, err_minus: float | None) -> float | None:
    vals = [abs(e) for e in (err_plus, err_minus) if e is not None]
    return sum(vals) / len(vals) if vals else None


def log10_sigma(value: float, sigma: float) -> float:
    """1-sigma of x given log10(x) +- sigma -> symmetric in linear space to first order."""
    return value * math.log(10.0) * sigma


def round_sig(x: float, sig: int) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def _decimals_for(sigma: float, sig: int = 2) -> int:
    return sig - 1 - int(math.floor(math.log10(abs(sigma))))


def format_measurement(value: float | None, lower: float | None = None, upper: float | None = None,
                       sig_figs_no_uncertainty: int = DEFAULT_SIG_FIGS_NO_UNCERTAINTY) -> tuple[float | None, float | None, float | None, str]:
    """Rounds a value to the precision its uncertainty justifies: the
    smaller uncertainty to two significant figures, the value and the other
    bound to the same decimal place. Without an uncertainty, the value is
    kept to `sig_figs_no_uncertainty` significant figures (never dropping
    integer digits -- an epoch of 1345.67 stays 1346, not 1350).

    Returns (value, lower, upper, display)."""
    if value is None or not math.isfinite(value):
        return None, None, None, "Unavailable"
    sigmas = [s for s in (lower, upper) if s is not None and math.isfinite(s) and s > 0]
    if not sigmas:
        int_digits = int(math.floor(math.log10(abs(value)))) + 1 if value != 0 else 1
        sig = max(sig_figs_no_uncertainty, int_digits)
        rounded = round_sig(value, sig)
        decimals = max(sig - int_digits, 0)
        return rounded, None, None, f"{rounded:.{decimals}f}"
    decimals = _decimals_for(min(sigmas))
    rv = round(value, decimals)
    rl = round(lower, decimals) if lower is not None else None
    ru = round(upper, decimals) if upper is not None else None
    d = max(decimals, 0)
    if rl is not None and ru is not None and math.isclose(rl, ru, rel_tol=1e-9, abs_tol=10 ** -(d + 1)):
        return rv, rl, ru, f"{rv:.{d}f} ± {rl:.{d}f}"
    return rv, rl, ru, f"{rv:.{d}f} +{ru:.{d}f} / −{rl:.{d}f}"
