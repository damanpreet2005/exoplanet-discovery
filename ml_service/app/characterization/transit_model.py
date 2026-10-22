"""
Limb-darkened transit light-curve model (circular orbit).

Why not batman / exoplanet: batman needs a C toolchain at install time and
exoplanet pulls in PyMC/PyTensor -- both heavy additions to a slim
FastAPI image whose only scientific dependencies are numpy, scipy (already
present as a scikit-learn requirement) and astropy. The model below is
small, vectorised, and verified in tests against the exact analytic
uniform-disk overlap area (Mandel & Agol 2002, eq. 1).

METHOD
The fraction of stellar flux blocked by an opaque planet disk of radius
k = Rp/Rstar whose centre sits at sky-projected separation z (both in
units of Rstar) is

    blocked(z) = [ integral_0^1 I(r) * 2 r * theta(r; z, k) dr ] / [ pi * (1 - u1/3 - u2/6) ]

where theta(r) is the half-angle of the stellar annulus at radius r that
lies behind the planet (theta = pi for an annulus fully covered), and
I(r) is the quadratic limb-darkening law

    I(mu) / I(1) = 1 - u1 (1 - mu) - u2 (1 - mu)^2,   mu = sqrt(1 - r^2).

The radial integral is only taken over the annuli the planet can touch,
r in [max(0, z - k), min(1, z + k)], with a cosine-clustered midpoint rule
so resolution scales with the planet size (an Earth-size k ~ 0.01 is
resolved as finely as a Jupiter) and the square-root behaviour of theta at
the integration limits is absorbed by the node clustering.

ORBIT
Circular orbit only. Photometry alone does not constrain eccentricity, so
the fitted a/Rstar and impact parameter are "circular-equivalent" values;
the characterization engine records this assumption on every dependent
output (see engine.py).

    phi = 2 pi (t - t0) / P
    z   = (a/Rstar) * sqrt( sin^2 phi + cos^2 i * cos^2 phi ),  cos i = b / (a/Rstar)

and the planet only occults the star while it is on the near side
(cos phi > 0).

FINITE EXPOSURES
Long-cadence data (Kepler: 29.4 min) smear ingress/egress. `supersample`
evaluates the model at evenly spaced sub-exposure times and averages them
(Kipping 2010).
"""
from __future__ import annotations

import math

import numpy as np

# Cosine-clustered midpoint nodes on [0, 1] for the radial integral. 48
# nodes keep the uniform-disk error below 1e-4 of k^2 for k in [0.005, 0.3]
# (see tests/test_transit_model_fit.py).
_N_NODES = 48
_U = (np.arange(_N_NODES) + 0.5) / _N_NODES
_X = 0.5 * (1.0 - np.cos(np.pi * _U))                  # node positions in [0, 1]
_W = 0.5 * np.pi * np.sin(np.pi * _U) / _N_NODES       # dx/du * du
# Gauss-Legendre nodes on [0, 1] for the smooth, fully covered inner disk.
_GL_X, _GL_W = np.polynomial.legendre.leggauss(16)
_GL_X, _GL_W = 0.5 * (_GL_X + 1.0), 0.5 * _GL_W


def uniform_disk_blocked_fraction(z: np.ndarray, k: float) -> np.ndarray:
    """Exact fractional flux blocked for a uniform (non-limb-darkened) star:
    the circle-circle overlap area divided by pi (Mandel & Agol 2002, eq. 1).
    Used as the analytic reference the numerical integrator is tested
    against, and as a building block for nothing else."""
    z = np.abs(np.asarray(z, dtype=float))
    out = np.zeros_like(z)
    full = z <= 1.0 - k
    out[full] = k * k
    partial = (z > abs(1.0 - k)) & (z < 1.0 + k)
    zp = z[partial]
    kap0 = np.arccos(np.clip((k * k + zp * zp - 1.0) / (2.0 * k * zp), -1.0, 1.0))
    kap1 = np.arccos(np.clip((1.0 - k * k + zp * zp) / (2.0 * zp), -1.0, 1.0))
    root = np.sqrt(np.clip(4.0 * zp * zp - (1.0 + zp * zp - k * k) ** 2, 0.0, None))
    out[partial] = (k * k * kap0 + kap1 - 0.5 * root) / math.pi
    if k > 1.0:
        out[z <= k - 1.0] = 1.0
    return out


