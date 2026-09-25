"""
Input-name normalization / alias-handling layer for raw KOI-style tabular
input, sitting in front of the existing prediction pipeline
(scaler -> random_forest / cnn -> weighted fusion, unchanged).

FEATURE ORDER -- now verified, not guessed:
The model artifact itself still exposes no feature names (`scaler.
feature_names_in_` / `random_forest.feature_names_in_` are both None) -- that
fact hasn't changed. What changed is that the original training code's exact
feature-selection logic was supplied:

    drop_cols = ['rowid', 'kepid', 'kepoi_name', 'kepler_name',
                 'koi_disposition', 'koi_pdisposition']
    drop_cols += [c for c in df.columns if 'fpflag' in c or 'err' in c]
    feature_cols = [c for c in df.columns
                    if c not in drop_cols and df[c].dtype in ['float64', 'int64']]

This was independently verified (not just trusted) by running that exact
logic against the real cumulative.csv (50 columns, 9564 rows) with pandas,
which reproduced precisely the 17-column list and order below. MODEL_FEATURE_
ORDER is set to that verified result.
"""
import math
import re

# Canonical KOI column name -> accepted alternative names (case/space/hyphen
# insensitivity is handled separately in `normalize_key`, so aliases here
# are listed in their canonical lowercase/underscore form only).
BASE_ALIASES: dict[str, list[str]] = {
    "koi_score": ["score"],
    "koi_period": ["period", "orbital_period", "planet_period"],
    "koi_time0bk": ["transit_time", "transit_epoch", "t0"],
    "koi_impact": ["impact_parameter", "impact", "b"],
    "koi_duration": ["transit_duration", "duration"],
    "koi_depth": ["transit_depth", "depth", "flux_drop"],
    "koi_prad": ["planet_radius", "planetary_radius", "radius"],
    "koi_teq": ["equilibrium_temperature", "planet_temperature", "temperature"],
    "koi_insol": ["insolation", "stellar_insolation", "incident_flux"],
    "koi_model_snr": ["snr", "signal_to_noise", "signal_noise_ratio"],
    "koi_tce_plnt_num": ["tce_planet_number", "planet_number", "tce_plnt_num"],
    "koi_steff": ["stellar_temperature", "star_temperature", "teff"],
    "koi_slogg": ["stellar_surface_gravity", "surface_gravity", "logg"],
    "koi_srad": ["stellar_radius", "star_radius"],
    "koi_kepmag": ["kepler_magnitude", "stellar_magnitude", "magnitude", "kepmag"],
    "ra": ["right_ascension"],
    "dec": ["declination"],
}

# The exact 17 features the trained model expects, in the exact order the
# training code's column filter produces (verified against the real
# cumulative.csv -- see module docstring above).
MODEL_FEATURE_ORDER: list[str] = [
    "koi_score",
    "koi_period",
    "koi_time0bk",
    "koi_impact",
    "koi_duration",
    "koi_depth",
    "koi_prad",
    "koi_teq",
    "koi_insol",
    "koi_model_snr",
    "koi_tce_plnt_num",
    "koi_steff",
    "koi_slogg",
    "koi_srad",
    "ra",
    "dec",
    "koi_kepmag",
]

