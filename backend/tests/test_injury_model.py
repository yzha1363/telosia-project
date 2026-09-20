"""Tests for the in-process injury-frequency scoring module.

Runs against the real bundled model/artifacts/research_model.joblib and
metrics.json - there's no mock model here, since the whole point of
these tests is confirming the actual deployed artifact scores correctly
through score_occupations(), the same function app/routes/occupations.py
calls on every request.
"""

from app.services import injury_model
from app.services.injury_model import ScoringResult, score_occupations


def test_model_loaded_at_import_time():
    assert injury_model._MODEL is not None
    assert len(injury_model._FEATURES) == 57


def test_full_feature_vector_returns_a_valid_tier():
    occupation = {134: {f: 50.0 for f in injury_model._FEATURES}}
    result = score_occupations(occupation)

    assert result.tiers[134] in (
        "Lower than typical", "About typical", "Higher than typical",
    )
    assert result.model_name == "exposure_injury_association"
    assert result.model_version is not None


def test_partial_feature_vector_still_scores():
    partial = {f: 50.0 for f in injury_model._FEATURES[:10]}
    result = score_occupations({2: partial})

    assert 2 in result.tiers


def test_empty_exposures_are_skipped_not_scored():
    result = score_occupations({3: {}})

    assert result.tiers == {}


def test_batches_multiple_occupations_in_one_call():
    occupations = {
        1: {f: 50.0 for f in injury_model._FEATURES},
        2: {},
        3: {f: 90.0 for f in injury_model._FEATURES},
    }
    result = score_occupations(occupations)

    assert set(result.tiers) == {1, 3}


def test_no_occupations_returns_empty_result():
    result = score_occupations({})

    assert result == ScoringResult()


def test_missing_model_degrades_to_empty_result_not_a_crash(monkeypatch):
    """The whole reason this module exists in-process rather than as a
    separately deployed service: a broken/missing model artifact must
    never take down the main API. Simulates that by pointing _MODEL at
    None directly, the same state _load() leaves it in when loading
    fails - see injury_model.py's own comment on why that except is
    deliberately broad.
    """
    monkeypatch.setattr(injury_model, "_MODEL", None)

    result = score_occupations({134: {f: 50.0 for f in injury_model._FEATURES}})

    assert result == ScoringResult()