def blocked_fraction(z: np.ndarray, k, u1: float, u2: float) -> np.ndarray:
    """Fraction of total stellar flux blocked at separations `z` (Rstar
    units) by a planet of radius ratio `k` (scalar, or an array matching
    `z`), quadratic limb darkening (u1, u2). Returns 0 wherever the disks
    don't overlap."""
    z = np.abs(np.asarray(z, dtype=float))
    k_all = np.broadcast_to(np.asarray(k, dtype=float), z.shape)
    out = np.zeros_like(z)
    touching = (z < 1.0 + k_all) & (k_all > 0)
    if not touching.any():
        return out
    zt = z[touching][:, None]
    kt = k_all[touching][:, None]

    def intensity(r):
        one_minus_mu = 1.0 - np.sqrt(np.clip(1.0 - r * r, 0.0, None))
        return 1.0 - u1 * one_minus_mu - u2 * one_minus_mu ** 2

    # Annuli with r < k - z are entirely behind the planet (theta = pi); the
    # partially covered annuli start at |z - k|. Splitting there keeps the
    # square-root kink of theta at an integration limit, where the node
    # clustering resolves it.
    inner = np.clip(np.minimum(kt - zt, 1.0), 0.0, None)
    r_in = inner * _GL_X[None, :]
    blocked = np.sum(intensity(r_in) * 2.0 * math.pi * r_in * inner * _GL_W[None, :], axis=1)

    lo = np.minimum(np.abs(zt - kt), 1.0)
    hi = np.minimum(1.0, zt + kt)
    r = lo + (hi - lo) * _X[None, :]
    w = (hi - lo) * _W[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        c = (r * r + zt * zt - kt * kt) / (2.0 * r * zt)
    theta = np.arccos(np.clip(np.nan_to_num(c, nan=1.0), -1.0, 1.0))
    blocked = blocked + np.sum(intensity(r) * 2.0 * r * theta * w, axis=1)
    norm = math.pi * (1.0 - u1 / 3.0 - u2 / 6.0)
    out[touching] = blocked / norm
    return out


def projected_separation(t: np.ndarray, t0: float, period: float, a_rs: float, b: float) -> tuple[np.ndarray, np.ndarray]:
    """Sky-projected star-planet separation (Rstar units) for a circular
    orbit, and a mask of the times the planet is in front of the star."""
    phi = 2.0 * math.pi * (np.asarray(t, dtype=float) - t0) / period
    cos_i = b / a_rs
    sin_phi, cos_phi = np.sin(phi), np.cos(phi)
    z = a_rs * np.sqrt(sin_phi ** 2 + (cos_i * cos_phi) ** 2)
    return z, cos_phi > 0.0


def transit_flux(t: np.ndarray, t0: float, period: float, k: float, a_rs: float, b: float,
                 u1: float, u2: float, exposure: float = 0.0, supersample: int = 1) -> np.ndarray:
    """Normalised model flux (1 out of transit) at times `t`.
    `exposure` (same units as t) and `supersample` integrate over finite
    exposures; supersample=1 evaluates instantaneous flux."""
    t = np.asarray(t, dtype=float)
    if supersample > 1 and exposure > 0:
        offsets = ((np.arange(supersample) + 0.5) / supersample - 0.5) * exposure
        tt = (t[:, None] + offsets[None, :]).ravel()
        return transit_flux(tt, t0, period, k, a_rs, b, u1, u2).reshape(t.size, supersample).mean(axis=1)
    z, front = projected_separation(t, t0, period, a_rs, b)
    flux = np.ones_like(t)
    sel = front & (z < 1.0 + k)
    if sel.any():
        flux[sel] = 1.0 - blocked_fraction(z[sel], k, u1, u2)
    return flux


def central_depth(k, b, u1: float, u2: float):
    """Fractional depth at mid-transit (z = b) for the given geometry and
    limb darkening -- the "fitted transit depth" the engine reports, which
    differs from k^2 by the limb-darkening and grazing-geometry factors.
    Accepts scalars or equal-length arrays of samples."""
    b_arr = np.atleast_1d(np.asarray(b, dtype=float))
    out = blocked_fraction(b_arr, np.broadcast_to(np.asarray(k, dtype=float), b_arr.shape), u1, u2)
    return float(out[0]) if np.ndim(b) == 0 and np.ndim(k) == 0 else out


def t14_t23(period: float, k: float, a_rs: float, b: float) -> tuple[float | None, float | None]:
    """Total (first-to-fourth contact) and full (second-to-third contact)
    transit durations for a circular orbit (Winn 2010, eqs. 14-15). Returns
    None for T23 when the transit is grazing (b > 1 - k), and None for both
    when the geometry admits no transit."""
    if a_rs <= 1.0 or b < 0:
        return None, None
    cos_i = b / a_rs
    sin_i = math.sqrt(max(1.0 - cos_i ** 2, 0.0))
    if sin_i <= 0:
        return None, None

    def duration(term: float) -> float | None:
        if term <= 0:
            return None
        arg = math.sqrt(term) / (a_rs * sin_i)
        if arg > 1:
            return None
        return period / math.pi * math.asin(arg)

    return duration((1 + k) ** 2 - b ** 2), duration((1 - k) ** 2 - b ** 2)
