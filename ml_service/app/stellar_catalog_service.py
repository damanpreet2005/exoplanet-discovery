"""
Stellar catalog service: looks up an uploaded light curve's Object ID
against the local KOI catalogue and returns the catalog-only KOI fields
(koi_score, koi_tce_plnt_num, koi_steff, koi_slogg, koi_srad, ra, dec,
koi_kepmag) the Random Forest needs but a light curve alone cannot supply.
Deliberately isolated from app/feature_engine.py and app/predictor.py (the
RF/CNN/ensemble code) -- this module's only job is "Object ID in, real
catalog data (or an explicit non-match/error) out".

DATA SOURCE -- real, not fabricated: the NASA Exoplanet Archive's Kepler
Objects of Interest (KOI) "cumulative" table, shipped as a local snapshot at
ml_service/data/koi_catalog.csv (see app/koi_catalog.py, which owns loading
and indexing the file -- this module only parses identifiers and interprets
the matching rows). This is the same table `app/feature_aliases.py`'s
MODEL_FEATURE_ORDER was independently verified against, so resolving a
target's stellar/catalog parameters from it is a legitimate catalog lookup
by identifier, not an estimate and not an invented value. Lookups are local
and offline: they never depend on the live Archive being reachable.

IDENTIFIER TYPES -- this deployment's trained model was fit on Kepler KOI
data (see app/feature_aliases.py's provenance notes), so only Kepler-mission
identifiers can be resolved: a KIC ID ('KIC 11904151' or a bare integer, which
is assumed to be a KIC ID since this catalog is Kepler-only), a KOI name
('K00752.01'), a confirmed Kepler planet name ('Kepler-227 b'), or a Kepler DR25
TCE identifier ('010797460-01' = KIC 10797460, TCE planet number 1, matched
against kepid + koi_tce_plnt_num). A TESS
Input Catalog (TIC) identifier is a DIFFERENT catalog's numbering scheme for
a different mission -- 'TIC 12345' and 'KIC 12345' are not the same object,
and this module never treats one as the other. TIC-shaped input is detected
and rejected with an explicit, distinct status rather than silently
searched against the (unrelated) Kepler KIC index. Likewise a KIC number is
only ever matched against `kepid`, and a KOI number only against
`kepoi_name` -- 'KIC 752' and 'KOI 752' are unrelated objects.

A single identifier can resolve to more than one catalog row: a star (KIC/
kepid) can host multiple KOIs (planet candidates), each with its own
koi_score and koi_tce_plnt_num, while sharing the same stellar parameters
(koi_steff/koi_slogg/koi_srad/ra/dec/koi_kepmag). This module reflects that
distinction rather than silently picking a row: stellar fields are returned
whenever the star is uniquely identified; koi_score/koi_tce_plnt_num are
only returned when the request resolves to exactly one KOI (planet
candidate) row.
"""
import logging
import math
import re
from dataclasses import dataclass, field

from app.koi_catalog import KoiCatalog, KoiCatalogUnavailableError, get_koi_catalog, normalize_identifier

logger = logging.getLogger("ml_service")

STELLAR_FIELDS = ("koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag")
KOI_LEVEL_FIELDS = ("koi_score", "koi_tce_plnt_num")

MAX_OBJECT_ID_LENGTH = 64


class InvalidObjectIdError(Exception):
    """Raised when the supplied Object ID fails basic input validation
    (missing, not a string, or unreasonably long) -- distinct from a catalog
    lookup miss, which is not an error but a legitimate 'not found' result."""