# Human-readable display metadata for the UI/API, in the exact
# {canonical, display, unit, aliases} shape requested, ordered to match
# MODEL_FEATURE_ORDER above exactly.
FEATURE_DEFINITIONS: list[dict] = [
    {"canonical": "koi_score", "display": "KOI Score", "unit": "",
     "aliases": BASE_ALIASES["koi_score"]},
    {"canonical": "koi_period", "display": "Orbital Period", "unit": "days",
     "aliases": BASE_ALIASES["koi_period"]},
    {"canonical": "koi_time0bk", "display": "Transit Epoch", "unit": "BJD - 2454833",
     "aliases": BASE_ALIASES["koi_time0bk"]},
    {"canonical": "koi_impact", "display": "Impact Parameter", "unit": "",
     "aliases": BASE_ALIASES["koi_impact"]},
    {"canonical": "koi_duration", "display": "Transit Duration", "unit": "hours",
     "aliases": BASE_ALIASES["koi_duration"]},
    {"canonical": "koi_depth", "display": "Transit Depth", "unit": "ppm",
     "aliases": BASE_ALIASES["koi_depth"]},
    {"canonical": "koi_prad", "display": "Planet Radius", "unit": "Earth radii",
     "aliases": BASE_ALIASES["koi_prad"]},
    {"canonical": "koi_teq", "display": "Equilibrium Temperature", "unit": "K",
     "aliases": BASE_ALIASES["koi_teq"]},
    {"canonical": "koi_insol", "display": "Stellar Insolation", "unit": "Earth flux",
     "aliases": BASE_ALIASES["koi_insol"]},
    {"canonical": "koi_model_snr", "display": "Signal-to-Noise Ratio", "unit": "",
     "aliases": BASE_ALIASES["koi_model_snr"]},
    {"canonical": "koi_tce_plnt_num", "display": "TCE Planet Number", "unit": "",
     "aliases": BASE_ALIASES["koi_tce_plnt_num"]},
    {"canonical": "koi_steff", "display": "Stellar Effective Temperature", "unit": "K",
     "aliases": BASE_ALIASES["koi_steff"]},
    {"canonical": "koi_slogg", "display": "Stellar Surface Gravity", "unit": "log10(cm/s^2)",
     "aliases": BASE_ALIASES["koi_slogg"]},
    {"canonical": "koi_srad", "display": "Stellar Radius", "unit": "Solar radii",
     "aliases": BASE_ALIASES["koi_srad"]},
    {"canonical": "ra", "display": "Right Ascension", "unit": "degrees",
     "aliases": BASE_ALIASES["ra"]},
    {"canonical": "dec", "display": "Declination", "unit": "degrees",
     "aliases": BASE_ALIASES["dec"]},
    {"canonical": "koi_kepmag", "display": "Kepler Magnitude", "unit": "",
     "aliases": BASE_ALIASES["koi_kepmag"]},
]

# Canonical base columns that have _err1/_err2 counterparts in the source
# dataset. Their aliases are derived automatically from BASE_ALIASES below
# (e.g. koi_period -> period -> period_err1 / period_err2).
_ERR_VARIANT_BASES = [
    "koi_period", "koi_time0bk", "koi_impact", "koi_duration", "koi_depth",
    "koi_prad", "koi_teq", "koi_insol", "koi_steff", "koi_slogg", "koi_srad",
]

# Recognized so they can be safely ignored (never passed to the model) --
# these are identifiers/metadata, not features.
ID_METADATA_COLUMNS = {"rowid", "kepid", "kepoi_name", "kepler_name"}

# Recognized so they can be safely ignored -- these are the prediction target
# and non-numeric flag/delivery metadata dropped by the verified training
# code's `drop_cols` (koi_disposition/koi_pdisposition are the target;
# fpflag_*/koi_tce_delivname are matched by its 'fpflag' filter or are
# non-numeric). koi_score and koi_tce_plnt_num are NOT excluded here --
# the verified drop logic keeps both; they are genuine model features.
TARGET_AND_SCORE_COLUMNS = {
    "koi_disposition", "koi_pdisposition",
    "koi_fpflag_nt", "koi_fpflag_ss", "koi_fpflag_co", "koi_fpflag_ec",
    "koi_tce_delivname",
}

_EXCLUDED_COLUMNS = ID_METADATA_COLUMNS | TARGET_AND_SCORE_COLUMNS


