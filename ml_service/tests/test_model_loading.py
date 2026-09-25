from app.config import get_settings
from app.model_loader import ModelRegistry


def test_model_loads_from_existing_pkl_without_modifying_it():
    settings = get_settings()
    import os
    before_mtime = os.path.getmtime(settings.model_path)

    registry = ModelRegistry(settings.model_path)
    registry.load()

    after_mtime = os.path.getmtime(settings.model_path)
    assert before_mtime == after_mtime, "model file must never be modified"

    assert registry.is_ready
    bundle = registry.bundle
    assert bundle.random_forest.n_features_in_ == 17
    assert list(bundle.random_forest.classes_) == [0, 1]
    assert bundle.scaler.n_features_in_ == 17
    assert bundle.cnn is not None


def test_registry_not_ready_before_load():
    registry = ModelRegistry("/tmp/does_not_exist.pkl")
    assert registry.is_ready is False


def test_registry_raises_on_missing_file():
    import pytest
    registry = ModelRegistry("/tmp/does_not_exist.pkl")
    with pytest.raises(Exception):
        registry.load()
    assert registry.is_ready is False