def _coerce_float(raw) -> float | None:
    """Accepts a catalogue cell for a numeric field: a numeric string, a
    native float/int, or None/blank for a column the KOI table itself has no
    recorded value for. NaN/inf are treated as missing, so every value that
    reaches the API is JSON-safe."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        raw = str(raw).strip()
        if raw == "":
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
    return value if math.isfinite(value) else None


_normalize = normalize_identifier


@dataclass
class CatalogResolution:
    requested_identifier: str | None
    identifier_type: str  # "kic" | "koi_name" | "kepler_name" | "tce" | "tic" | "unrecognized" | "none"
    match_status: str  # "not_provided" | "not_found" | "unsupported_identifier_type" | "lookup_error" | "matched_koi" | "matched_star"
    matched_kepid: int | None = None
    matched_kepoi_name: str | None = None
    matched_kepler_name: str | None = None
    n_candidate_rows: int = 0
    fields: dict[str, float | None] = field(default_factory=dict)
    field_available: dict[str, bool] = field(default_factory=dict)
    note: str = ""
    # Raw catalogue row(s) behind the match, so the characterization engine
    # can read uncertainty (_err1/_err2) and planet-level reference columns
    # without a second lookup. Empty for any non-match.
    matched_rows: list[dict] = field(default_factory=list)


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


def _lookup_error_resolution(identifier: str, identifier_type: str, exc: KoiCatalogUnavailableError) -> CatalogResolution:
    """The catalogue itself couldn't be read -- distinct from a legitimate
    'not found', so the caller/frontend never tells the user an object
    doesn't exist when the lookup simply couldn't run."""
    return _empty_resolution(
        identifier, identifier_type, "lookup_error",
        "The local KOI catalogue could not be loaded, so this Object ID could not be looked up. "
        "This is a server configuration problem, not a missing object.",
    )


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
        matched_rows=[row],
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
        matched_rows=list(rows),
    )


# Kepler DR25 TCE identifiers: '<KIC, zero-padded to 9 digits>-<planet number>'
# (e.g. '010797460-01'), optionally prefixed with 'TCE'/'KIC', or the spelled
# form 'KIC 10797460 TCE 1'. Matched on the raw string, because normalization
# strips the hyphen that distinguishes a TCE from a bare KIC number.
_TCE_RE = re.compile(r"^(?:TCE[\s:_]*)?(?:KIC[\s_]*)?0*(\d{1,9})-0*(\d{1,2})$")
_TCE_SPELLED_RE = re.compile(r"^KIC[\s_-]*0*(\d{1,9})[\s_-]*TCE[\s_-]*0*(\d{1,2})$")


def _parse_tce(raw: str) -> tuple[int, int] | None:
    text = raw.strip().upper()
    m = _TCE_RE.match(text) or _TCE_SPELLED_RE.match(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _classify_identifier(compact: str) -> str:
    """Classifies the *shape* of a normalized identifier before any lookup
    is attempted, specifically so a TESS TIC number is never treated as a
    Kepler KIC number just because both are integers."""
    if re.match(r"^TIC\d+$", compact):
        return "tic"
    # A trailing ".0"/".00" is tolerated (a KIC number exported as a float);
    # anything else after the dot is not a KIC ID.
    if re.match(r"^(?:KIC)?\d+(?:\.0+)?$", compact):
        return "kic"
    if re.match(r"^K\d{5}\.\d{2}$", compact) or re.match(r"^KOI\d+(\.\d+)?$", compact):
        return "koi_name"
    if compact.startswith("KEPLER"):
        return "kepler_name"
    return "unrecognized"


def _coerce_object_id(object_id) -> str | None:
    """Object IDs normally arrive as form strings, but a bare KIC number may
    come through as an int (or an integral float such as 10797460.0 from a
    spreadsheet export). Those are stringified as plain integers -- never as
    '10797460.0', which would no longer look like a KIC ID."""
    if object_id is None or isinstance(object_id, str):
        return object_id
    if isinstance(object_id, bool):
        raise InvalidObjectIdError("Object ID must be a string or an integer KIC ID.")
    if isinstance(object_id, int):
        return str(object_id)
    if isinstance(object_id, float) and math.isfinite(object_id) and object_id.is_integer():
        return str(int(object_id))
    raise InvalidObjectIdError("Object ID must be a string or an integer KIC ID.")


def resolve_object_id(object_id: str | int | None) -> CatalogResolution:
    """Resolves an Object ID against the local KOI catalogue.
    Accepts a KIC ID ('11904151', 'KIC 11904151', 11904151), a KOI name
    ('K00752.01', 'KOI-752.01', 'KOI 752'), or a confirmed Kepler planet name
    ('Kepler-227 b'). A TESS TIC identifier ('TIC 141914082') is recognized
    and explicitly rejected as unsupported for this (Kepler-trained)
    deployment rather than ever being searched against the unrelated KIC
    field. Returns an explicit not-found/not-provided/unsupported/
    lookup-error result rather than ever guessing a closest match or
    fabricating a value when the catalogue can't be read."""
    object_id = _coerce_object_id(object_id)
    if object_id is None or not object_id.strip():
        return _empty_resolution(None, "none", "not_provided", "No Object ID was supplied.")

    raw = object_id.strip()
    if len(raw) > MAX_OBJECT_ID_LENGTH:
        raise InvalidObjectIdError(f"Object ID must be at most {MAX_OBJECT_ID_LENGTH} characters (got {len(raw)}).")

    tce = _parse_tce(raw)
    if tce is not None:
        try:
            catalog = get_koi_catalog()
        except KoiCatalogUnavailableError as exc:
            return _lookup_error_resolution(raw, "tce", exc)
        return _resolve_tce(catalog, raw, *tce)

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

    if identifier_type == "unrecognized":
        return _empty_resolution(
            raw, "unrecognized", "not_found",
            f"'{raw}' did not match any recognized KIC ID, KOI name, or Kepler planet name format.",
        )

    try:
        catalog = get_koi_catalog()
    except KoiCatalogUnavailableError as exc:
        return _lookup_error_resolution(raw, identifier_type, exc)

    if identifier_type == "kic":
        return _resolve_kic(catalog, raw, compact)
    if identifier_type == "koi_name":
        return _resolve_koi_name(catalog, raw, compact)
    return _resolve_kepler_name(catalog, raw, compact)


