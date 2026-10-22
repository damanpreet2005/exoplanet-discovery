"""
Stellar and planetary values the local KOI catalogue snapshot lacks, looked
up in the NASA Exoplanet Archive for the matched Kepler target:

  - metallicity [Fe/H] and distance from the Kepler Q1-Q17 DR25 stellar
    table -- the same catalogue the local KOI table's Teff / log g / R* come
    from, so the stellar parameters stay mutually consistent;
  - for confirmed planets, the Gaia-based system distance and the planet
    mass from the confirmed-planet composite table -- the mass only when the
    Archive marks it as a measurement (pl_bmassprov = "Mass"), never when it
    is itself a mass-radius estimate.

Every value is recorded with its uncertainty and source. Any lookup failure
leaves the value out (the engine then reports it as unavailable with the
reason); nothing is substituted.
"""
from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor

from app.nasa_exoplanet_archive_client import NasaApiError, query_confirmed_planet, query_dr25_stellar

logger = logging.getLogger("ml_service")

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 6 * 3600


def _num(raw) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _record(row: dict, col: str, source: str) -> dict | None:
    value = _num(row.get(col))
    if value is None:
        return None
    ep, em = _num(row.get(f"{col}err1", row.get(f"{col}_err1"))), _num(row.get(f"{col}err2", row.get(f"{col}_err2")))
    # The Archive writes 0 for "no uncertainty recorded"; that is not a zero uncertainty.
    ep = abs(ep) if ep else None
    em = abs(em) if em else None
    return {"value": value, "err_plus": ep, "err_minus": em, "source": source}


# DR25 stellar values must agree with the local catalogue's (both come from
# the same DR25 stellar table) before any DR25-only value is used for the star.
IDENTITY_TOLERANCE = {"radius": ("stellar_radius", 0.02), "logg": ("stellar_logg", 0.02), "teff": ("stellar_teff", 0.01)}
PERIOD_MATCH_TOLERANCE = 0.01
# Archive planet-mass provenance values (pl_bmassprov) that are measurements.
MEASURED_MASS_PROVENANCE = {"Mass", "Msin(i)/sin(i)", "Msini"}


def _identity_conflicts(row: dict, local_stellar: dict | None) -> list[str]:
    conflicts = []
    for col, (name, tol) in IDENTITY_TOLERANCE.items():
        archive_v, local = _num(row.get(col)), (local_stellar or {}).get(name, {}).get("value")
        if archive_v is not None and local:
            if abs(archive_v / local - 1) > tol:
                conflicts.append(f"{col} {archive_v:g} vs local {local:g}")
    return conflicts


