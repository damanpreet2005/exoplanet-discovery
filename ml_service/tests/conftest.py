import os
import sys
from pathlib import Path

# Tests never reach the NASA Exoplanet Archive; characterization enrichment is
# exercised with injected lookup results instead.
os.environ.setdefault("CHARACTERIZATION_ARCHIVE_LOOKUP", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


VALID_FEATURES = {
    "feature_1": 0.334, "feature_2": 9.75, "feature_3": 137.2, "feature_4": 0.537,
    "feature_5": 3.79, "feature_6": 421.1, "feature_7": 2.39, "feature_8": 878,
    "feature_9": 141.6, "feature_10": 23, "feature_11": 1.0, "feature_12": 5767,
    "feature_13": 4.438, "feature_14": 1.0, "feature_15": 292.26, "feature_16": 43.68,
    "feature_17": 14.52,
}