def normalize_key(name: str) -> str:
    """Case-insensitive, space/hyphen-tolerant normalization."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _build_alias_map() -> dict[str, str]:
    alias_to_canonical: dict[str, str] = {}

    def register(canonical: str, aliases: list[str]) -> None:
        alias_to_canonical[normalize_key(canonical)] = canonical
        for alias in aliases:
            alias_to_canonical[normalize_key(alias)] = canonical

    for canonical, aliases in BASE_ALIASES.items():
        register(canonical, aliases)

    for base in _ERR_VARIANT_BASES:
        base_aliases = BASE_ALIASES.get(base, [])
        for suffix in ("err1", "err2"):
            canonical_err = f"{base}_{suffix}"
            err_aliases = [f"{alias}_{suffix}" for alias in base_aliases]
            register(canonical_err, err_aliases)

    for excluded_col in _EXCLUDED_COLUMNS:
        register(excluded_col, [])

    return alias_to_canonical


ALIAS_TO_CANONICAL: dict[str, str] = _build_alias_map()


class MissingFeatureError(Exception):
    """Raised when a required model feature has no matching field in the
    input, under any of its recognized aliases."""

    def __init__(self, canonical_name: str) -> None:
        aliases = BASE_ALIASES.get(canonical_name)
        if aliases:
            message = (
                f"Missing required feature: {canonical_name}. "
                f"Accepted aliases: {', '.join(aliases)}."
            )
        else:
            message = f"Missing required feature: {canonical_name}."
        super().__init__(message)
        self.canonical_name = canonical_name


class InvalidFeatureValueError(Exception):
    """Raised when a recognized field's value isn't a finite number."""


class FeatureOrderNotConfiguredError(Exception):
    """Raised when extraction is attempted before MODEL_FEATURE_ORDER is set.
    This is deliberate -- see the module docstring. It is not a bug to be
    silently worked around by guessing a feature list."""

    def __init__(self) -> None:
        super().__init__(
            "The model's real feature order has not been configured "
            "(app.feature_aliases.MODEL_FEATURE_ORDER is unset). It cannot "
            "be recovered from the model artifact or from any code in this "
            "repository -- it must be supplied from the original training "
            "code, or confirmed by whoever trained the model, before named "
            "input can be mapped to the model's feature vector."
        )


def resolve_canonical_fields(raw_input: dict) -> dict[str, float]:
    """Normalizes every input key to its canonical KOI column name (if
    recognized) and drops target/ID/metadata columns, so they can never
    become model inputs even if present in the payload. Unrecognized keys
    are ignored, not rejected, since callers may send extra fields."""
    resolved: dict[str, float] = {}
    for raw_key, value in raw_input.items():
        normalized = normalize_key(str(raw_key))
        canonical = ALIAS_TO_CANONICAL.get(normalized)
        if canonical is None or canonical in _EXCLUDED_COLUMNS:
            continue
        resolved[canonical] = value
    return resolved


def extract_feature_vector(raw_input: dict, feature_order: list[str] | None = None) -> list[float]:
    """Normalizes `raw_input`'s keys via aliasing, then returns the feature
    values in exactly `feature_order` (defaults to MODEL_FEATURE_ORDER).
    Raises MissingFeatureError for any required feature with no match, and
    InvalidFeatureValueError for any non-finite/non-numeric value. Never
    fills a missing value with a default -- every value returned came from
    the caller's own input."""
    order = feature_order if feature_order is not None else MODEL_FEATURE_ORDER
    if order is None:
        raise FeatureOrderNotConfiguredError()

    resolved = resolve_canonical_fields(raw_input)
    values: list[float] = []
    for canonical in order:
        if canonical not in resolved:
            raise MissingFeatureError(canonical)
        raw_value = resolved[canonical]
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise InvalidFeatureValueError(
                f"{canonical} must be numeric (got {raw_value!r})."
            ) from None
        if not math.isfinite(value):
            raise InvalidFeatureValueError(
                f"{canonical} must be a finite number (got {value})."
            )
        values.append(value)
    return values


def looks_like_light_curve_header(header: list[str]) -> bool:
    """True if the header is a (time, flux) light curve -- 'brightness' is
    accepted as an alias for 'flux'. Only column presence is checked here;
    there is no observation-baseline or duration requirement."""
    normalized = {normalize_key(h) for h in header}
    return "time" in normalized and ("flux" in normalized or "brightness" in normalized)


_MIN_TABULAR_COLUMN_MATCHES = 2


def looks_like_tabular_kepler_header(header: list[str]) -> bool:
    """True if the header contains at least two recognized Kepler tabular
    columns (by canonical name or alias) -- catalog/candidate rows, never a
    light curve. This is checked only after ruling out the light-curve case,
    since a tabular file never has literal 'time'/'flux' columns.

    Requires 2+ matches rather than 1 specifically because a few real KOI
    aliases are single, common short tokens (e.g. "b" for koi_impact, "t0"
    for koi_time0bk) that could otherwise false-positive on an unrelated
    file that merely happens to have a column with that name."""
    normalized = {normalize_key(h) for h in header}
    matches = sum(1 for h in normalized if h in ALIAS_TO_CANONICAL)
    return matches >= _MIN_TABULAR_COLUMN_MATCHES
