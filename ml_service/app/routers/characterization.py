"""
Planet characterization recomputation endpoint.

The full characterization (including the transit-model fit) runs once as
part of POST /predict/csv. This endpoint re-runs only the cheap engine stage
on the report's stored `inputs` snapshot, with expert overrides and/or
changed assumptions (Bond albedo, heat redistribution) -- no light-curve
refit, so it is safe on the synchronous request path. Results are cached by
a content hash of (inputs, overrides, config): any change to those produces
a new key, so a stale report is never served.
"""
import asyncio
import logging

from fastapi import APIRouter, Request

from app.characterization import (
    CharacterizationInputError,
    OverrideValidationError,
    inputs_cache_key,
    recompute_characterization,
)
from app.characterization.engine import overrides_from_model_features
from app.errors import CharacterizationRequestError

router = APIRouter(tags=["characterization"])
logger = logging.getLogger("ml_service")


@router.post("/characterization/recompute")
async def recompute_endpoint(payload: dict, request: Request) -> dict:
    """Body: {"inputs": <report.inputs>, "overrides": {name: value | {value, uncertainty | err_plus, err_minus}},
    "model_feature_edits": {"submitted": {...17 KOI-named values}, "automatic": {...}}, "config": {...}}.
    `model_feature_edits` converts edits made in the existing 17-parameter Expert Override form into
    characterization overrides (only fields that actually changed); explicit `overrides` take precedence."""
    request_id = request.headers.get("x-request-id", "unknown")
    inputs = payload.get("inputs")
    overrides = payload.get("overrides") or {}
    config = payload.get("config") or {}
    edits = payload.get("model_feature_edits")
    if not isinstance(overrides, dict) or not isinstance(config, dict):
        raise CharacterizationRequestError("'overrides' and 'config' must be JSON objects.")
    if isinstance(edits, dict):
        submitted, automatic = edits.get("submitted") or {}, edits.get("automatic") or {}
        if not isinstance(submitted, dict) or not isinstance(automatic, dict):
            raise CharacterizationRequestError("'model_feature_edits.submitted' and '.automatic' must be objects.")
        overrides = {**overrides_from_model_features(submitted, automatic), **overrides}

    cache = request.app.state.cache
    key = inputs_cache_key(inputs, overrides, config)
    cached = cache.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True, "request_id": request_id}
    try:
        report = await asyncio.to_thread(recompute_characterization, inputs, overrides, config)
    except (OverrideValidationError, CharacterizationInputError) as exc:
        raise CharacterizationRequestError(str(exc)) from exc
    cache.set(key, report)
    logger.info("characterization_recomputed", extra={"request_id": request_id, "n_overrides": len(overrides)})
    return {**report, "cache_hit": False, "request_id": request_id}
