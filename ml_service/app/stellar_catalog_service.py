"""
Stellar catalog service: looks up an uploaded light curve's Object ID
against the real NASA Exoplanet Archive and returns the catalog-only KOI
fields (koi_score, koi_tce_plnt_num, koi_steff, koi_slogg, koi_srad, ra,
dec, koi_kepmag) the Random Forest needs but a light curve alone cannot
supply. Deliberately isolated from app/feature_engine.py and
app/predictor.py (the RF/CNN/ensemble code) -- this module's only job is
"Object ID in, real catalog data (or an explicit non-match/error) out".

DATA SOURCE -- real, not fabricated, and now fetched live: every lookup
queries the NASA Exoplanet Archive's Kepler Objects of Interest (KOI)
"cumulative" table over its TAP API (see app/nasa_exoplanet_archive_client.py,
which owns all the raw HTTP/ADQL mechanics -- this module only builds WHERE
clauses and interprets the rows that come back). This is the same table
`app/feature_aliases.py`'s MODEL_FEATURE_ORDER was independently verified
against, so resolving a target's stellar/catalog parameters from it is a
legitimate catalog lookup by identifier, not an estimate and not an invented
value.

(A local snapshot of this same table previously shipped at
ml_service/data/koi_catalog.csv for offline lookups. Nothing in this module
reads that file anymore -- see the migration note in that file's directory
for whether it's still needed.)

IDENTIFIER TYPES -- this deployment's trained model was fit on Kepler KOI
data (see app/feature_aliases.py's provenance notes), so only Kepler-mission
identifiers can be resolved: a KIC ID ('KIC 11904151' or a bare integer, which
is assumed to be a KIC ID since this catalog is Kepler-only), a KOI name
('K00752.01'), or a confirmed Kepler planet name ('Kepler-227 b'). A TESS
Input Catalog (TIC) identifier is a DIFFERENT catalog's numbering scheme for
a different mission -- 'TIC 12345' and 'KIC 12345' are not the same object,
and this module never treats one as the other. TIC-shaped input is detected
and rejected with an explicit, distinct status rather than silently
searched against the (unrelated) Kepler KIC index.

A single identifier can resolve to more than one catalog row: a star (KIC/
kepid) can host multiple KOIs (planet candidates), each with its own
koi_score and koi_tce_plnt_num, while sharing the same stellar parameters
(koi_steff/koi_slogg/koi_srad/ra/dec/koi_kepmag). This module reflects that
distinction rather than silently picking a row: stellar fields are returned
whenever the star is uniquely identified; koi_score/koi_tce_plnt_num are
only returned when the request resolves to exactly one KOI (planet
candidate) row.

SAFETY NOTE on query construction: no raw user-supplied Object ID text is
ever interpolated directly into an ADQL WHERE clause. Every value embedded
in a query is either a regex-validated integer, or a canonical KOI/Kepler-
name string this module reconstructs itself from regex-captured digits
(e.g. f"K{n:05d}.{p:02d}") -- never the caller's original string verbatim.
"""
import logging
import re
from dataclasses import dataclass, field

from app.cache import InMemoryTTLCache
from app.config import get_settings
from app.nasa_exoplanet_archive_client import (
    NasaApiError,
    NasaApiHttpError,
    NasaApiMalformedResponseError,
    NasaApiTimeoutError,
    NasaApiUnavailableError,
    query_cumulative_table,
)

logger = logging.getLogger("ml_service")

STELLAR_FIELDS = ("koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag")
KOI_LEVEL_FIELDS = ("koi_score", "koi_tce_plnt_num")

MAX_OBJECT_ID_LENGTH = 64

_cache: InMemoryTTLCache | None = None


def _query_cache() -> InMemoryTTLCache:
    """Simple in-memory TTL cache (Object ID -> raw NASA rows), so the same
    star/KOI isn't re-queried over the network on every analysis. Lazily
    built from settings rather than at import time, so tests can override
    NASA_CACHE_* env vars freely. Intentionally in-process (no Redis/new
    infra) -- consistent with app/cache.py's existing prediction cache."""
    global _cache
    if _cache is None:
        settings = get_settings()
        _cache = InMemoryTTLCache(settings.nasa_cache_max_size, settings.nasa_cache_ttl_seconds)
    return _cache


