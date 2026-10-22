"""
Transit-model fit of an uploaded light curve, seeded by the existing Box
Least Squares search (app/lightcurve_extraction.py, unchanged).

PIPELINE
 1. Ephemeris seed: BLS period P, epoch t0, box duration T.
 2. Local detrending: for every predicted transit epoch with data, the
    points within +-1.5 T of mid-transit are divided by a straight line
    fitted to that window's out-of-transit points (|dt| > 0.75 T; the
    margin allows for BLS boxes that underestimate the true T14). This
    removes slow stellar/instrumental trends without touching the transit.
 3. Photometric noise: sigma_1 = 1.4826 * MAD of the detrended
    out-of-transit points. The CSV contract is time + flux only, so per-point
    uncertainties are estimated empirically rather than read from the file.
 4. Global least-squares fit (scipy.optimize.least_squares, trust-region,
    bounded) of the limb-darkened circular-orbit model in transit_model.py
    for (t0, P, k = Rp/Rstar, a/Rstar, b^2), restarted from three impact
    parameters to avoid the well-known b - a/Rstar local minima. With a
    single observed transit, P is not fitted (it is not constrained) and is
    held at the BLS value.
 5. Parameter covariance from the Jacobian at the optimum, inflated by
    max(1, reduced chi^2) and by the time-averaging red-noise factor beta^2
    (Pont, Zucker & Queloz 2006; Winn et al. 2008), so correlated noise does
    not produce over-precise parameters.
 6. Individual transit times: each sufficiently covered transit is refitted
    for its own mid-time with the shape fixed at the global solution.
 7. Linear ephemeris t_n = T0 + n P (weighted least squares) through the
    individual times; O-C residuals and a chi^2 test for timing variations.

Limb darkening is *assumed*, not fitted: quadratic u1 = 0.40, u2 = 0.26, a
representative Kepler-band value for a Sun-like dwarf. Fitting LD
coefficients from a single-band light curve is degenerate with k and b at
typical Kepler SNR. The engine records this assumption; it mainly affects k
at the few-percent level.

TIME UNITS: the uploaded `time` column is treated as days (the Kepler/TESS
convention, and the convention the BLS search already uses). No BJD offset
is added or removed.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np
from scipy import optimize, stats

from app.characterization.transit_model import central_depth, t14_t23, transit_flux

G_CGS = 6.67430e-8        # cm^3 g^-1 s^-2
DAY_S = 86400.0


def stellar_density_from_geometry(period_days: float, a_rs: float) -> float:
    """rho* (g/cm^3) = 3 pi (a/R*)^3 / (G P^2), circular orbit, Mp << M*."""
    return 3.0 * math.pi * a_rs ** 3 / (G_CGS * (period_days * DAY_S) ** 2)

logger = logging.getLogger("ml_service")

# The impact parameter is fitted as b^2: the light curve depends on b only
# through b^2 (cos^2 i), so d(flux)/db vanishes at b = 0 and a linearised
# covariance in b would be meaningless there; in b^2 it is well behaved.
PARAM_NAMES = ("t0", "period", "k", "a_rs", "b2")

FIT_FITTED = "fitted"
FIT_FAILED = "failed"
FIT_NO_TRANSIT = "no_transit"


@dataclass
class FitConfig:
    u1: float = 0.40
    u2: float = 0.26
    window_half_width_durations: float = 1.5
    oot_inner_durations: float = 0.75
    max_points: int = 20000
    max_nfev: int = 300
    min_points_in_transit: int = 5        # across all transits, for the global fit
    min_points_per_transit: int = 2       # for a transit window to be included at all
    long_cadence_threshold_days: float = 0.005   # ~7 min: above this, integrate over the exposure
    supersample: int = 5
    impact_starts: tuple[float, ...] = (0.1, 0.5, 0.85)


@dataclass
class TransitTime:
    epoch: int
    time: float
    error: float
    n_points: int
    o_minus_c: float | None = None
    o_minus_c_error: float | None = None


@dataclass
class TransitFitResult:
    status: str
    message: str
    params: dict[str, float] = field(default_factory=dict)
    errors: dict[str, float] = field(default_factory=dict)
    covariance: list[list[float]] | None = None
    fitted_names: list[str] = field(default_factory=list)
    period_constrained: bool = False
    depth: float | None = None              # model depth at mid-transit (fraction)
    t14_days: float | None = None
    t23_days: float | None = None
    snr: float | None = None
    n_points: int = 0
    n_in_transit: int = 0
    n_transits_with_data: int = 0
    epochs_with_data: list[int] = field(default_factory=list)
    chi2: float | None = None
    dof: int | None = None
    reduced_chi2: float | None = None
    beta_red_noise: float | None = None
    noise_per_point_ppm: float | None = None
    residual_rms_ppm: float | None = None
    converged: bool = False
    n_function_evals: int = 0
    params_at_bounds: list[str] = field(default_factory=list)
    limb_darkening: dict = field(default_factory=dict)
    exposure_days: float = 0.0
    supersample: int = 1
    decimated: bool = False
    bls: dict = field(default_factory=dict)
    transit_times: list[TransitTime] = field(default_factory=list)
    ephemeris: dict | None = None
    timing_assessment: str = ""
    seed_source: str = "bls"                # "bls" | "catalog_ephemeris"
    warnings: list[str] = field(default_factory=list)
    folded: dict | None = None              # binned phase-folded data + fitted model, for display only
    # Catalogue stellar-density prior on a/R* (value, sigma in g/cm^3), when one was applied.
    stellar_density_prior: dict | None = None
    # The same fit without the prior: kept so the transit-derived stellar
    # density can still be compared independently with the catalogue.
    unconstrained: dict | None = None
    # Profile likelihood of rho* when no prior was applied (this fit is then itself prior-free).
    density_profile: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _robust_sigma(x: np.ndarray) -> float:
    if x.size < 3:
        return float("nan")
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def _prepare_windows(time, flux, period, t0, duration, cfg: FitConfig):
    """Selects and locally detrends the data around every predicted transit.
    Returns (t, f, epoch_index, oot_mask) for the concatenated windows."""
    cadence = float(np.median(np.diff(time)))
    # At least ~8 baseline points per side, so the local line is not overfit.
    half = max(cfg.window_half_width_durations * duration, cfg.oot_inner_durations * duration + 8 * cadence)
    oot_inner = cfg.oot_inner_durations * duration
    n_lo = int(math.ceil((time[0] - t0 - half) / period))
    n_hi = int(math.floor((time[-1] - t0 + half) / period))
    ts, fs, es, oots = [], [], [], []
    for n in range(n_lo, n_hi + 1):
        tc = t0 + n * period
        lo, hi = np.searchsorted(time, [tc - half, tc + half])
        if hi - lo < 3:
            continue
        tw, fw = time[lo:hi], flux[lo:hi]
        dt = tw - tc
        oot = np.abs(dt) > oot_inner
        if oot.sum() >= 3 and (dt[oot] < 0).any() and (dt[oot] > 0).any():
            coeff = np.polyfit(dt[oot], fw[oot], 1)
            baseline = np.polyval(coeff, dt)
        elif oot.sum() >= 2:
            baseline = np.full_like(fw, np.median(fw[oot]))
        else:
            continue  # no out-of-transit reference in this window: cannot normalise it honestly
        ts.append(tw)
        fs.append(fw / baseline)
        es.append(np.full(tw.size, n))
        oots.append(oot)
    if not ts:
        return None
    return np.concatenate(ts), np.concatenate(fs), np.concatenate(es), np.concatenate(oots)


def _folded_curve(t, f, t0, p, k, a_rs, b, cfg: FitConfig, exposure, ss, t14) -> dict | None:
    """Phase-folded, binned view of the detrended transit windows and the
    fitted model, for plotting only (never fed back into any calculation).
    Bins are T14/12 wide (folding many transits samples phase more finely
    than one cadence); bins with fewer than three points are dropped rather
    than plotted from too little data. Flux is
    reported in ppm relative to the out-of-transit baseline."""
    dt_h = (((t - t0 + 0.5 * p) % p) - 0.5 * p) * 24.0
    span = float(np.max(np.abs(dt_h))) if dt_h.size else 0.0
    if span <= 0:
        return None
    width = max((t14 or 0.0) * 24.0 / 12.0, span / 150.0)
    edges = np.arange(-span, span + width, width)
    idx = np.digitize(dt_h, edges) - 1
    centers, means, errs, counts = [], [], [], []
    for i in range(edges.size - 1):
        sel = idx == i
        n = int(sel.sum())
        if n < 3:
            continue
        vals = (f[sel] - 1.0) * 1e6
        centers.append(round(float(0.5 * (edges[i] + edges[i + 1])), 4))
        means.append(round(float(np.mean(vals)), 2))
        errs.append(round(float(np.std(vals, ddof=1) / math.sqrt(n)), 2))
        counts.append(n)
    if len(centers) < 5:
        return None
    grid_h = np.linspace(-span, span, 241)
    model = transit_flux(t0 + grid_h / 24.0, t0, p, k, a_rs, b, cfg.u1, cfg.u2, exposure, ss)
    return {
        "phase_hours": centers, "flux_ppm": means, "flux_err_ppm": errs, "n_per_bin": counts,
        "model_phase_hours": [round(float(x), 4) for x in grid_h],
        "model_flux_ppm": [round(float((m - 1.0) * 1e6), 2) for m in model],
        "bin_width_hours": round(width, 4), "n_points": int(t.size),
        "note": "Detrended transit windows folded on the fitted ephemeris and binned; the model is the "
                "best-fit limb-darkened transit. For display only.",
    }


def _beta_red_noise(t: np.ndarray, resid: np.ndarray, epochs: np.ndarray, cadence: float, t14: float) -> float:
    """Time-averaging red-noise factor. Residuals are binned within each
    transit window on timescales from T14/4 to T14 (the timescales that set
    the depth and timing precision); beta is
    the median ratio of the measured binned scatter to the white-noise
    expectation sigma_1/sqrt(N) * sqrt(M/(M-1)). Floored at 1."""
    sigma1 = float(np.std(resid))
    if sigma1 == 0 or cadence <= 0:
        return 1.0
    ratios = []
    for n_bin in sorted({max(2, int(round(s / cadence))) for s in (t14 / 4, t14 / 2, t14)}):
        binned = []
        for e in np.unique(epochs):
            r = resid[epochs == e]
            m = r.size // n_bin
            if m >= 1:
                binned.extend(r[: m * n_bin].reshape(m, n_bin).mean(axis=1))
        m_total = len(binned)
        if m_total < 4:
            continue
        expected = sigma1 / math.sqrt(n_bin) * math.sqrt(m_total / (m_total - 1))
        ratios.append(float(np.std(binned)) / expected)
    return max(1.0, float(np.median(ratios))) if ratios else 1.0


def fit_transit(time: np.ndarray, flux: np.ndarray, bls_period: float, bls_epoch: float,
                bls_duration_days: float, bls_depth: float, bls_snr: float | None = None,
                cfg: FitConfig | None = None, rho_prior: dict | None = None,
                diagnostics: bool = True) -> TransitFitResult:
    """`rho_prior` ({"value", "sigma"} in g/cm^3, e.g. from catalogue log g
    and R*) adds a Gaussian prior on ln(rho*) through a/R* and P. This is the
    standard way to break the b - a/R* degeneracy of a single-band light
    curve (Seager & Mallen-Ornelas 2003); it assumes a circular orbit."""
    cfg = cfg or FitConfig()
    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float) / np.median(flux)
    ld = {"u1": cfg.u1, "u2": cfg.u2, "law": "quadratic", "provenance": "assumed",
          "note": "Representative Kepler-band coefficients for a Sun-like dwarf; not fitted."}
    bls_info = {"period_days": bls_period, "epoch": bls_epoch, "duration_hours": bls_duration_days * 24.0,
                "depth_ppm": bls_depth * 1e6, "snr": bls_snr}

    if not (math.isfinite(bls_depth) and bls_depth > 0 and bls_period > 0 and bls_duration_days > 0):
        return TransitFitResult(FIT_NO_TRANSIT, "The transit search found no positive transit depth to fit.",
                                limb_darkening=ld, bls=bls_info)

    prepared = _prepare_windows(time, flux, bls_period, bls_epoch, bls_duration_days, cfg)
    if prepared is None:
        return TransitFitResult(FIT_FAILED, "No transit window has both in-transit and out-of-transit data.",
                                limb_darkening=ld, bls=bls_info)
    t, f, epochs, oot = prepared

    in_core = np.abs(((t - bls_epoch + 0.5 * bls_period) % bls_period) - 0.5 * bls_period) < 0.5 * bls_duration_days
    covered = sorted(int(e) for e in np.unique(epochs) if (in_core & (epochs == e)).sum() >= cfg.min_points_per_transit)
    n_core = int((in_core & np.isin(epochs, covered)).sum())
    if not covered or n_core < cfg.min_points_in_transit:
        return TransitFitResult(FIT_FAILED, f"Only {n_core} in-transit points are available; at least "
                                f"{cfg.min_points_in_transit} are needed to fit a transit model.",
                                limb_darkening=ld, bls=bls_info)
    keep = np.isin(epochs, covered)
    t, f, epochs, oot = t[keep], f[keep], epochs[keep], oot[keep]
    t_plot, f_plot = t, f  # undecimated, for the folded display curve

    decimated = False
    if t.size > cfg.max_points:
        step = int(math.ceil(t.size / cfg.max_points))
        t, f, epochs, oot = t[::step], f[::step], epochs[::step], oot[::step]
        decimated = True

    # Per-point white noise from the whole light curve's point-to-point
    # differences (robust to slow trends, and independent of the local
    # detrending, which would otherwise absorb part of the scatter).
    phase_all = np.abs(((time - bls_epoch + 0.5 * bls_period) % bls_period) - 0.5 * bls_period)
    out_all = flux[phase_all > cfg.oot_inner_durations * bls_duration_days]
    sigma1 = _robust_sigma(np.diff(out_all)) / math.sqrt(2.0) if out_all.size > 10 else float("nan")
    if not math.isfinite(sigma1) or sigma1 <= 0:
        return TransitFitResult(FIT_FAILED, "Out-of-transit scatter could not be measured.",
                                limb_darkening=ld, bls=bls_info, n_transits_with_data=len(covered))

    cadence = float(np.median(np.diff(np.sort(time))))
    exposure, ss = (cadence, cfg.supersample) if cadence > cfg.long_cadence_threshold_days else (0.0, 1)

    period_constrained = len(covered) >= 2
    n_ref = int(np.median(covered))
    t0_seed = bls_epoch + n_ref * bls_period
    k_seed = math.sqrt(bls_depth)
    t_span = (max(covered) - min(covered)) or 1
    dp = max(0.002 * bls_period, 0.5 * bls_duration_days / t_span)

    def unpack(x):
        if period_constrained:
            return x[0], x[1], x[2], x[3], math.sqrt(max(x[4], 0.0))
        return x[0], bls_period, x[1], x[2], math.sqrt(max(x[3], 0.0))

    use_prior = bool(rho_prior and rho_prior.get("value", 0) > 0 and rho_prior.get("sigma", 0) > 0)
    if use_prior:
        ln_rho0 = math.log(rho_prior["value"])
        sigma_ln = rho_prior["sigma"] / rho_prior["value"]

    def residuals(x):
        t0, p, k, a_rs, b = unpack(x)
        r = (f - transit_flux(t, t0, p, k, a_rs, b, cfg.u1, cfg.u2, exposure, ss)) / sigma1
        if use_prior:
            prior = (math.log(stellar_density_from_geometry(p, a_rs)) - ln_rho0) / sigma_ln
            return np.append(r, prior)
        return r

    names = list(PARAM_NAMES) if period_constrained else ["t0", "k", "a_rs", "b2"]
    best = None
    for b0 in cfg.impact_starts:
        sin_arg = math.sin(math.pi * min(bls_duration_days / bls_period, 0.49))
        if use_prior:  # start a/R* where the stellar density puts it
            a0 = float(np.clip((rho_prior["value"] * G_CGS * (bls_period * DAY_S) ** 2 / (3 * math.pi)) ** (1 / 3),
                               1.5, 500.0))
        else:
            a0 = float(np.clip(math.sqrt(max((1 + k_seed) ** 2 - b0 ** 2, 1e-4)) / sin_arg, 1.5, 500.0))
        x0 = [t0_seed, bls_period, k_seed, a0, b0 ** 2] if period_constrained else [t0_seed, k_seed, a0, b0 ** 2]
        lo = [t0_seed - 0.5 * bls_duration_days, bls_period - dp, 1e-4, 1.01, 0.0]
        hi = [t0_seed + 0.5 * bls_duration_days, bls_period + dp, 0.5, 2000.0, 2.25]
        if not period_constrained:
            lo, hi = [lo[0]] + lo[2:], [hi[0]] + hi[2:]
        x0 = np.clip(x0, np.array(lo) + 1e-12, np.array(hi) - 1e-12)
        try:
            res = optimize.least_squares(residuals, x0, bounds=(lo, hi), x_scale="jac", max_nfev=cfg.max_nfev)
        except Exception as exc:  # noqa: BLE001
            logger.warning("transit_fit_start_failed", extra={"b0": b0, "error": str(exc)})
            continue
        if best is None or res.cost < best[0].cost:
            best = (res, lo, hi)
    if best is None:
        return TransitFitResult(FIT_FAILED, "The transit-model optimisation failed from every starting point.",
                                limb_darkening=ld, bls=bls_info, n_transits_with_data=len(covered))
    res, lo, hi = best
    t0, p, k, a_rs, b = unpack(res.x)

    data_fun = res.fun[:-1] if use_prior else res.fun   # the prior term is not a data residual
    resid = data_fun * sigma1
    n_free = len(names)
    dof = max(t.size - n_free, 1)
    chi2 = float(np.sum(data_fun ** 2))
    red_chi2 = chi2 / dof
    t14, t23 = t14_t23(p, k, a_rs, b)
    beta = _beta_red_noise(t, resid, epochs, cadence, t14 or bls_duration_days)

    warnings: list[str] = []
    at_bounds = [n for n, v, l, h in zip(names, res.x, lo, hi) if n != "b2" and (math.isclose(v, l, rel_tol=1e-6, abs_tol=1e-9) or math.isclose(v, h, rel_tol=1e-6, abs_tol=1e-9))]
    if at_bounds:
        warnings.append(f"Fit parameter(s) at a search bound: {', '.join(at_bounds)}; their uncertainties are unreliable.")

    cov = None
    errors: dict[str, float] = {}
    try:
        jtj = res.jac.T @ res.jac
        if np.linalg.cond(jtj) < 1e14:
            cov_arr = np.linalg.inv(jtj) * max(1.0, red_chi2) * beta ** 2
            if np.all(np.diag(cov_arr) > 0):
                cov = cov_arr.tolist()
                errors = {n: float(math.sqrt(cov_arr[i, i])) for i, n in enumerate(names)}
    except np.linalg.LinAlgError:
        pass
    if cov is None:
        warnings.append("The fit's parameter covariance is singular (parameters degenerate at this SNR); "
                        "fitted values are reported without statistical uncertainties.")

    model = transit_flux(t, t0, p, k, a_rs, b, cfg.u1, cfg.u2, exposure, ss)
    in_transit = model < 1.0
    depth = central_depth(k, b, cfg.u1, cfg.u2)
    n_in = int(in_transit.sum())
    snr = depth / (sigma1 * beta) * math.sqrt(n_in) if n_in > 0 else None

    result = TransitFitResult(
        status=FIT_FITTED,
        message="Limb-darkened transit model fitted." if res.success else f"Optimiser stopped early: {res.message}",
        params={"t0": float(t0), "period": float(p), "k": float(k), "a_rs": float(a_rs), "b2": float(b * b), "b": float(b)},
        errors=errors, covariance=cov, fitted_names=names, period_constrained=period_constrained,
        depth=depth, t14_days=t14, t23_days=t23, snr=snr,
        n_points=int(t.size), n_in_transit=n_in, n_transits_with_data=len(covered), epochs_with_data=covered,
        chi2=chi2, dof=dof, reduced_chi2=red_chi2, beta_red_noise=beta,
        noise_per_point_ppm=sigma1 * 1e6, residual_rms_ppm=float(np.std(resid)) * 1e6,
        converged=bool(res.success), n_function_evals=int(res.nfev), params_at_bounds=at_bounds,
        limb_darkening=ld, exposure_days=exposure, supersample=ss, decimated=decimated, bls=bls_info,
        warnings=warnings,
        folded=_folded_curve(t_plot, f_plot, t0, p, k, a_rs, b, cfg, exposure, ss, t14) if diagnostics else None,
        stellar_density_prior=dict(rho_prior) if use_prior else None,
    )
    if decimated:
        warnings.append(f"More than {cfg.max_points} points fell in transit windows; every "
                        f"{int(math.ceil(prepared[0].size / cfg.max_points))}th point was used for fitting.")
    if not res.success:
        warnings.append(f"The optimiser stopped before formal convergence ({res.message}); treat the fit with caution.")
    if not period_constrained:
        warnings.append("Only one transit has data: the orbital period is not constrained by this light curve "
                        "and was held at the transit-search value.")

    if diagnostics:
        _fit_transit_times(result, t, f, epochs, sigma1, cfg, exposure, ss)
    return result


# Stellar-density grid for the profile likelihood: 0.01-100 g/cm^3 spans
# every main-sequence star, giant and subgiant (the Sun is 1.41). The coarse
# grid (a factor of ~1.8 per step) is refined around the minimum.
PROFILE_LN_RHO = np.linspace(math.log(0.01), math.log(100.0), 17)
PROFILE_LN_TOL = 0.03          # locate the minimum and the 68% limits to ~3% in rho*
PROFILE_MAX_POINTS = 2000      # per profile fit; Delta chi^2 is rescaled by the decimation factor
PROFILE_MAX_ITER = 8


def stellar_density_profile(time, flux, free: TransitFitResult, cfg: FitConfig | None = None) -> dict | None:
    """What the light curve alone says about the stellar density: the
    prior-free fit's chi^2 profile over fixed rho* (each point refitted with
    a/R* pinned by rho* and P, all other parameters free).

    Used instead of the fit covariance because b and a/R* are strongly and
    non-linearly degenerate at typical SNR/cadence, where a linearised
    covariance is meaningless (it gave sigma(a/R*) > a/R* for Kepler-227 b).
    Delta chi^2 is scaled by the same max(1, reduced chi^2) * beta^2 factor
    that inflates the fit covariance; the 68% interval is Delta chi^2 <= 1.
    An interval reaching the grid edge is reported as unbounded on that side:
    the light curve then does not constrain rho* there."""
    if free.status != FIT_FITTED:
        return None
    cfg = cfg or FitConfig()
    p = free.params
    k = p["k"]
    t14 = free.t14_days or free.bls.get("duration_hours", 0) / 24.0
    depth = free.depth or k ** 2

    def chi2_at(ln_rho: float) -> float:
        rho = math.exp(ln_rho)
        # With a/R* pinned, b follows from the duration: seed a single start there.
        a_rs = (rho * G_CGS * (p["period"] * DAY_S) ** 2 / (3 * math.pi)) ** (1 / 3)
        b2 = (1 + k) ** 2 - (a_rs * math.sin(math.pi * min(t14 / p["period"], 0.49))) ** 2
        start = float(np.clip(math.sqrt(max(b2, 0.0)), 0.0, 1.2))
        # Two starts -- b from the duration, and the free fit's b -- so a pinned
        # fit does not stop in a poorer local minimum (that would inflate
        # Delta chi^2 and make the interval look more precise than it is).
        starts = tuple(sorted({round(start, 3), round(float(np.clip(p["b"], 0.0, 1.2)), 3)}))
        r = fit_transit(time, flux, p["period"], p["t0"], t14, depth, None,
                        replace(cfg, impact_starts=starts, max_points=PROFILE_MAX_POINTS),
                        rho_prior={"value": rho, "sigma": 1e-3 * rho}, diagnostics=False)
        if r.status != FIT_FITTED or r.chi2 is None or not r.n_points:
            return float("nan")
        # With decimation every k-th point is fitted; for white noise the full
        # data's chi^2 differences are k times larger.
        return r.chi2 * (free.n_points / r.n_points)

    grid = {float(x): chi2_at(x) for x in PROFILE_LN_RHO}
    if sum(math.isfinite(c) for c in grid.values()) < 5:
        return None
    scale = max(1.0, free.reduced_chi2 or 1.0) * (free.beta_red_noise or 1.0) ** 2

    def state():
        xs = np.array(sorted(grid))
        c = np.array([grid[x] for x in xs])
        d = (c - np.nanmin(c)) / scale
        return xs, d, int(np.nanargmin(d))

    def bracket(xs, d, i_best, direction):
        """(inside, outside) grid indices around the Delta chi^2 = 1 crossing."""
        prev = i_best
        i = i_best + direction
        while 0 <= i < len(xs):
            if np.isfinite(d[i]):
                if d[i] > 1.0:
                    return prev, i
                prev = i
            i += direction
        return None

    # Adaptive refinement: bisect around the minimum and both Delta chi^2 = 1
    # crossings until they are located to PROFILE_LN_TOL. The profile can be
    # strongly one-sided (e.g. a wall where the duration would need b^2 < 0),
    # so no parabolic shape is assumed.
    for _ in range(PROFILE_MAX_ITER):
        xs, d, i_best = state()
        todo = set()
        for j in (i_best - 1, i_best + 1):
            if 0 <= j < len(xs) and abs(xs[j] - xs[i_best]) > PROFILE_LN_TOL:
                todo.add(0.5 * (xs[j] + xs[i_best]))
        for direction in (-1, 1):
            br = bracket(xs, d, i_best, direction)
            if br and abs(xs[br[1]] - xs[br[0]]) > PROFILE_LN_TOL:
                todo.add(0.5 * (xs[br[0]] + xs[br[1]]))
        todo = {float(x) for x in todo if float(x) not in grid}
        if not todo:
            break
        for x in todo:
            grid[x] = chi2_at(x)

    xs, dchi2, i_best = state()

    def crossing(direction):
        br = bracket(xs, dchi2, i_best, direction)
        if br is None:
            return None
        (x0, y0), (x1, y1) = (xs[br[0]], dchi2[br[0]]), (xs[br[1]], dchi2[br[1]])
        return float(math.exp(x0 + (1.0 - y0) * (x1 - x0) / (y1 - y0)))

    best = float(math.exp(xs[i_best]))
    lo, hi = crossing(-1), crossing(1)
    return {
        "best": best, "lower_68": lo, "upper_68": hi,
        "bounded": lo is not None and hi is not None,
        "grid_rho": [round(float(math.exp(x)), 5) for x in xs],
        "delta_chi2": [None if not np.isfinite(v) else round(float(v), 3) for v in dchi2],
        "method": "Profile likelihood of the prior-free transit fit over fixed stellar densities "
                  "(Delta chi^2 <= 1, scaled by max(1, reduced chi^2) x beta^2).",
    }


def _fit_transit_times(result: TransitFitResult, t, f, epochs, sigma1, cfg: FitConfig, exposure, ss) -> None:
    """Per-transit mid-times with the transit shape fixed, then a weighted
    linear ephemeris and O-C residuals."""
    p = result.params
    t14 = result.t14_days
    # Epochs are counted from the global fit's reference transit, so the
    # ephemeris T0 below and the fitted t0 refer to the same event.
    n_ref = int(round((p["t0"] - result.bls["epoch"]) / result.bls["period_days"]))
    if t14 is None:
        result.timing_assessment = "Transit timing unavailable: the fitted geometry has no defined duration."
        return
    times: list[TransitTime] = []
    for n in result.epochs_with_data:
        sel = epochs == n
        tn, fn = t[sel], f[sel]
        tc_pred = p["t0"] + (n - n_ref) * p["period"]
        dt = tn - tc_pred
        in_tr = np.abs(dt) < 0.5 * t14
        # Timing needs the transit's edges: at least one point on each side
        # of mid-transit, plus out-of-transit baseline.
        if in_tr.sum() < cfg.min_points_in_transit or not ((dt[in_tr] < 0).any() and (dt[in_tr] > 0).any()):
            continue

        def resid(x):
            return (fn - transit_flux(tn, x[0], p["period"], p["k"], p["a_rs"], p["b"],
                                      cfg.u1, cfg.u2, exposure, ss)) / sigma1
        try:
            r = optimize.least_squares(resid, [tc_pred], bounds=([tc_pred - 0.5 * t14], [tc_pred + 0.5 * t14]),
                                       x_scale="jac", max_nfev=100)
        except Exception:  # noqa: BLE001
            continue
        jtj = float((r.jac.T @ r.jac).item())
        if jtj <= 0:
            continue
        red = float(np.sum(r.fun ** 2)) / max(tn.size - 1, 1)
        err = math.sqrt(1.0 / jtj * max(1.0, red)) * (result.beta_red_noise or 1.0)
        if err > 0.25 * t14:
            continue  # this transit does not constrain its own time
        times.append(TransitTime(epoch=int(n - n_ref), time=float(r.x[0]), error=err, n_points=int(tn.size)))

    result.transit_times = times
    if len(times) < 2:
        result.timing_assessment = (
            f"{len(times)} individually timed transit(s); at least 2 are needed for an ephemeris and 3 for a "
            "transit-timing-variation test."
        )
        return

    n_arr = np.array([tt.epoch for tt in times], dtype=float)
    t_arr = np.array([tt.time for tt in times])
    w = 1.0 / np.array([tt.error for tt in times]) ** 2
    a = np.vstack([np.ones_like(n_arr), n_arr]).T
    cov = np.linalg.inv(a.T @ (a * w[:, None]))
    t0_lin, p_lin = cov @ (a.T @ (w * t_arr))
    oc = t_arr - (t0_lin + p_lin * n_arr)
    for tt, o in zip(times, oc):
        tt.o_minus_c = float(o)
        tt.o_minus_c_error = tt.error
    chi2 = float(np.sum(oc ** 2 * w))
    dof = len(times) - 2
    p_value = float(stats.chi2.sf(chi2, dof)) if dof > 0 else None
    result.ephemeris = {
        "t0": float(t0_lin), "t0_error": float(math.sqrt(cov[0, 0])),
        "period": float(p_lin), "period_error": float(math.sqrt(cov[1, 1])),
        "covariance": cov.tolist(), "n_transits": len(times), "chi2": chi2, "dof": dof, "p_value": p_value,
        "oc_rms_minutes": float(np.sqrt(np.mean(oc ** 2)) * 1440.0),
    }
    if dof <= 0:
        result.timing_assessment = "Two timed transits define the linear ephemeris; a third is needed to test for timing variations."
    elif p_value is not None and p_value < 1e-3:
        result.timing_assessment = (
            f"Transit times deviate from a linear ephemeris (chi^2 = {chi2:.1f} for {dof} dof, p = {p_value:.1e}). "
            "This can indicate transit timing variations, but also unmodelled systematics, starspot crossings or "
            "underestimated timing errors -- it is not a TTV detection without dedicated analysis."
        )
    else:
        result.timing_assessment = (
            f"Transit times are consistent with a linear ephemeris (chi^2 = {chi2:.1f} for {dof} dof"
            + (f", p = {p_value:.2f}" if p_value is not None else "") + "); no significant timing variations."
        )
