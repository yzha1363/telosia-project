"""Injury-frequency tier endpoint - the one place that shows how the
exposure -> injury model actually gets used end to end.

This file exists on its own, separate from occupations.py, specifically
so the whole "how does the injury-risk model work" story can be pointed
to as one place: fetch an occupation's published BOHD exposure scores ->
hand them to the trained model (app/services/injury_model.py) -> return
its tier, honestly, with a null + message when there's nothing to show.

The model itself - what it predicts, how it was trained, why only a
tier is ever exposed and never a raw predicted number - is documented in
model/README.md and model/artifacts/metrics.json, not repeated here.
This file is the wiring: occupation -> exposures -> model -> response.

Destinations (app/routes/occupations.py) also shows a tier per
destination, reusing the exact same model through the exact same
score_occupations() function - see that file's _attach_tiers for the
few lines that do it there. This endpoint is the clearest single
example of the whole path, not the only place it's used.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.routes.occupations import _fetch_exposures, _get_occupation_or_404
from app.schemas.occupation import InjuryInsightResponse
from app.services.injury_model import score_occupations
from database.connection import get_db

router = APIRouter(
    prefix="/occupations",
    tags=["Occupations"],
)

# The trained model's absolute predictions aren't reliable enough to show
# a number (test R^2 is negative on held-out data - see
# model/train_exposure_model.py and model/artifacts/metrics.json). Its
# RANKING of occupations is meaningfully better (test Spearman 0.77, 81%
# pairwise direction accuracy), so only the tercile a prediction falls
# into ("Higher/About/Lower than typical") is ever exposed here - never
# the predicted rate itself.
_NO_INSIGHT_MESSAGE = "We don't have a model estimate for this occupation yet."


@router.get("/{occupation_id}/injury-insight", response_model=InjuryInsightResponse)
def get_injury_insight(
    occupation_id: int = Path(..., description="Occupation ID."),
    db: Session = Depends(get_db),
):
    """Return the direction-only injury-frequency signal for an occupation.

    This is a research model's output, not a published statistic - see
    model/README.md and model/artifacts/metrics.json for the full
    caveats (cross-sectional association, not causal, not a forecast,
    not production-approved). Only the ranking tier is returned; a
    specific predicted number is never published because the model's
    absolute predictions failed validation (negative test R^2).

    Scored in-process on every call (app/services/injury_model.py) - no
    separate service, no network call, nothing precomputed to go stale.
    A missing/corrupt model artifact degrades to every request returning
    the same honest "no estimate" response below, not an error - see
    injury_model.py's _load() for why.

    Args:
        occupation_id: The occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: The tier and the model that produced it, or a null
        insight with an honest message if this occupation has no BOHD
        exposure coverage (roughly 83 of 401 loaded occupations) or the
        model failed to load.

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    occupation = _get_occupation_or_404(db, occupation_id)

    exposures = _fetch_exposures(db, [occupation_id])
    result = score_occupations(exposures)
    tier = result.tiers.get(occupation_id)

    if tier is None:
        return {
            "occupation_id": occupation_id,
            "title": occupation["occupation_title"],
            "insight": None,
            "message": _NO_INSIGHT_MESSAGE,
        }

    return {
        "occupation_id": occupation_id,
        "title": occupation["occupation_title"],
        "insight": {
            "tier": tier,
            "model_name": result.model_name,
            "model_version": result.model_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
