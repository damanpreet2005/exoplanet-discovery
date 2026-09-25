"""
Loads the existing, immutable model artifact exactly once at process startup.

The artifact is never modified, retrained, or replaced by this code -- it is
opened read-only via joblib.load and its three components (random_forest,
scaler, cnn_state_dict) are handed to the CNN reconstruction and predictor
modules as-is.
"""
import logging
import threading

import joblib

from app.cnn_model import load_cnn

logger = logging.getLogger("ml_service")


class ModelBundle:
    def __init__(self, random_forest, scaler, cnn) -> None:
        self.random_forest = random_forest
        self.scaler = scaler
        self.cnn = cnn


class ModelRegistry:
    """Holds the singleton, lazily-loaded model bundle for the process lifetime."""

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._bundle: ModelBundle | None = None
        self._load_error: str | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._bundle is not None:
                return
            try:
                raw = joblib.load(self._model_path)
                random_forest = raw["random_forest"]
                scaler = raw["scaler"]
                cnn = load_cnn(raw["cnn_state_dict"])
                self._bundle = ModelBundle(random_forest, scaler, cnn)
                logger.info("model_loaded", extra={"model_path": self._model_path})
            except Exception as exc:  # noqa: BLE001
                self._load_error = str(exc)
                logger.exception("model_load_failed")
                raise

    @property
    def is_ready(self) -> bool:
        return self._bundle is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def bundle(self) -> ModelBundle:
        if self._bundle is None:
            raise RuntimeError("Model is not loaded yet")
        return self._bundle
