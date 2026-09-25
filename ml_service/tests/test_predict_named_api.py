"""
API-level tests for POST /predict, now that MODEL_FEATURE_ORDER holds the
verified real 17 features (see app/feature_aliases.py module docstring for
how that was independently verified against the real cumulative.csv).
"""

REAL_NAMED_PAYLOAD = {
    "score": 1.0,
    "orbital_period": 9.488035570,
    "transit_epoch": 170.5387500,
    "impact": 0.1460,
    "transit_duration": 2.95750,
    "depth": 615.8,
    "planet_radius": 2.26,
    "temperature": 793.0,
    "insolation": 93.59,
    "snr": 35.80,
    "tce_planet_number": 1,
    "teff": 5455.00,
    "logg": 4.467,
    "stellar_radius": 0.9270,
    "right_ascension": 291.934230,
    "declination": 48.141651,
    "kepmag": 15.347,
}


def test_valid_named_parameters_reach_a_real_prediction(client):
    resp = client.post("/predict", json=REAL_NAMED_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["prediction"] in (0, 1)
    assert 0.0 <= body["weighted_probability"] <= 1.0
    assert 0.0 <= body["random_forest_probability"] <= 1.0
    assert 0.0 <= body["cnn_probability"] <= 1.0


def test_canonical_names_work_identically_to_aliases(client):
    canonical_payload = {
        "koi_score": 1.0, "koi_period": 9.488035570, "koi_time0bk": 170.5387500,
        "koi_impact": 0.1460, "koi_duration": 2.95750, "koi_depth": 615.8,
        "koi_prad": 2.26, "koi_teq": 793.0, "koi_insol": 93.59, "koi_model_snr": 35.80,
        "koi_tce_plnt_num": 1, "koi_steff": 5455.00, "koi_slogg": 4.467,
        "koi_srad": 0.9270, "ra": 291.934230, "dec": 48.141651, "koi_kepmag": 15.347,
    }
    resp_canonical = client.post("/predict", json=canonical_payload)
    resp_alias = client.post("/predict", json=REAL_NAMED_PAYLOAD)
    assert resp_canonical.status_code == 200
    assert resp_alias.status_code == 200
    assert resp_canonical.json()["weighted_probability"] == resp_alias.json()["weighted_probability"]


def test_missing_one_of_the_real_17_features_returns_422_with_its_aliases(client):
    incomplete = dict(REAL_NAMED_PAYLOAD)
    del incomplete["orbital_period"]  # koi_period
    resp = client.post("/predict", json=incomplete)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_FEATURE"
    message = resp.json()["error"]["message"]
    assert "koi_period" in message
    assert "orbital_period" in message


def test_target_column_is_never_used_as_a_feature_even_if_provided(client):
    payload = dict(REAL_NAMED_PAYLOAD)
    payload["koi_disposition"] = "CONFIRMED"  # must be ignored, not treated as a feature
    del payload["orbital_period"]  # still genuinely missing a real feature
    resp = client.post("/predict", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_FEATURE"
    assert "koi_period" in resp.json()["error"]["message"]


def test_non_numeric_value_returns_422(client):
    payload = dict(REAL_NAMED_PAYLOAD)
    payload["orbital_period"] = "not_a_number"
    resp = client.post("/predict", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_FEATURE_VALUE"
