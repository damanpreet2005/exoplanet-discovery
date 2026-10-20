"""
Stage 2: Physics Validation endpoint.

Accepts the same named/aliased KOI-style JSON body as POST /predict (see
app/feature_aliases.py), but -- unlike /predict -- never requires all 17
fields to be present. Physics validation only needs a subset (koi_period,
koi_impact, koi_duration, koi_depth, koi_prad, koi_srad, koi_slogg) and is
designed to report NOT_EVALUATED for whatever is missing rather than reject
the whole request, since "some tests could not be evaluated" is itself a
meaningful, honestly-reported result (see app/physics_validation.py).

This endpoint never calls the trained Random Forest / CNN ensemble and never
mixes its own PASS/REVIEW_REQUIRED/NOT_EVALUATED statuses with the model's
prediction probability.
"""
from fastapi import APIRouter, Request

from app.feature_aliases import resolve_canonical_fields
from app.physics_validation import run_physics_validation

router = APIRouter(tags=["physics-validation"])

_PHYSICS_FIELDS = (
    "koi_period", "koi_impact", "koi_duration", "koi_depth",
    "koi_prad", "koi_srad", "koi_steff", "koi_slogg",
)


def _to_float_or_none(raw_value) -> float | None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None  # NaN/inf guard


@router.post("/physics-validation")
async def physics_validation_endpoint(payload: dict, request: Request) -> dict:
    request_id = request.headers.get("x-request-id", "unknown")

    raw_object_id = payload.get("object_id")
    object_id = raw_object_id.strip() if isinstance(raw_object_id, str) and raw_object_id.strip() else None

    resolved = resolve_canonical_fields(payload)
    features = {name: _to_float_or_none(resolved.get(name)) for name in _PHYSICS_FIELDS}

    report = run_physics_validation(features, object_id=object_id)
    body = report.to_dict()
    body["request_id"] = request_id
    return body