def _cached_query(cache_key: str, where_clause: str) -> list[dict]:
    cache = _query_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached["rows"]
    rows = query_cumulative_table(where_clause)
    cache.set(cache_key, {"rows": rows})
    return rows


class InvalidObjectIdError(Exception):
    """Raised when the supplied Object ID fails basic input validation
    (missing, not a string, or unreasonably long) -- distinct from a catalog
    lookup miss, which is not an error but a legitimate 'not found' result."""


def _coerce_float(raw) -> float | None:
    """Accepts whatever the NASA TAP JSON response hands back for a numeric
    field: a native float/int, a numeric string, or None/blank for a column
    the Archive itself has no recorded value for."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw == raw else None  # filters NaN
    raw = str(raw).strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value == value else None


def _normalize(s: str) -> str:
    """Uppercase, strip surrounding whitespace, collapse internal
    whitespace/hyphens/underscores -- so 'Kepler-227 b', 'kepler 227b', and
    'KEPLER-227-B' all normalize identically."""
    return re.sub(r"[\s\-_]+", "", s.strip().upper())


@dataclass
class CatalogResolution:
    requested_identifier: str | None
    identifier_type: str  # "kic" | "koi_name" | "kepler_name" | "tic" | "unrecognized" | "none"
    match_status: str  # "not_provided" | "not_found" | "unsupported_identifier_type" | "lookup_error" | "matched_koi" | "matched_star"
    matched_kepid: int | None = None
    matched_kepoi_name: str | None = None
    matched_kepler_name: str | None = None
    n_candidate_rows: int = 0
    fields: dict[str, float | None] = field(default_factory=dict)
    field_available: dict[str, bool] = field(default_factory=dict)
    note: str = ""


def _empty_resolution(identifier: str | None, identifier_type: str, status: str, note: str) -> CatalogResolution:
    all_fields = STELLAR_FIELDS + KOI_LEVEL_FIELDS
    return CatalogResolution(
        requested_identifier=identifier,
        identifier_type=identifier_type,
        match_status=status,
        fields={k: None for k in all_fields},
        field_available={k: False for k in all_fields},
        note=note,
    )


def _lookup_error_resolution(identifier: str, identifier_type: str, exc: NasaApiError) -> CatalogResolution:
    """A genuine service-availability problem (timeout/unreachable/HTTP
    error/malformed body) -- distinct from a legitimate 'not found', so the
    caller/frontend can tell "this Object ID doesn't exist" apart from "the
    Archive couldn't be reached right now, try again"."""
    if isinstance(exc, NasaApiTimeoutError):
        note = "The NASA Exoplanet Archive did not respond in time. Please try again shortly."
    elif isinstance(exc, NasaApiUnavailableError):
        note = "The NASA Exoplanet Archive could not be reached. Please try again shortly."
    elif isinstance(exc, NasaApiHttpError):
        note = f"The NASA Exoplanet Archive returned an error (HTTP {exc.status_code}). Please try again shortly."
    elif isinstance(exc, NasaApiMalformedResponseError):
        note = "The NASA Exoplanet Archive returned an unexpected response. Please try again shortly."
    else:
        note = "The NASA Exoplanet Archive lookup failed unexpectedly."
    return _empty_resolution(identifier, identifier_type, "lookup_error", note)


def _resolution_from_single_row(identifier: str, identifier_type: str, row: dict, note: str) -> CatalogResolution:
    fields: dict[str, float | None] = {}
    availability: dict[str, bool] = {}
    for canonical in STELLAR_FIELDS + KOI_LEVEL_FIELDS:
        value = _coerce_float(row.get(canonical))
        fields[canonical] = value
        availability[canonical] = value is not None

    kepid_raw = row.get("kepid")
    return CatalogResolution(
        requested_identifier=identifier,
        identifier_type=identifier_type,
        match_status="matched_koi",
        matched_kepid=int(kepid_raw) if kepid_raw is not None else None,
        matched_kepoi_name=(str(row.get("kepoi_name")).strip() or None) if row.get("kepoi_name") else None,
        matched_kepler_name=(str(row.get("kepler_name")).strip() or None) if row.get("kepler_name") else None,
        n_candidate_rows=1,
        fields=fields,
        field_available=availability,
        note=note,
    )


