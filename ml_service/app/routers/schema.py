"""Exposes the feature display metadata (canonical name, human-readable
label, unit, aliases) so the frontend can render the manual-parameter form
from a single source of truth instead of duplicating names."""
from fastapi import APIRouter

from app.feature_aliases import FEATURE_DEFINITIONS, MODEL_FEATURE_ORDER

router = APIRouter(tags=["schema"])


@router.get("/feature-schema")
async def feature_schema() -> dict:
    return {
        "features": FEATURE_DEFINITIONS,
        "order_configured": MODEL_FEATURE_ORDER is not None,
    }
