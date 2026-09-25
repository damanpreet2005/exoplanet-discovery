import numpy as np
import pytest
import torch

from app.model_loader import ModelBundle
from app.predictor import predict
from app.schemas import PredictionFeatures
from tests.conftest import VALID_FEATURES


class StubRF:
    def __init__(self, prob_class1: float) -> None:
        self._prob = prob_class1

    def predict_proba(self, X):
        return np.array([[1 - self._prob, self._prob]])


class StubScaler:
    def transform(self, X):
        return X


class StubCNN:
    def __init__(self, logit0: float, logit1: float) -> None:
        self._logits = torch.tensor([[logit0, logit1]], dtype=torch.float32)

    def __call__(self, x):
        return self._logits

    def eval(self):
        return self


@pytest.mark.asyncio
async def test_weighted_fusion_math_is_correct():
    # RF says P(class1)=0.8, CNN logits chosen so softmax P(class1)=0.2
    bundle = ModelBundle(StubRF(0.8), StubScaler(), StubCNN(logit0=1.386294, logit1=0.0))
    features = PredictionFeatures(**VALID_FEATURES)

    response, duration = await predict(
        bundle, features, rf_weight=0.4, cnn_weight=0.6, model_version="test"
    )

    assert response.random_forest_probability == pytest.approx(0.8, abs=1e-3)
    assert response.cnn_probability == pytest.approx(0.2, abs=1e-3)
    expected_weighted = 0.4 * 0.8 + 0.6 * 0.2
    assert response.weighted_probability == pytest.approx(expected_weighted, abs=1e-3)
    assert response.prediction == int(expected_weighted >= 0.5)
    assert duration >= 0


@pytest.mark.asyncio
async def test_prediction_threshold_boundary():
    bundle = ModelBundle(StubRF(0.9), StubScaler(), StubCNN(logit0=100.0, logit1=-100.0))
    features = PredictionFeatures(**VALID_FEATURES)
    response, _ = await predict(bundle, features, rf_weight=0.5, cnn_weight=0.5, model_version="t")
    assert response.cnn_probability < 0.01
    assert response.weighted_probability < 0.5
    assert response.prediction == 0