def _resolution_from_star_only(identifier: str, identifier_type: str, kepid: int, rows: list[dict]) -> CatalogResolution:
    """Multiple KOI rows share this KIC ID. Stellar parameters are the same
    physical star, so they're safe to report; koi_score/koi_tce_plnt_num are
    per-candidate and would be ambiguous, so they're explicitly withheld."""
    representative = rows[0]
    fields: dict[str, float | None] = {}
    availability: dict[str, bool] = {}
    for canonical in STELLAR_FIELDS:
        value = _coerce_float(representative.get(canonical))
        fields[canonical] = value
        availability[canonical] = value is not None
    for canonical in KOI_LEVEL_FIELDS:
        fields[canonical] = None
        availability[canonical] = False

    return CatalogResolution(
        requested_identifier=identifier,
        identifier_type=identifier_type,
        match_status="matched_star",
        matched_kepid=kepid,
        n_candidate_rows=len(rows),
        fields=fields,
        field_available=availability,
        note=(
            f"{len(rows)} KOI candidates share KIC {kepid}; stellar parameters are shared and "
            "were resolved, but koi_score/koi_tce_plnt_num are specific to one planet candidate "
            "and were left unavailable. Provide a KOI name (e.g. K00752.01) or Kepler name (e.g. "
            "'Kepler-227 b') to resolve those two fields as well."
        ),
    )


def _classify_identifier(compact: str) -> str:
    """Classifies the *shape* of a normalized identifier before any lookup
    is attempted, specifically so a TESS TIC number is never treated as a
    Kepler KIC number just because both are integers."""
    if re.match(r"^TIC\d+$", compact):
        return "tic"
    if re.match(r"^(?:KIC)?\d+$", compact):
        return "kic"
    if re.match(r"^K\d{5}\.\d{2}$", compact) or re.match(r"^KOI\d+(\.\d+)?$", compact):
        return "koi_name"
    if compact.startswith("KEPLER"):
        return "kepler_name"
    return "unrecognized"


def resolve_object_id(object_id: str | None) -> CatalogResolution:
    """Resolves an Object ID against the live NASA Exoplanet Archive.
    Accepts a KIC ID ('11904151', 'KIC 11904151'), a KOI name ('K00752.01',
    'KOI-752.01', 'KOI 752'), or a confirmed Kepler planet name
    ('Kepler-227 b'). A TESS TIC identifier ('TIC 141914082') is recognized
    and explicitly rejected as unsupported for this (Kepler-trained)
    deployment rather than ever being searched against the unrelated KIC
    field. Returns an explicit not-found/not-provided/unsupported/
    lookup-error result rather than ever guessing a closest match or
    fabricating a value on a network failure."""
    if object_id is None or not object_id.strip():
        return _empty_resolution(None, "none", "not_provided", "No Object ID was supplied.")

    raw = object_id.strip()
    if len(raw) > MAX_OBJECT_ID_LENGTH:
        raise InvalidObjectIdError(f"Object ID must be at most {MAX_OBJECT_ID_LENGTH} characters (got {len(raw)}).")

    compact = _normalize(raw)
    identifier_type = _classify_identifier(compact)

    if identifier_type == "tic":
        return _empty_resolution(
            raw, "tic", "unsupported_identifier_type",
            f"'{raw}' looks like a TESS Input Catalog (TIC) identifier. This deployment's model "
            "was trained on Kepler KOI data, and its catalog lookup only covers Kepler KIC/KOI/"
            "Kepler-name identifiers -- a TIC number is a different catalog's numbering scheme for "
            "a different mission and is never matched against it. Provide the object's KIC ID, "
            "KOI name, or confirmed Kepler planet name instead.",
        )

    try:
        if identifier_type == "kic":
            return _resolve_kic(raw, compact)
        if identifier_type == "koi_name":
            return _resolve_koi_name(raw, compact)
        if identifier_type == "kepler_name":
            return _resolve_kepler_name(raw, compact)
    except NasaApiError as exc:
        return _lookup_error_resolution(raw, identifier_type, exc)

    return _empty_resolution(
        raw, "unrecognized", "not_found",
        f"'{raw}' did not match any recognized KIC ID, KOI name, or Kepler planet name format.",
    )


