"""
Uncertainty propagation and honest-precision formatting.

Two propagation routes, chosen per quantity by the engine:

  * analytic_first_order -- for power-law products of *independent* inputs
    (e.g. L = R^2 (T/Tsun)^4, M = g R^2 / G): relative variances add,
        (sigma_y / y)^2 = sum_i (n_i * sigma_xi / x_i)^2.
    Asymmetric catalogue errors are symmetrised (mean of + and -) for this
    route; the interval is reported as symmetric.

  * mcmc -- for nonlinear chains and correlated inputs (anything downstream
    of the transit fit, whose parameters are strongly correlated: b, a/Rstar
    and k especially). Every uncertain input is sampled by Markov chain Monte
    Carlo (random-walk Metropolis, below) from its intended distribution;
    each derived quantity is evaluated on every retained chain sample and
    reported as the median with the 16th-84th percentile interval.

MCMC SAMPLER
Target distributions (one sampler "block" per independent input):
  * catalogue values and expert overrides with an uncertainty: the split
    (two-piece) normal with mode at the value and widths err_plus above /
    err_minus below -- the distribution implied by asymmetric err1/err2
    columns. Unbounded, as before.
  * transit-fit parameters (jointly): the multivariate normal with the fit's
    linearised covariance (correlations preserved), restricted to the
    physical domain k > 0, a/R* > 1, 0 <= b^2 < (1+k)^2 (density zero
    outside). This is the Gaussian approximation of the fit, not a posterior
    re-fitted to the light curve. The chain runs in whitened coordinates
    (x = mean + A y, A A^T = cov), which also handles singular covariances.
  * standard-normal latent variables (the Chen & Kipping intrinsic scatter,
    the split-lognormal transit-only stellar density).
There is no likelihood beyond these densities: each block's log-density is
the log of its target, -inf outside its support.

Algorithm: `n_chains` independent random-walk Metropolis chains per block,
proposal x' = x + s L z (z ~ N(0, I); L the target's scale, so the proposal
matches its shape), accepted with probability min(1, p(x')/p(x)). Chains
start over-dispersed (centre + 2 L z, pulled toward the centre until inside
the support). During `burn_in` iterations the global scale s is adapted
towards the optimal acceptance rate (0.44 in 1-D, 0.234 otherwise); burn-in
draws are discarded and s is then frozen, so the retained draws come from a
fixed Metropolis kernel whose stationary distribution is the target. Every
`thin`-th draw is retained until `n_samples` draws are pooled over chains
(chain-major order).

Blocks are independent in the intended joint distribution, so pairing the
i-th retained draw of every block is a draw from the product target; the
correlations that matter (within the fit block, and those induced by shared
inputs such as M* and R*, or Mp and Rp through the mass-radius relation) are
preserved because every derived quantity is computed per sample index.

Convergence: per block, split-R-hat (Gelman et al. 2013, BDA3 sec. 11.4) and
the multi-chain effective sample size (BDA3 sec. 11.5, Geyer initial
monotone sequence) on every retained coordinate. A block is converged when
max R-hat <= `rhat_threshold` and min ESS >= `min_ess`. Non-converged blocks
are reported, and everything computed from their samples is flagged.

Inputs without an uncertainty are held fixed (no chain); every dependent
output is then flagged `complete=False` with the missing inputs listed,
because its interval underestimates the true uncertainty.

The random generator is seeded deterministically (engine config), so the
same inputs always give the same report.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

DEFAULT_SIG_FIGS_NO_UNCERTAINTY = 3


class SamplingError(RuntimeError):
    """An MCMC block could not be run (e.g. no starting point in the support)."""


@dataclass(frozen=True)
class MCMCSettings:
    n_samples: int          # retained draws, pooled over chains
    n_chains: int
    burn_in: int            # discarded iterations per chain (proposal adaptation happens only here)
    thin: int               # keep every thin-th post-burn-in iteration
    rhat_threshold: float
    min_ess: float

    @property
    def retained_per_chain(self) -> int:
        return -(-self.n_samples // self.n_chains)

    @property
    def iterations_per_chain(self) -> int:
        return self.burn_in + self.retained_per_chain * self.thin


@dataclass
class ChainDiagnostics:
    block: str
    parameters: list[str]
    target: str
    dimension: int
    converged: bool
    acceptance_rate: float | None = None
    proposal_scale: float | None = None
    rhat: float | None = None           # max over coordinates
    ess: float | None = None            # min over coordinates
    message: str = ""
    per_parameter: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        def r(x, nd=4):
            return None if x is None or not math.isfinite(x) else round(float(x), nd)
        return {"block": self.block, "parameters": self.parameters, "target": self.target,
                "dimension": self.dimension, "converged": self.converged,
                "acceptance_rate": r(self.acceptance_rate, 3), "proposal_scale": r(self.proposal_scale),
                "rhat": r(self.rhat), "ess": r(self.ess, 0), "message": self.message,
                "per_parameter": {k: {"rhat": r(v["rhat"]), "ess": r(v["ess"], 0)}
                                  for k, v in self.per_parameter.items()}}


def _split_rhat_ess(draws: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split-R-hat and multi-chain ESS per coordinate of `draws` (m, C, d).
    Each chain is split in half (2C sequences of length m // 2)."""
    half = draws.shape[0] // 2
    d = draws.shape[2]
    if half < 2:
        return np.full(d, np.nan), np.full(d, np.nan)
    x = np.concatenate([draws[:half], draws[-half:]], axis=1)       # (n, M, d)
    n, m_seq = x.shape[0], x.shape[1]
    w = x.var(axis=0, ddof=1).mean(axis=0)
    b = n * x.mean(axis=0).var(axis=0, ddof=1)
    var_plus = (n - 1) / n * w + b / n
    rhat = np.ones(d)
    ess = np.full(d, float(n * m_seq))
    for j in range(d):
        if not (w[j] > 0 and var_plus[j] > 0):
            continue                                # constant coordinate: nothing to diagnose
        rhat[j] = math.sqrt(var_plus[j] / w[j])
        xj = x[:, :, j]

        def rho(t):
            return 1.0 - np.mean((xj[t:] - xj[:-t]) ** 2) / (2.0 * var_plus[j])

        # Geyer's initial monotone sequence over pairs (rho_2k + rho_2k+1).
        tau, prev, k = -1.0, math.inf, 0
        while 2 * k + 1 < n:
            pair = (1.0 if k == 0 else rho(2 * k)) + rho(2 * k + 1)
            if pair <= 0:
                break
            pair = min(pair, prev)
            tau += 2.0 * pair
            prev, k = pair, k + 1
        ess[j] = n * m_seq / max(tau, 1.0 / math.log10(max(n * m_seq, 10)))
    return rhat, ess


