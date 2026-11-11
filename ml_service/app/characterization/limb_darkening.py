"""
Kepler-band quadratic limb-darkening coefficients for the host star.

Read from data/limb_darkening_kepler_atlas9.csv, which is computed OFFLINE
with ExoCTK on the ATLAS9 model-atmosphere grid
(scripts/build_limb_darkening_table.py); ExoCTK itself is not a runtime
dependency. The table holds (u1, u2) at every grid node (Teff 3500-8750 K in
250 K steps, log g 3.0-5.0 in 0.5 dex steps, [Fe/H] -0.5/0/+0.5) for the law
I(mu)/I(1) = 1 - u1 (1 - mu) - u2 (1 - mu)^2 -- the same law as
transit_model.py.

Coefficients are trilinearly interpolated in (Teff, log g, [Fe/H]). Outside
the grid, or when Teff / log g are unknown, `kepler_quadratic` returns None
and the caller keeps the fixed default; values are never extrapolated.
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache

import numpy as np

from app.config import get_settings

SOURCE = "ExoCTK (ATLAS9 model atmospheres), Kepler band"


@lru_cache(maxsize=1)
def _table() -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray], np.ndarray, np.ndarray]:
    with open(get_settings().limb_darkening_table_path, newline="") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    axes = tuple(np.array(sorted({float(r[k]) for r in rows})) for k in ("teff", "logg", "feh"))
    shape = tuple(a.size for a in axes)
    u1, u2 = np.full(shape, np.nan), np.full(shape, np.nan)
    for r in rows:
        i = tuple(int(np.searchsorted(a, float(r[k]))) for a, k in zip(axes, ("teff", "logg", "feh")))
        u1[i], u2[i] = float(r["u1"]), float(r["u2"])
    if np.isnan(u1).any():
        raise ValueError("The limb-darkening table does not cover a full (Teff, log g, [Fe/H]) grid.")
    return axes, u1, u2


def _bracket(axis: np.ndarray, x: float) -> tuple[int, float] | None:
    """Index of the lower grid node and the fractional distance to the next,
    or None outside the axis."""
    if not (axis[0] <= x <= axis[-1]):
        return None
    i = min(int(np.searchsorted(axis, x, side="right")) - 1, axis.size - 2)
    return i, (x - axis[i]) / (axis[i + 1] - axis[i])


def kepler_quadratic(teff: float | None, logg: float | None, feh: float = 0.0) -> dict | None:
    """Interpolated Kepler-band (u1, u2) for the star, or None when Teff or
    log g is unknown or outside the table."""
    if teff is None or logg is None or not all(math.isfinite(v) for v in (teff, logg, feh)):
        return None
    axes, u1, u2 = _table()
    brackets = [_bracket(a, x) for a, x in zip(axes, (teff, logg, feh))]
    if any(b is None for b in brackets):
        return None
    (it, ft), (ig, fg), (iff, ff) = brackets
    w1 = w2 = 0.0
    for dt, wt in ((0, 1 - ft), (1, ft)):
        for dg, wg in ((0, 1 - fg), (1, fg)):
            for df, wf in ((0, 1 - ff), (1, ff)):
                w = wt * wg * wf
                w1 += w * u1[it + dt, ig + dg, iff + df]
                w2 += w * u2[it + dt, ig + dg, iff + df]
    return {"u1": round(float(w1), 4), "u2": round(float(w2), 4), "teff": float(teff), "logg": float(logg),
            "feh": float(feh)}
