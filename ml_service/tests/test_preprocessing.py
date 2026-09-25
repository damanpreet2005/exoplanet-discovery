import numpy as np

from app.config import get_settings
from app.model_loader import ModelRegistry
from app.preprocessing import scale_features
from app.schemas import PredictionFeatures
from tests.conftest import VALID_FEATURES


def test_scale_features_matches_scaler_transform_directly():
    settings = get_settings()
    registry = ModelRegistry(settings.model_path)
    registry.load()
    bundle = registry.bundle

    features = PredictionFeatures(**VALID_FEATURES)
    scaled = scale_features(bundle, features)

    raw = np.array([features.as_ordered_list()])
    expected = bundle.scaler.transform(raw)

    assert np.allclose(scaled, expected)
    assert scaled.shape == (1, 17)


def test_scale_features_uses_robust_scaler_formula():
    settings = get_settings()
    registry = ModelRegistry(settings.model_path)
    registry.load()
    bundle = registry.bundle

    features = PredictionFeatures(**VALID_FEATURES)
    scaled = scale_features(bundle, features)

    manual = (np.array(features.as_ordered_list()) - bundle.scaler.center_) / bundle.scaler.scale_
    assert np.allclose(scaled[0], manual)
