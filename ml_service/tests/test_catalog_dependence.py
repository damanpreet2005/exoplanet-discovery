"""
The trained ensemble's dependence on koi_score (NASA's Robovetter disposition
score from the KOI catalogue), and the separation between light-curve
evidence and catalogue-informed classification.
"""
import math

import numpy as np
import csv
import pytest

from app.feature_aliases import MODEL_FEATURE_ORDER
from app.feature_engine import extract_features
from app.model_loader import ModelRegistry
from app.predictor import _catalog_dependence, _run_inference_sync
from app.schemas import PredictionFeatures
from app.stellar_catalog_service import resolve_object_id

KEPLER_227B = {"koi_score": 1.0, "koi_period": 9.488036, "koi_time0bk": 170.53875, "koi_impact": 0.146,
               "koi_duration": 2.9575, "koi_depth": 615.8, "koi_prad": 2.26, "koi_teq": 793.0, "koi_insol": 93.59,
               "koi_model_snr": 35.8, "koi_tce_plnt_num": 1, "koi_steff": 5455.0, "koi_slogg": 4.467,
               "koi_srad": 0.927, "ra": 286.0, "dec": 48.0, "koi_kepmag": 15.6}


@pytest.fixture(scope="module")
def bundle():
    from app.config import get_settings
    reg = ModelRegistry(get_settings().model_path)
    reg.load()
    return reg.bundle


def features(values):
    return PredictionFeatures(**dict(zip(PredictionFeatures.model_fields, [values[c] for c in MODEL_FEATURE_ORDER])))


def test_koi_score_nearly_determines_the_catalogue_disposition():
    """Backs the UI statement that koi_score alone matches NASA's disposition for ~98% of KOIs."""
    with open("data/koi_catalog.csv") as fh:
        rows = [r for r in csv.DictReader(line for line in fh if not line.startswith("#")) if r["koi_score"]]
    agree = np.mean([(float(r["koi_score"]) >= 0.5) == (r["koi_disposition"] in ("CONFIRMED", "CANDIDATE"))
                     for r in rows])
    assert 0.97 < agree < 0.99


def test_koi_score_dominates_the_random_forest(bundle):
    imp = bundle.random_forest.feature_importances_
    i = MODEL_FEATURE_ORDER.index("koi_score")
    assert imp[i] == max(imp) and imp[i] > 0.5


def test_prediction_reports_its_dependence_on_koi_score(bundle):
    dep = _catalog_dependence(bundle, features(KEPLER_227B), 0.5, 0.5)
    full = _run_inference_sync(bundle, features(KEPLER_227B), 0.5, 0.5).weighted_probability
    assert dep.value == 1.0
    assert dep.neutral_value == pytest.approx(float(bundle.scaler.center_[MODEL_FEATURE_ORDER.index("koi_score")]))
    assert dep.rf_importance > 0.5
    assert dep.weighted_probability_with_neutral_value < full
    # Only koi_score is changed for the sensitivity check.
    same = _run_inference_sync(bundle, features({**KEPLER_227B, "koi_score": dep.neutral_value}), 0.5, 0.5)
    assert same.weighted_probability == pytest.approx(dep.weighted_probability_with_neutral_value)


def test_noise_under_a_confirmed_planets_id_is_classified_by_the_catalogue(bundle):
    """Documents the limitation: pure noise uploaded with Kepler-227 b's Object
    ID gets a class-1 probability from the catalogue's koi_score, while the
    light curve itself shows no significant transit."""
    t = np.arange(130.0, 230.0, 0.0204)
    f = 1.0 + np.random.default_rng(6).normal(0.0, 150e-6, t.size)
    res = extract_features(t, f, "K00752.01")
    vals = {c: fv.value for c, fv in res.features.items()}
    assert vals["koi_model_snr"] < 7.1                      # no significant transit in the light curve
    assert res.features["koi_score"].status == "catalog"
    p = _run_inference_sync(bundle, features(vals), 0.5, 0.5).weighted_probability
    dep = _catalog_dependence(bundle, features(vals), 0.5, 0.5)
    assert p > 0.5                                           # catalogue-informed class 1
    assert dep.weighted_probability_with_neutral_value < 0.5  # without koi_score it is not


def test_api_response_carries_the_dependence(client):
    body = client.post("/predict", json=KEPLER_227B).json()
    dep = body["catalog_dependence"]
    assert dep["feature"] == "koi_score" and dep["value"] == 1.0
    assert 0 <= dep["weighted_probability_with_neutral_value"] <= 1
