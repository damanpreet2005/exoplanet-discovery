"""
Preprocessing for inference requests.

Scaling is performed using the exact, already-fitted RobustScaler stored in
the model artifact (`.transform()` only -- it is never re-fit). This is the
same scaler object the Random Forest and CNN were trained downstream of, so
using it here reproduces the original preprocessing pipeline rather than
approximating it.
"""
import numpy as np

from app.model_loader import ModelBundle
from app.schemas import N_FEATURES, PredictionFeatures


def scale_features(bundle: ModelBundle, features: PredictionFeatures) -> np.ndarray:
    raw = np.asarray(features.as_ordered_list(), dtype=np.float64).reshape(1, N_FEATURES)
    scaled = bundle.scaler.transform(raw)
    return scaled
