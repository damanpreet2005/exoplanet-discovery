"""
Thin HTTP client for the NASA Exoplanet Archive's TAP (Table Access
Protocol) sync service -- the Archive's own supported programmatic
interface (https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html),
no API key required.

This module's only job is "ADQL WHERE clause in, raw JSON rows out (or a
typed error)". It knows nothing about KIC/KOI/Kepler-name identifier
semantics, matching rules, or the 17-feature RF contract -- that logic
stays in app/stellar_catalog_service.py, which is this client's only
caller. Isolating it here means the NASA API's URL/query format is never
duplicated elsewhere in the ML code.

Queries the same `cumulative` KOI table `app/feature_aliases.py`'s
MODEL_FEATURE_ORDER was verified against, requesting only the columns the
RF pipeline actually needs (see FIELDS below) -- never a broad "select *".
"""
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("ml_service")

# Exactly the catalog-only fields app/stellar_catalog_service.py needs to
# populate the RF's 17-feature contract -- see feature_engine.py's mapping
# of koi_score/koi_tce_plnt_num/koi_steff/koi_slogg/koi_srad/ra/dec/koi_kepmag.
FIELDS = (
    "kepid", "kepoi_name", "kepler_name",
    "koi_score", "koi_tce_plnt_num",
    "koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag",
)


class NasaApiError(Exception):
    """Base class for every way the NASA Exoplanet Archive lookup can fail.
    Never raised for a legitimate empty result (object not found) -- that's
    a normal, well-formed response with zero rows, not an error."""


class NasaApiTimeoutError(NasaApiError):
    """The Archive did not respond within the configured timeout."""


class NasaApiUnavailableError(NasaApiError):
    """A connection-level failure (DNS, TLS, connection refused, etc.) --
    the Archive could not be reached at all."""


class NasaApiHttpError(NasaApiError):
    """The Archive responded with a non-2xx status (e.g. a malformed ADQL
    query, or a server-side error)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"NASA Exoplanet Archive returned HTTP {status_code}: {detail}")


class NasaApiMalformedResponseError(NasaApiError):
    """The Archive responded 200 OK but the body wasn't the JSON array of
    row objects the TAP `format=json` contract promises."""


def query_cumulative_table(where_clause: str) -> list[dict]:
    """Runs `SELECT <FIELDS> FROM cumulative WHERE <where_clause>` against
    the Archive's TAP sync endpoint and returns the raw list of row dicts
    (possibly empty -- that's a legitimate "no match", not an error).

    `where_clause` must already be safe to embed in the query: callers
    build it from regex-validated, type-narrowed identifier components
    (digits, or the canonical KOI/Kepler-name forms this codebase itself
    constructs) -- never the raw user-supplied Object ID string directly.
    """
    select_clause = ", ".join(FIELDS)
    return run_adql(f"select {select_clause} from cumulative where {where_clause}", where_clause)


# Kepler DR25 stellar properties (the catalogue the local KOI table's stellar
# values come from) and the confirmed-planet composite table -- only the
# columns the characterization engine fills in from them.
STELLAR_PROPERTY_FIELDS = ("kepid", "feh", "feh_err1", "feh_err2", "dist", "dist_err1", "dist_err2",
                           "mass", "mass_err1", "mass_err2", "prov_sec", "radius", "logg", "teff")
CONFIRMED_PLANET_FIELDS = ("pl_name", "pl_orbper", "pl_bmasse", "pl_bmasseerr1", "pl_bmasseerr2", "pl_bmassprov",
                           "sy_dist", "sy_disterr1", "sy_disterr2")


def query_dr25_stellar(kepid: int) -> list[dict]:
    """Kepler Q1-Q17 DR25 stellar row(s) for one KIC star."""
    return run_adql(f"select {', '.join(STELLAR_PROPERTY_FIELDS)} from q1_q17_dr25_ks where kepid = {int(kepid)}",
                    f"kepid = {int(kepid)}")


def query_confirmed_planet(pl_name: str) -> list[dict]:
    """Confirmed-planet composite row for one planet name (e.g. 'Kepler-227 b')."""
    safe = pl_name.replace("'", "''")
    return run_adql(f"select {', '.join(CONFIRMED_PLANET_FIELDS)} from pscomppars where pl_name = '{safe}'",
                    f"pl_name = '{safe}'")


def run_adql(adql: str, where_clause: str = "") -> list[dict]:
    """Runs one ADQL query against the Archive's TAP sync endpoint and
    returns the raw JSON rows, raising a typed NasaApiError on failure."""
    settings = get_settings()
    logger.info("nasa_api_query_started", extra={"where_clause": where_clause})
    try:
        response = httpx.get(
            settings.nasa_api_base_url,
            params={"query": adql, "format": "json"},
            timeout=settings.nasa_api_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        logger.error("nasa_api_timeout")
        raise NasaApiTimeoutError("The NASA Exoplanet Archive did not respond in time.") from exc
    except httpx.RequestError as exc:
        logger.error("nasa_api_unreachable", extra={"reason": str(exc)})
        raise NasaApiUnavailableError("The NASA Exoplanet Archive could not be reached.") from exc

    if response.status_code != 200:
        # The Archive returns error details as a VOTABLE XML document (even
        # when JSON was requested) on failure -- never try to JSON-parse a
        # non-200 body. Only a short, safe snippet is kept for logging/the
        # user-facing note; never the full raw body.
        detail_snippet = response.text.strip().replace("\n", " ")[:200]
        logger.error("nasa_api_http_error", extra={"status_code": response.status_code})
        raise NasaApiHttpError(response.status_code, detail_snippet)

    try:
        rows = response.json()
    except ValueError as exc:
        logger.error("nasa_api_malformed_response")
        raise NasaApiMalformedResponseError(
            "The NASA Exoplanet Archive returned a response that was not valid JSON."
        ) from exc

    if not isinstance(rows, list):
        logger.error("nasa_api_malformed_response", extra={"reason": "not_a_list"})
        raise NasaApiMalformedResponseError(
            "The NASA Exoplanet Archive returned an unexpected response shape (expected a JSON array)."
        )

    logger.info("nasa_api_query_finished", extra={"n_rows": len(rows)})
    return rows
