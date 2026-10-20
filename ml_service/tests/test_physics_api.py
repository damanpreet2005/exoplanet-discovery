"""API-level tests for POST /physics-validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


EARTH_LIKE_NAMED = {
    "koi_period": 365.25,
    "koi_impact": 0.0,
    "koi_duration": 13.0,
    "koi_depth": 83.9,
    "koi_prad": 1.0,
    "koi_srad": 1.0,
    "koi_steff": 5772.0,
    "koi_slogg": 4.438,
}


def test_full_named_payload_returns_pass_overall(client):
    resp = client.post("/physics-validation", json=EARTH_LIKE_NAMED)
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "PASS"
    assert len(body["tests"]) == 3
    assert body["summary"]["tests_passed"] == 3
    assert body["request_id"] == "unknown"


def test_aliases_are_accepted_identically_to_canonical_names(client):
    aliased = {
        "orbital_period": 365.25,
        "impact": 0.0,
        "transit_duration": 13.0,
        "depth": 83.9,
        "planet_radius": 1.0,
        "stellar_radius": 1.0,
        "teff": 5772.0,
        "logg": 4.438,
    }
    resp_alias = client.post("/physics-validation", json=aliased)
    resp_canonical = client.post("/physics-validation", json=EARTH_LIKE_NAMED)
    assert resp_alias.status_code == 200
    assert resp_alias.json()["overall_status"] == resp_canonical.json()["overall_status"]


def test_missing_fields_return_200_with_not_evaluated_not_an_error(client):
    resp = client.post("/physics-validation", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "NOT_EVALUATED"
    assert body["summary"]["tests_not_evaluated"] == 3
    assert len(body["issues"]) == 3


def test_object_id_is_echoed_back(client):
    payload = dict(EARTH_LIKE_NAMED, object_id="  KIC 11904151  ")
    resp = client.post("/physics-validation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["object_id"] == "KIC 11904151"


def test_non_numeric_value_is_treated_as_unavailable_not_rejected(client):
    payload = dict(EARTH_LIKE_NAMED)
    payload["koi_depth"] = "not_a_number"
    resp = client.post("/physics-validation", json=payload)
    assert resp.status_code == 200
    planet_size = next(t for t in resp.json()["tests"] if t["test_id"] == "planet_size")
    assert planet_size["status"] == "NOT_EVALUATED"


def test_request_id_header_is_echoed(client):
    resp = client.post(
        "/physics-validation", json=EARTH_LIKE_NAMED, headers={"X-Request-Id": "trace-42"}
    )
    assert resp.status_code == 200
    assert resp.json()["request_id"] == "trace-42"
    assert resp.headers["x-request-id"] == "trace-42"


def test_does_not_require_model_to_be_loaded(client):
    """Physics validation is independent of the RF/CNN model registry --
    it must work even on a request that never touches app.state.model_registry."""
    resp = client.post("/physics-validation", json=EARTH_LIKE_NAMED)
    assert resp.status_code == 200