def _resolve_kic(raw: str, compact: str) -> CatalogResolution:
    kepid_match = re.match(r"^(?:KIC)?(\d+)$", compact)
    kepid = int(kepid_match.group(1))
    rows = _cached_query(f"kic:{kepid}", f"kepid = {kepid}")
    if rows:
        if len(rows) == 1:
            return _resolution_from_single_row(raw, "kic", rows[0], f"Matched KIC {kepid} (single KOI on record).")
        return _resolution_from_star_only(raw, "kic", kepid, rows)
    return _empty_resolution(raw, "kic", "not_found", f"No catalog entry found for KIC {kepid}.")


def _resolve_koi_name(raw: str, compact: str) -> CatalogResolution:
    # Canonical KOI name, e.g. K00752.01.
    exact_match = re.match(r"^K(\d{5})\.(\d{2})$", compact)
    if exact_match:
        canonical = f"K{int(exact_match.group(1)):05d}.{int(exact_match.group(2)):02d}"
        rows = _cached_query(f"koi_name:{canonical}", f"kepoi_name = '{canonical}'")
        if rows:
            return _resolution_from_single_row(raw, "koi_name", rows[0], f"Matched KOI name {canonical}.")
        return _empty_resolution(raw, "koi_name", "not_found", f"No catalog entry found for KOI {canonical}.")

    # KOI-<number>[.<planet>] in looser forms, e.g. "KOI-752.01" or "KOI752".
    koi_match = re.match(r"^KOI0*(\d+)(?:\.(\d+))?$", compact)
    if koi_match:
        koi_number = int(koi_match.group(1))
        planet_suffix = koi_match.group(2)
        if planet_suffix:
            canonical = f"K{koi_number:05d}.{int(planet_suffix):02d}"
            rows = _cached_query(f"koi_name:{canonical}", f"kepoi_name = '{canonical}'")
            if rows:
                return _resolution_from_single_row(raw, "koi_name", rows[0], f"Matched KOI name {canonical}.")
            return _empty_resolution(raw, "koi_name", "not_found", f"No catalog entry found for KOI {canonical}.")

        prefix = f"K{koi_number:05d}."
        rows = _cached_query(f"koi_number:{koi_number}", f"kepoi_name like '{prefix}%'")
        if rows:
            if len(rows) == 1:
                return _resolution_from_single_row(raw, "koi_name", rows[0], f"Matched KOI {koi_number} (single planet candidate).")
            kepid_raw = rows[0].get("kepid")
            kepid = int(kepid_raw) if kepid_raw is not None else 0
            return _resolution_from_star_only(raw, "koi_name", kepid, rows)
        return _empty_resolution(raw, "koi_name", "not_found", f"No catalog entry found for KOI {koi_number}.")

    return _empty_resolution(raw, "koi_name", "not_found", f"'{raw}' is not a recognized KOI name format.")


def _resolve_kepler_name(raw: str, compact: str) -> CatalogResolution:
    number_match = re.match(r"^KEPLER(\d+[A-Z]*)", compact)
    if not number_match:
        return _empty_resolution(raw, "kepler_name", "not_found", f"'{raw}' is not a recognized Kepler planet name format.")

    # Only the leading digits are a safe/reliable LIKE prefix -- the exact
    # match against candidates (below) is what actually confirms identity,
    # so a slightly loose prefix here can never cause a wrong match.
    digits_match = re.match(r"^(\d+)", number_match.group(1))
    kepler_number = digits_match.group(1) if digits_match else number_match.group(1)

    rows = _cached_query(f"kepler_number:{kepler_number}", f"kepler_name like 'Kepler-{kepler_number}%'")
    for row in rows:
        candidate_name = row.get("kepler_name") or ""
        if _normalize(candidate_name) == compact:
            return _resolution_from_single_row(raw, "kepler_name", row, f"Matched Kepler name {candidate_name}.")
    return _empty_resolution(raw, "kepler_name", "not_found", f"No catalog entry found for Kepler name '{raw}'.")
