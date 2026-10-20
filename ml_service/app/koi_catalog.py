"""
Local KOI catalogue: loads the NASA Exoplanet Archive KOI `cumulative`
table snapshot shipped at ml_service/data/koi_catalog.csv (baked into the
Docker image at /srv/data by the Dockerfile's `COPY data ./data`) and
indexes it for identifier lookups.

This module's only job is "catalogue file in, indexed rows out (or a typed
error)". It knows nothing about how user-supplied Object IDs are parsed or
which fields the RF needs -- that stays in app/stellar_catalog_service.py,
this module's only caller.

Loaded with the stdlib csv module (no pandas dependency) and kept as raw
strings: numeric coercion, including blank/NaN/inf handling, is done by the
caller per field, so one blank column never discards a whole row.

IDENTIFIER COLUMNS (verified against the file's header):
  kepid       -- Kepler Input Catalog (KIC) number of the host star. One star
                 can host several KOIs, so this is NOT unique.
  kepoi_name  -- KOI designation, e.g. 'K00752.01'. Unique per row.
  kepler_name -- confirmed planet name, e.g. 'Kepler-227 b'. Blank for
                 unconfirmed candidates / false positives.
These are separate identifier systems: a KIC number is never looked up as a
KOI number or vice versa.
"""
import csv
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("ml_service")

IDENTIFIER_COLUMNS = ("kepid", "kepoi_name", "kepler_name")
REQUIRED_COLUMNS = IDENTIFIER_COLUMNS + (
    "koi_score", "koi_tce_plnt_num",
    "koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag",
)

_KOI_NAME_RE = re.compile(r"^K(\d{5})\.(\d{2})$")


class KoiCatalogUnavailableError(Exception):
    """The catalogue file is missing, unreadable, or doesn't have the
    expected columns. Always a lookup failure -- never to be reported to the
    user as 'object not found'."""


def normalize_identifier(s: str) -> str:
    """Uppercase, strip surrounding whitespace, collapse internal
    whitespace/hyphens/underscores -- so 'Kepler-227 b', 'kepler 227b', and
    'KEPLER-227-B' all normalize identically."""
    return re.sub(r"[\s\-_]+", "", s.strip().upper())


def _parse_kepid(raw: str | None) -> int | None:
    """kepid is an integer column, but tolerate an exported '10797460.0'
    without ever accepting a genuinely fractional value."""
    if raw is None or not raw.strip():
        return None
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value.is_integer() else None


@dataclass
class KoiCatalog:
    path: str
    n_rows: int = 0
    by_kepid: dict[int, list[dict]] = field(default_factory=dict)
    by_kepoi_name: dict[str, list[dict]] = field(default_factory=dict)
    by_koi_number: dict[int, list[dict]] = field(default_factory=dict)
    by_kepler_name: dict[str, list[dict]] = field(default_factory=dict)  # keyed by normalize_identifier()


def load_koi_catalog(path: str | Path) -> KoiCatalog:
    path = Path(path)
    try:
        handle = path.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise KoiCatalogUnavailableError(f"KOI catalogue could not be opened at {path}: {exc.strerror or exc}") from exc

    catalog = KoiCatalog(path=str(path))
    skipped = 0
    with handle:
        try:
            reader = csv.DictReader(handle)
            header = [h.strip() for h in (reader.fieldnames or [])]
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                raise KoiCatalogUnavailableError(
                    f"KOI catalogue at {path} is missing required column(s): {', '.join(missing)}."
                )
            reader.fieldnames = header

            for raw_row in reader:
                row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items() if k is not None}
                kepid = _parse_kepid(row.get("kepid"))
                kepoi_name = (row.get("kepoi_name") or "").upper()
                if kepid is None or not _KOI_NAME_RE.match(kepoi_name):
                    skipped += 1
                    continue
                row["kepid"] = kepid
                row["kepoi_name"] = kepoi_name
                row["kepler_name"] = row.get("kepler_name") or None

                catalog.by_kepid.setdefault(kepid, []).append(row)
                catalog.by_kepoi_name.setdefault(kepoi_name, []).append(row)
                koi_number = int(_KOI_NAME_RE.match(kepoi_name).group(1))
                catalog.by_koi_number.setdefault(koi_number, []).append(row)
                if row["kepler_name"]:
                    catalog.by_kepler_name.setdefault(normalize_identifier(row["kepler_name"]), []).append(row)
                catalog.n_rows += 1
        except (csv.Error, UnicodeDecodeError) as exc:
            raise KoiCatalogUnavailableError(f"KOI catalogue at {path} could not be parsed: {exc}") from exc

    if catalog.n_rows == 0:
        raise KoiCatalogUnavailableError(f"KOI catalogue at {path} contains no usable rows.")

    logger.info(
        "koi_catalog_loaded",
        extra={"path": str(path), "n_rows": catalog.n_rows, "n_skipped": skipped, "n_stars": len(catalog.by_kepid)},
    )
    return catalog


_catalog: KoiCatalog | None = None
_lock = threading.Lock()


def get_koi_catalog() -> KoiCatalog:
    """Loads the configured catalogue once per process and reuses it. A
    failed load is not cached, so a fixed/remounted file is picked up on the
    next request without a restart."""
    global _catalog
    path = get_settings().koi_catalog_path
    if _catalog is not None and _catalog.path == str(Path(path)):
        return _catalog
    with _lock:
        if _catalog is None or _catalog.path != str(Path(path)):
            try:
                _catalog = load_koi_catalog(path)
            except KoiCatalogUnavailableError as exc:
                logger.error("koi_catalog_load_failed", extra={"reason": str(exc)})
                raise
    return _catalog
