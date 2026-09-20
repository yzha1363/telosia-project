from types import SimpleNamespace

from app.services.chat_intent import parse_occupation_demand_intent
from app.services.occupation_demand_search import (
    rank_occupations_by_body_demand,
    resolve_region_hazards,
)


def test_high_exposure_job_search_intent_supports_multiple_regions():
    intent = parse_occupation_demand_intent(
        "What jobs require using the hands or lower back?"
    )

    assert intent is not None
    assert intent.direction == "high"
    assert intent.personal_constraint is False
    assert intent.regions == ("Lower back", "Hands and wrists")


def test_issue_with_body_part_becomes_low_exposure_search():
    intent = parse_occupation_demand_intent(
        "I have an issue with my lower back, so what kind of job "
        "should I choose?"
    )

    assert intent is not None
    assert intent.direction == "low"
    assert intent.personal_constraint is True
    assert intent.regions == ("Lower back",)


def test_low_exposure_synonym_sentences_are_recognised():
    questions = [
        "I have problems with my knees. Which jobs could I do?",
        "I have difficulty using my hands. What occupations should I choose?",
        "My legs are limited. What job options could I explore?",
        "I want to avoid strain on my shoulders. What jobs could I do?",
        "I struggle to use my hands. What type of work should I consider?",
        "I have a lumbar problem. Which roles could I do?",
        "My wrist is injured. What careers could I explore?",
    ]

    for question in questions:
        intent = parse_occupation_demand_intent(question)
        assert intent is not None, question
        assert intent.direction == "low", question
        assert intent.personal_constraint is True, question


def test_job_demand_question_is_a_high_exposure_occupation_search():
    intent = parse_occupation_demand_intent(
        "What job demands are associated with the lower back?"
    )

    assert intent is not None
    assert intent.direction == "high"
    assert intent.regions == ("Lower back",)


def test_work_demand_question_still_requests_general_hazard_information():
    assert parse_occupation_demand_intent(
        "What work demands are associated with the lower back?"
    ) is None


def test_sam_mapping_resolves_to_approved_rag_ids():
    resolved = resolve_region_hazards(("Lower back", "Hands and wrists"))

    assert {
        item["hazard_variable_id"]
        for item in resolved["Lower back"]
    } == {1, 6, 24, 26}
    assert {
        item["hazard_variable_id"]
        for item in resolved["Hands and wrists"]
    } == {5, 8, 34}


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def test_low_exposure_ranking_uses_max_and_excludes_missing_regions():
    intent = parse_occupation_demand_intent(
        "I have an issue with my legs and knees. What jobs should I choose?"
    )
    assert intent is not None

    rows = [
        {
            "occupation_id": 1,
            "occupation_title": "Complete Low",
            "hazard_variable_id": 4,
            "hazard_variable": "Spend Time Kneeling, Crouching, Stooping, or Crawling",
            "exposure_score": 12.4,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 1,
            "occupation_title": "Complete Low",
            "hazard_variable_id": 7,
            "hazard_variable": "Spend Time Standing",
            "exposure_score": 20.2,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 1,
            "occupation_title": "Complete Low",
            "hazard_variable_id": 9,
            "hazard_variable": "Spend Time Walking and Running",
            "exposure_score": 8.0,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 2,
            "occupation_title": "Complete High",
            "hazard_variable_id": 4,
            "hazard_variable": "Spend Time Kneeling, Crouching, Stooping, or Crawling",
            "exposure_score": 70.0,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 2,
            "occupation_title": "Complete High",
            "hazard_variable_id": 7,
            "hazard_variable": "Spend Time Standing",
            "exposure_score": 85.0,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 2,
            "occupation_title": "Complete High",
            "hazard_variable_id": 9,
            "hazard_variable": "Spend Time Walking and Running",
            "exposure_score": 60.0,
            "source_reference_id": 3,
        },
        {
            "occupation_id": 3,
            "occupation_title": "Missing Legs Data",
            "hazard_variable_id": 4,
            "hazard_variable": "Spend Time Kneeling, Crouching, Stooping, or Crawling",
            "exposure_score": 0.0,
            "source_reference_id": 3,
        },
    ]
    fake_db = SimpleNamespace(
        execute=lambda *_args, **_kwargs: _FakeMappings(rows)
    )

    results, source_ids = rank_occupations_by_body_demand(
        fake_db,
        intent,
        limit=5,
    )

    assert [result["title"] for result in results] == [
        "Complete Low",
        "Complete High",
    ]
    assert results[0]["relative_exposure_score"] == 20
    assert source_ids == {3}
