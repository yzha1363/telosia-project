"""In-process scoring for the exposure -> injury-frequency model.

Loads the trained model (see model/README.md for how it was trained,
model/artifacts/metrics.json for its real evaluation numbers) once when
this module is first imported, and scores occupations' BOHD exposure
vectors into a tier - "Lower than typical" / "About typical" / "Higher
than typical" - in the same process as the rest of the API. No network
call, no separate service to deploy, no MODEL_SERVICE_URL to keep in
sync with a second deployment.

The model's raw predicted number is never exposed anywhere - only the
tier. Its held-out test R^2 is negative (see metrics.json's "test"
block), so the absolute predicted rate isn't trustworthy, but its
RANKING of occupations relative to each other is (test Spearman 0.77,
81% pairwise direction accuracy) - the tercile cutoffs in metrics.json
are exactly that ranking, bucketed into thirds.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import load as load_joblib

log = logging.getLogger(__name__)

_ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "model" / "artifacts"

_MODEL = None
_FEATURES: list[str] = []
_LOW_CUTOFF: float | None = None
_HIGH_CUTOFF: float | None = None
_MODEL_NAME = "exposure_injury_association"
_MODEL_VERSION: str | None = None


def _load() -> None:
    """Runs once, at import time. Deliberately broad except: this is one
    research signal among many the product already shows as an honest
    "no estimate available" when data is missing (see
    _NO_BODY_REGION_DATA_MESSAGE and friends in app/routes/occupations.py)
    - a missing or corrupt model artifact must degrade to that same
    case, not take down search/destinations/every other endpoint just
    because this module failed to import cleanly. That's not a
    theoretical concern: the first version of this integration imported
    a module that didn't exist yet and crashed the entire API at
    startup before this fallback existed.
    """
    global _MODEL, _FEATURES, _LOW_CUTOFF, _HIGH_CUTOFF, _MODEL_VERSION
    try:
        artifact = load_joblib(_ARTIFACT_DIR / "research_model.joblib")
        metrics = json.loads((_ARTIFACT_DIR / "metrics.json").read_text(encoding="utf-8"))
        _MODEL = artifact["model"]
        _FEATURES = artifact["features"]
        _LOW_CUTOFF = metrics["tier_thresholds"]["low_cutoff"]
        _HIGH_CUTOFF = metrics["tier_thresholds"]["high_cutoff"]
        _MODEL_VERSION = f"{metrics['selected']}-{date.today().isoformat()}"
    except Exception:
        log.warning(
            "Injury-frequency model failed to load from %s - "
            "tier will be unavailable for every occupation until this is fixed.",
            _ARTIFACT_DIR,
            exc_info=True,
        )


_load()


@dataclass
class ScoringResult:
    """model_name/model_version are None and tiers is empty when the
    model didn't load, or none of the requested occupations had any
    exposure data to score - callers already treat that identically to
    "no estimate available", the same honest missing-data case as an
    occupation with no BOHD coverage at all.
    """

    model_name: str | None = None
    model_version: str | None = None
    tiers: dict[int, str] = field(default_factory=dict)


def _tier(predicted_rate: float) -> str:
    if predicted_rate <= _LOW_CUTOFF:
        return "Lower than typical"
    if predicted_rate >= _HIGH_CUTOFF:
        return "Higher than typical"
    return "About typical"


def score_occupations(exposures_by_id: dict[int, dict[str, float]]) -> ScoringResult:
    """Score each occupation's injury-frequency tier from its BOHD
    exposure scores, in one batched prediction call.

    Occupations with an empty exposures dict are skipped, not scored -
    scoring a vector of pure imputation would just reproduce the
    training median for every such occupation, which is a fabricated
    result, not a real estimate (there is nothing to have imputed
    *around*). Any feature present in _FEATURES but missing from an
    occupation's exposures becomes NaN, filled by the model pipeline's
    own median imputer - the exact same handling training used for
    occupations with partial BOHD coverage.

    Args:
        exposures_by_id: Hazard-exposure scores per occupation, keyed
            by occupation_id (as returned by
            app.routes.occupations._fetch_exposures).

    Returns:
        ScoringResult with a tier per scoreable occupation. Occupations
        that were skipped (empty exposures) or that the model never
        loaded for simply have no key in .tiers - callers check with a
        plain dict lookup and treat a miss as "no estimate".
    """
    if _MODEL is None:
        return ScoringResult()

    scoreable = [
        (occupation_id, exposures)
        for occupation_id, exposures in exposures_by_id.items()
        if exposures
    ]
    if not scoreable:
        return ScoringResult()

    rows = pd.DataFrame(
        [{feature: exposures.get(feature) for feature in _FEATURES} for _, exposures in scoreable]
    )
    # np.maximum(0, ...) matches train_exposure_model.py's own clamp - the
    # tier_thresholds were computed against clamped predictions, so
    # inference must clamp the same way to land in the same terciles.
    raw = np.maximum(0, _MODEL.predict(rows[_FEATURES]))

    return ScoringResult(
        model_name=_MODEL_NAME,
        model_version=_MODEL_VERSION,
        tiers={
            occupation_id: _tier(rate)
            for (occupation_id, _), rate in zip(scoreable, raw)
        },
    )