def lookup(kepid: int | None, kepler_name: str | None, local_stellar: dict | None = None,
           period_days: float | None = None) -> dict:
    """Returns {"stellar": {...}, "planet": {...}, "notes": [...]} for the
    matched target; empty sections when nothing could be retrieved.

    Identity checks: the DR25 stellar row must be the only row for this KIC
    and agree with the local catalogue's R*, log g and Teff; the confirmed-
    planet row must carry exactly this planet name and, when a period is
    known, a period within 1% of it. Anything else is reported in `notes`
    and not used, so another object's properties can never be attached."""
    key = (kepid, kepler_name, round(period_days, 3) if period_days else None,
           tuple(sorted((k, v.get("value")) for k, v in (local_stellar or {}).items())))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    out: dict = {"stellar": {}, "planet": {}, "notes": []}
    # The two queries are independent: run them concurrently.
    with ThreadPoolExecutor(max_workers=2) as pool:
        dr25_future = pool.submit(_safe, query_dr25_stellar, kepid) if kepid else None
        planet_future = pool.submit(_safe, query_confirmed_planet, kepler_name) if kepler_name else None
        dr25_result = dr25_future.result() if dr25_future else None
        planet_result = planet_future.result() if planet_future else None
    if kepid:
        rows, err = dr25_result
        if err:
            out["notes"].append(f"Kepler DR25 stellar lookup failed: {err}")
        elif len(rows) > 1:
            out["notes"].append(f"The Kepler DR25 stellar table returned {len(rows)} rows for KIC {kepid}; "
                                "the match is ambiguous, so none of its values are used.")
        elif rows:
            row = rows[0]
            conflicts = _identity_conflicts(row, local_stellar)
            if conflicts:
                out["notes"].append("The Kepler DR25 stellar row disagrees with the local catalogue for this "
                                    f"star ({'; '.join(conflicts)}), so its values are not used.")
            else:
                src = "NASA Exoplanet Archive, Kepler Q1-Q17 DR25 stellar table (q1_q17_dr25_ks)"
                if rec := _record(row, "feh", src):
                    out["stellar"]["stellar_metallicity"] = rec
                if rec := _record(row, "dist", src):
                    out["stellar"]["distance"] = rec
                if (rec := _record(row, "mass", src)) and rec["err_plus"] and rec["err_minus"]:
                    model = (row.get("prov_sec") or "").strip()
                    rec["kind"] = "catalogue_derived"
                    rec["method"] = ("Isochrone-model stellar mass from the Kepler DR25 stellar catalogue"
                                     + (f" ({model} stellar models)" if model else "")
                                     + ", fitted to the star's Teff, log g and [Fe/H]; a model-derived "
                                       "catalogue value, not a direct (e.g. binary-orbit) measurement.")
                    out["stellar"]["stellar_mass"] = rec
    if kepler_name:
        rows, err = planet_result
        if err:
            out["notes"].append(f"Confirmed-planet lookup failed: {err}")
        else:
            rows = [r for r in rows if (r.get("pl_name") or "").strip() == kepler_name]
            if len(rows) > 1:
                out["notes"].append(f"The confirmed-planet table returned {len(rows)} rows for {kepler_name}; none used.")
            elif rows:
                row = rows[0]
                p_arch = _num(row.get("pl_orbper"))
                if period_days and p_arch and abs(p_arch / period_days - 1) > PERIOD_MATCH_TOLERANCE:
                    out["notes"].append(f"The confirmed-planet row for {kepler_name} has period {p_arch:g} d, which "
                                        f"does not match this transit's {period_days:g} d; its values are not used.")
                else:
                    src = "NASA Exoplanet Archive, confirmed-planet composite table (pscomppars)"
                    if rec := _record(row, "sy_dist", src + ", Gaia-based system distance"):
                        out["stellar"]["distance"] = rec   # preferred over the DR25 isochrone distance
                    _add_planet_mass(out, row, kepler_name, src)
    logger.info("characterization_archive_lookup", extra={"kepid": kepid, "found": sorted({**out["stellar"], **out["planet"]})})
    if not any("failed" in n for n in out["notes"]):
        _CACHE[key] = (time.monotonic(), out)
    return out


def _safe(query, arg):
    """(rows, None) or ([], error) -- a failed query never raises out of the pool."""
    try:
        return query(arg), None
    except NasaApiError as exc:
        return [], exc


def _add_planet_mass(out: dict, row: dict, kepler_name: str, src: str) -> None:
    prov = (row.get("pl_bmassprov") or "").strip()
    mass = _record(row, "pl_bmasse", src)
    if not mass:
        return
    has_interval = bool(mass["err_plus"] and mass["err_minus"])
    if prov in MEASURED_MASS_PROVENANCE and has_interval:
        mass["kind"] = "measured"
        mass["method"] = {
            "Mass": "Measured planet mass (radial velocities or transit-timing variations) from the NASA "
                    "Exoplanet Archive.",
            "Msin(i)/sin(i)": "Measured planet mass from radial velocities, M sin i corrected by the orbital "
                              "inclination (NASA Exoplanet Archive).",
            "Msini": "Measured minimum mass M sin i from radial velocities (NASA Exoplanet Archive); for a "
                     "transiting planet sin i is close to 1, so it is close to the true mass.",
        }[prov]
        out["planet"]["planet_mass"] = mass
    elif prov and prov not in MEASURED_MASS_PROVENANCE and has_interval:
        mass["kind"] = "catalogue_estimate"
        mass["method"] = (f"NASA Exoplanet Archive mass estimate ({prov}), with its quoted uncertainty; an "
                          "estimate, not a measurement.")
        out["planet"]["planet_mass"] = mass
    else:
        out["notes"].append(f"The Archive lists a planet mass of {mass['value']:g} M⊕ for {kepler_name}, but its "
                            f"provenance is '{prov or 'unspecified'}' (not a measurement) and it has no quoted "
                            "uncertainty, so it is not used; the engine's own mass-radius estimate, which carries "
                            "the relation's scatter, is used instead.")