def overdispersed_init(center: np.ndarray, scale: np.ndarray, log_prob: Callable[[np.ndarray], np.ndarray],
                       n_chains: int, rng: np.random.Generator, spread: float = 2.0) -> np.ndarray:
    """Starting points centre + spread * L z, each pulled halfway toward the
    centre (up to 30 times) until it lies in the target's support; chains
    that never do start at the centre. Raises SamplingError when even the
    centre is outside the support."""
    center = np.asarray(center, dtype=float)
    if not np.all(np.isfinite(log_prob(center[None, :]))):
        raise SamplingError("the central value lies outside the target's support")
    x = center + spread * rng.standard_normal((n_chains, center.size)) @ scale.T
    for _ in range(30):
        bad = ~np.isfinite(log_prob(x))
        if not bad.any():
            break
        x[bad] = center + 0.5 * (x[bad] - center)
    x[~np.isfinite(log_prob(x))] = center
    return x


def run_metropolis(log_prob: Callable[[np.ndarray], np.ndarray], init: np.ndarray, scale: np.ndarray,
                   settings: MCMCSettings, rng: np.random.Generator, *, block: str, parameters: list[str],
                   target: str, transform: Callable[[np.ndarray], np.ndarray] | None = None
                   ) -> tuple[np.ndarray, ChainDiagnostics]:
    """Random-walk Metropolis, vectorised over chains. `log_prob` maps
    (C, d) states to (C,) log-densities (-inf outside the support); `scale`
    (d x d) shapes the proposal. `transform` maps retained states to the
    reported coordinates (diagnostics are computed on those). Returns the
    retained samples (n_samples x d_out) and their diagnostics."""
    x = np.array(init, dtype=float)
    n_chains, dim = x.shape
    lp = log_prob(x)
    if not np.all(np.isfinite(lp)):
        raise SamplingError("a chain started outside the target's support")
    target_acc = 0.44 if dim == 1 else 0.234
    log_s = math.log(2.38 / math.sqrt(dim))
    per_chain = settings.retained_per_chain
    total = settings.iterations_per_chain
    eps = rng.standard_normal((total, n_chains, dim)) @ scale.T
    log_u = np.log(rng.random((total, n_chains)))
    kept = np.empty((per_chain, n_chains, dim))
    window_acc, window_len, n_windows, post_acc = 0, 0, 0, 0
    for it in range(total):
        prop = x + math.exp(log_s) * eps[it]
        lp_prop = log_prob(prop)
        with np.errstate(invalid="ignore"):
            accept = log_u[it] < (lp_prop - lp)
        x = np.where(accept[:, None], prop, x)
        lp = np.where(accept, lp_prop, lp)
        if it < settings.burn_in:
            window_acc += int(accept.sum())
            window_len += 1
            if window_len == 25:
                n_windows += 1
                log_s += (window_acc / (25 * n_chains) - target_acc) / math.sqrt(n_windows)
                window_acc, window_len = 0, 0
        else:
            post_acc += int(accept.sum())
            j = it - settings.burn_in
            if (j + 1) % settings.thin == 0:
                kept[j // settings.thin] = x
    if transform is not None:
        kept = transform(kept.reshape(-1, dim)).reshape(per_chain, n_chains, -1)
    rhat, ess = _split_rhat_ess(kept)
    diagnosable = bool(np.all(np.isfinite(rhat)) and np.all(np.isfinite(kept)))
    rhat_max = float(np.max(rhat)) if diagnosable else None
    ess_min = float(np.min(ess)) if diagnosable else None
    converged = diagnosable and rhat_max <= settings.rhat_threshold and ess_min >= settings.min_ess
    if not diagnosable:
        message = "Convergence could not be assessed (too few retained draws per chain, or non-finite draws)."
    elif not converged:
        message = (f"Not converged: max R-hat = {rhat_max:.3f} (threshold {settings.rhat_threshold}), "
                   f"min ESS = {ess_min:.0f} (threshold {settings.min_ess:g}).")
    else:
        message = ""
    samples = kept.transpose(1, 0, 2).reshape(-1, kept.shape[2])[: settings.n_samples]
    diag = ChainDiagnostics(
        block=block, parameters=list(parameters), target=target, dimension=dim, converged=converged,
        acceptance_rate=post_acc / max(1, (total - settings.burn_in) * n_chains), proposal_scale=math.exp(log_s),
        rhat=rhat_max, ess=ess_min, message=message,
        per_parameter={p: {"rhat": float(rhat[i]), "ess": float(ess[i])} for i, p in enumerate(parameters)
                       if i < rhat.size})
    return samples, diag


def split_normal_log_prob(value: float, err_plus: float, err_minus: float) -> Callable[[np.ndarray], np.ndarray]:
    """Log-density (up to a constant) of the split normal: N(value, err_plus)
    above the value, N(value, err_minus) below it. A zero-width side has no
    support beyond the value."""
    def log_prob(x: np.ndarray) -> np.ndarray:
        dx = x[:, 0] - value
        out = np.full(dx.shape, -np.inf)
        up = dx >= 0
        if err_plus > 0:
            out[up] = -0.5 * (dx[up] / err_plus) ** 2
        else:
            out[up & (dx == 0)] = 0.0
        if err_minus > 0:
            out[~up] = -0.5 * (dx[~up] / err_minus) ** 2
        return out
    return log_prob


def split_normal_widths(err_plus: float | None, err_minus: float | None) -> tuple[float, float] | None:
    """(err_plus, err_minus) as non-negative widths, a missing side mirroring
    the other; None when the value has no uncertainty (held fixed)."""
    if err_plus is None and err_minus is None:
        return None
    ep = abs(err_plus) if err_plus is not None else abs(err_minus)
    em = abs(err_minus) if err_minus is not None else ep
    if ep == 0 and em == 0:
        return None
    return ep, em


def standard_normal_log_prob(x: np.ndarray) -> np.ndarray:
    return -0.5 * np.sum(x ** 2, axis=1)


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
