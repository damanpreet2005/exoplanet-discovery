import math

from tests.conftest import VALID_FEATURES


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_ready(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_valid_prediction(client):
    resp = client.post("/predict/raw", json={"features": VALID_FEATURES})
    assert resp.status_code == 200
    body = resp.json()
    assert body["prediction"] in (0, 1)
    assert 0.0 <= body["weighted_probability"] <= 1.0
    assert 0.0 <= body["random_forest_probability"] <= 1.0
    assert 0.0 <= body["cnn_probability"] <= 1.0
    assert math.isclose(
        body["weighted_probability"],
        body["weights"]["random_forest"] * body["random_forest_probability"]
        + body["weights"]["cnn"] * body["cnn_probability"],
        rel_tol=1e-6,
    )


def test_cache_hit_on_repeated_input(client):
    unique_features = dict(VALID_FEATURES)
    unique_features["feature_17"] = 99.999  # avoid collision with other tests' cache entries
    resp1 = client.post("/predict/raw", json={"features": unique_features})
    resp2 = client.post("/predict/raw", json={"features": unique_features})
    assert resp1.json()["cache_hit"] is False
    assert resp2.json()["cache_hit"] is True
    assert resp1.json()["weighted_probability"] == resp2.json()["weighted_probability"]


def test_missing_feature_returns_422(client):
    incomplete = dict(VALID_FEATURES)
    del incomplete["feature_5"]
    resp = client.post("/predict/raw", json={"features": incomplete})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_wrong_type_returns_422(client):
    bad = dict(VALID_FEATURES)
    bad["feature_1"] = "not_a_number"
    resp = client.post("/predict/raw", json={"features": bad})
    assert resp.status_code == 422


def test_extra_feature_returns_422(client):
    extra = dict(VALID_FEATURES)
    extra["feature_18"] = 1.0
    resp = client.post("/predict/raw", json={"features": extra})
    assert resp.status_code == 422


def test_nan_value_returns_422(client):
    import json as jsonlib
    bad = dict(VALID_FEATURES)
    bad["feature_1"] = float("nan")
    raw = jsonlib.dumps({"features": bad}, allow_nan=True)
    resp = client.post("/predict/raw", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422


def test_infinite_value_returns_422(client):
    import json as jsonlib
    bad = dict(VALID_FEATURES)
    bad["feature_1"] = float("inf")
    raw = jsonlib.dumps({"features": bad}, allow_nan=True)
    resp = client.post("/predict/raw", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422


def test_null_value_returns_422(client):
    bad = dict(VALID_FEATURES)
    bad["feature_1"] = None
    resp = client.post("/predict/raw", json={"features": bad})
    assert resp.status_code == 422


def test_unknown_route_returns_404(client):
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_request_id_propagates(client):
    resp = client.post(
        "/predict/raw", json={"features": VALID_FEATURES}, headers={"X-Request-Id": "abc-123"}
    )
    assert resp.json()["request_id"] == "abc-123"
    assert resp.headers["x-request-id"] == "abc-123"