def _resolution_from_rows(raw: str, identifier_type: str, rows: list[dict], single_note: str) -> CatalogResolution:
    """One row -> a full KOI match. Several rows on one star -> stellar
    fields only. Several rows spread across different stars can only mean
    conflicting catalogue entries for one identifier; nothing is resolved
    rather than picking one arbitrarily."""
    if len(rows) == 1:
        return _resolution_from_single_row(raw, identifier_type, rows[0], single_note)
    kepids = {row["kepid"] for row in rows}
    if len(kepids) == 1:
        return _resolution_from_star_only(raw, identifier_type, rows[0]["kepid"], rows)
    logger.warning("koi_catalog_ambiguous_identifier", extra={"identifier": raw, "n_rows": len(rows)})
    resolution = _empty_resolution(
        raw, identifier_type, "lookup_error",
        f"'{raw}' matches {len(rows)} conflicting KOI catalogue entries on different stars, so no "
        "stellar parameters were resolved. Provide a more specific identifier.",
    )
    resolution.n_candidate_rows = len(rows)
    return resolution


def _resolve_tce(catalog: KoiCatalog, raw: str, kepid: int, planet_number: int) -> CatalogResolution:
    """A TCE (KIC + TCE planet number) identifies exactly one KOI row, via
    the catalogue's kepid and koi_tce_plnt_num columns."""
    rows = [r for r in catalog.by_kepid.get(kepid, []) if _coerce_float(r.get("koi_tce_plnt_num")) == planet_number]
    if rows:
        return _resolution_from_rows(raw, "tce", rows, f"Matched TCE {kepid:09d}-{planet_number:02d} "
                                                       f"({rows[0]['kepoi_name']}).")
    return _empty_resolution(raw, "tce", "not_found",
                             f"No KOI catalogue entry for TCE {kepid:09d}-{planet_number:02d} (KIC {kepid}, "
                             f"TCE planet number {planet_number}).")


def _resolve_kic(catalog: KoiCatalog, raw: str, compact: str) -> CatalogResolution:
    kepid = int(re.match(r"^(?:KIC)?(\d+)", compact).group(1))
    rows = catalog.by_kepid.get(kepid, [])
    if rows:
        return _resolution_from_rows(raw, "kic", rows, f"Matched KIC {kepid} (single KOI on record).")
    return _empty_resolution(raw, "kic", "not_found", f"No catalog entry found for KIC {kepid}.")


def _resolve_canonical_koi_name(catalog: KoiCatalog, raw: str, canonical: str) -> CatalogResolution:
    rows = catalog.by_kepoi_name.get(canonical, [])
    if rows:
        return _resolution_from_rows(raw, "koi_name", rows, f"Matched KOI name {canonical}.")
    return _empty_resolution(raw, "koi_name", "not_found", f"No catalog entry found for KOI {canonical}.")


def _resolve_koi_name(catalog: KoiCatalog, raw: str, compact: str) -> CatalogResolution:
    # Canonical KOI name, e.g. K00752.01.
    exact_match = re.match(r"^K(\d{5})\.(\d{2})$", compact)
    if exact_match:
        canonical = f"K{int(exact_match.group(1)):05d}.{int(exact_match.group(2)):02d}"
        return _resolve_canonical_koi_name(catalog, raw, canonical)

    # KOI-<number>[.<planet>] in looser forms, e.g. "KOI-752.01" or "KOI752".
    koi_match = re.match(r"^KOI0*(\d+)(?:\.(\d+))?$", compact)
    if koi_match:
        koi_number = int(koi_match.group(1))
        planet_suffix = koi_match.group(2)
        if planet_suffix:
            canonical = f"K{koi_number:05d}.{int(planet_suffix):02d}"
            return _resolve_canonical_koi_name(catalog, raw, canonical)

        rows = catalog.by_koi_number.get(koi_number, [])
        if rows:
            return _resolution_from_rows(raw, "koi_name", rows, f"Matched KOI {koi_number} (single planet candidate).")
        return _empty_resolution(raw, "koi_name", "not_found", f"No catalog entry found for KOI {koi_number}.")

    return _empty_resolution(raw, "koi_name", "not_found", f"'{raw}' is not a recognized KOI name format.")


def _resolve_kepler_name(catalog: KoiCatalog, raw: str, compact: str) -> CatalogResolution:
    if not re.match(r"^KEPLER\d+[A-Z]*$", compact):
        return _empty_resolution(raw, "kepler_name", "not_found", f"'{raw}' is not a recognized Kepler planet name format.")

    # Exact normalized match only -- 'Kepler-2270 x' can never satisfy a
    # request for 'Kepler-227 b'.
    rows = catalog.by_kepler_name.get(compact, [])
    if rows:
        return _resolution_from_rows(raw, "kepler_name", rows, f"Matched Kepler name {rows[0]['kepler_name']}.")
    return _empty_resolution(raw, "kepler_name", "not_found", f"No catalog entry found for Kepler name '{raw}'.")
