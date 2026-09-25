"""
CSV parsing for the TABULAR Kepler dataset path (catalog/candidate rows --
NOT a light curve). This module only turns CSV bytes into row dictionaries;
it does not interpret any column as a time axis, does not compute an
observation baseline, and does not run any light-curve validation. Column
name normalization and feature extraction/ordering are handled by
app/feature_aliases.py; prediction is handled by the existing, unmodified
app/predictor.py.
"""
import csv
import io

MAX_TABULAR_ROWS = 20000


class TabularValidationError(Exception):
    """Raised for file-level problems with a tabular CSV (empty file, no
    header, no data rows, too many rows)."""


def parse_tabular_csv(raw_bytes: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not raw_bytes.strip():
        raise TabularValidationError("The uploaded CSV file is empty.")

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TabularValidationError("The uploaded file is not valid UTF-8 text.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise TabularValidationError("The uploaded CSV file has no header row.")

    rows = list(reader)
    if len(rows) == 0:
        raise TabularValidationError("The uploaded CSV file has a header but no data rows.")
    if len(rows) > MAX_TABULAR_ROWS:
        raise TabularValidationError(
            f"The uploaded CSV has {len(rows)} data rows, which exceeds the "
            f"maximum of {MAX_TABULAR_ROWS} rows per upload."
        )

    return list(reader.fieldnames), rows
