"""
Runs Random Forest inference, CNN inference, and weighted-probability fusion
against the existing, unmodified trained artifacts.

Both models are treated as binary classifiers over classes {0, 1} (verified
from `random_forest.classes_ == [0, 1]` and the CNN's final Linear(64, 2)
layer). "Probability" below means P(class == 1) from each model.
"""
import asyncio
import time

import numpy as np
import torch

from app.cache import Cache, make_cache_key
from app.model_loader import ModelBundle
from app.preprocessing import scale_features
from app.feature_aliases import MODEL_FEATURE_ORDER
from app.schemas import CatalogDependence, FusionWeights, PredictionFeatures, PredictionResponse

KOI_SCORE_INDEX = MODEL_FEATURE_ORDER.index("koi_score")


class FusionResult:
    def __init__(self, prediction: int, weighted_probability: float,
                 rf_probability: float, cnn_probability: float) -> None:
        self.prediction = prediction
        self.weighted_probability = weighted_probability
        self.rf_probability = rf_probability
        self.cnn_probability = cnn_probability


def _run_inference_sync(bundle: ModelBundle, features: PredictionFeatures,
                         rf_weight: float, cnn_weight: float) -> FusionResult:
    scaled = scale_features(bundle, features)

    rf_proba = bundle.random_forest.predict_proba(scaled)[0]
    rf_prob_class1 = float(rf_proba[1])

    # Matches the confirmed reference `predict_user_input`: edge-pad the
    # scaled feature vector out to 64 values, then reshape into an 8x8 grid.
    pad_width = 64 - scaled.shape[1]
    padded_data = np.pad(scaled, ((0, 0), (0, pad_width)), mode="edge")

    with torch.no_grad():
        tensor_input = torch.tensor(padded_data.reshape(-1, 1, 8, 8), dtype=torch.float32)
        logits = bundle.cnn(tensor_input)
        cnn_proba = torch.softmax(logits, dim=1)[0]
        cnn_prob_class1 = float(cnn_proba[1].item())

    weighted_probability = rf_weight * rf_prob_class1 + cnn_weight * cnn_prob_class1
    prediction = int(weighted_probability >= 0.5)

    return FusionResult(
        prediction=prediction,
        weighted_probability=weighted_probability,
        rf_probability=rf_prob_class1,
        cnn_probability=cnn_prob_class1,
    )


async def predict(bundle: ModelBundle, features: PredictionFeatures,
                   rf_weight: float, cnn_weight: float,
                   model_version: str) -> tuple[PredictionResponse, float]:
    """Runs inference off the event loop (it is CPU-bound) and returns the
    structured response plus the wall-clock inference duration in seconds."""
    start = time.perf_counter()
    result = await asyncio.to_thread(
        _run_inference_sync, bundle, features, rf_weight, cnn_weight
    )
    duration = time.perf_counter() - start
    dependence = await asyncio.to_thread(_catalog_dependence, bundle, features, rf_weight, cnn_weight)

    response = PredictionResponse(
        prediction=result.prediction,
        weighted_probability=result.weighted_probability,
        random_forest_probability=result.rf_probability,
        cnn_probability=result.cnn_probability,
        weights=FusionWeights(random_forest=rf_weight, cnn=cnn_weight),
        model_version=model_version,
        catalog_dependence=dependence,
    )
    return response, duration


def _catalog_dependence(bundle: ModelBundle, features: PredictionFeatures,
                        rf_weight: float, cnn_weight: float) -> CatalogDependence | None:
    """Re-evaluates the same inputs with koi_score set to its training median,
    so the response can show how much the probability depends on it."""
    names = list(PredictionFeatures.model_fields)
    try:
        neutral = float(bundle.scaler.center_[KOI_SCORE_INDEX])
        importance = float(bundle.random_forest.feature_importances_[KOI_SCORE_INDEX])
    except (AttributeError, IndexError):
        return None
    values = features.model_dump()
    original = float(values[names[KOI_SCORE_INDEX]])
    values[names[KOI_SCORE_INDEX]] = neutral
    alt = _run_inference_sync(bundle, PredictionFeatures(**values), rf_weight, cnn_weight)
    return CatalogDependence(value=original, rf_importance=importance, neutral_value=neutral,
                             weighted_probability_with_neutral_value=alt.weighted_probability)


async def predict_with_cache(bundle: ModelBundle, cache: Cache, features: PredictionFeatures,
                              rf_weight: float, cnn_weight: float,
                              model_version: str) -> tuple[PredictionResponse, bool, float]:
    """Shared cache-then-infer path used by both the single-row JSON endpoint
    and the CSV batch endpoint, so both stay behind the same cache/inference
    behavior instead of duplicating it."""
    start = time.perf_counter()
    cache_key = make_cache_key(features)
    cached = cache.get(cache_key)
    if cached is not None:
        response = PredictionResponse(**cached, cache_hit=True)
        return response, True, (time.perf_counter() - start)

    response, _ = await predict(bundle, features, rf_weight, cnn_weight, model_version)
    cache.set(cache_key, response.model_dump(exclude={"request_id", "cache_hit"}))
    return response, False, (time.perf_counter() - start)
