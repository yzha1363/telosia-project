from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import chat as chat_route
from app.services import nvidia_chat
from app.services.chat_context import (
    calculate_frequency_summary,
    is_in_scope,
    requires_occupation,
)
from database.connection import get_db


def test_scope_guard_accepts_telosia_topics():
    assert is_in_scope("What physical demands affect the lower back?")
    assert is_in_scope("Where does this occupation usually move next?")
    assert is_in_scope("What is the injury frequency rate?")


def test_scope_guard_rejects_unrelated_and_medical_questions():
    assert not is_in_scope("What will the weather be tomorrow?")
    assert not is_in_scope("Can you diagnose my shoulder symptoms?")
    assert not is_in_scope("Write some Python code for me")


def test_occupation_requirement():
    assert requires_occupation("Show the lower back exposure")
    assert requires_occupation("What is the injury frequency rate?")
    assert requires_occupation("What affects this occupation?")
    assert not requires_occupation(
        "What hazards may affect the lower back?"
    )
    assert not requires_occupation("Where does the Telosia data come from?")


def test_frequency_summary_uses_means_and_ignores_missing_values():
    rows = [
        {
            "financial_year": "2018-19",
            "frequency_rate": 2.0,
            "is_preliminary": False,
            "source_reference_id": 2,
        },
        {
            "financial_year": "2019-20",
            "frequency_rate": None,
            "is_preliminary": False,
            "source_reference_id": 2,
        },
        {
            "financial_year": "2020-21",
            "frequency_rate": 4.0,
            "is_preliminary": False,
            "source_reference_id": 2,
        },
        {
            "financial_year": "2021-22",
            "frequency_rate": 6.0,
            "is_preliminary": False,
            "source_reference_id": 2,
        },
        {
            "financial_year": "2022-23",
            "frequency_rate": 8.0,
            "is_preliminary": False,
            "source_reference_id": 2,
        },
        {
            "financial_year": "2023-24",
            "frequency_rate": 10.0,
            "is_preliminary": True,
            "source_reference_id": 2,
        },
    ]

    result = calculate_frequency_summary(rows)

    assert result["all_years_average"] == 6.0
    assert result["last_five_years_average"] == 6.0
    assert result["last_five_financial_years"] == [
        "2018-19",
        "2020-21",
        "2021-22",
        "2022-23",
        "2023-24",
    ]
    assert result["suppressed_or_missing_year_count"] == 1


def test_model_client_receives_only_supplied_context(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="A grounded answer.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: fake_client)

    answer = nvidia_chat.generate_chat_answer(
        "What is available?",
        {"published_value": 12.3},
    )

    assert answer == "A grounded answer."
    assert captured["model"] == "openai/gpt-oss-20b"
    assert "12.3" in captured["messages"][1]["content"]
    assert "Answer only from" in captured["messages"][0]["content"]


def test_model_answer_always_identifies_general_scope(monkeypatch):
    class FakeCompletions:
        def create(self, **_kwargs):
            message = SimpleNamespace(content="A grounded answer.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: fake_client)

    answer = nvidia_chat.generate_chat_answer(
        "What affects the lower back?",
        {
            "answer_scope": {"occupation_selected": False},
            "occupation": None,
        },
    )

    assert answer.startswith("**Scope: general information")
    assert "not an occupation-specific profile" in answer


def test_model_answer_names_selected_occupation(monkeypatch):
    class FakeCompletions:
        def create(self, **_kwargs):
            message = SimpleNamespace(content="A grounded answer.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: fake_client)

    answer = nvidia_chat.generate_chat_answer(
        "What affects this occupation?",
        {
            "answer_scope": {"occupation_selected": True},
            "occupation": {
                "profile": {"title": "Aged and Disabled Carers"},
            },
        },
    )

    assert answer.startswith("**Occupation: Aged and Disabled Carers**")


def test_general_body_mapping_is_deterministic_and_correctly_attributed(
    monkeypatch,
):
    monkeypatch.setattr(
        nvidia_chat,
        "_create_client",
        lambda: (_ for _ in ()).throw(AssertionError("model should not run")),
    )
    answer = nvidia_chat.generate_chat_answer(
        "What work demands are associated with the lower back?",
        {
            "answer_scope": {"occupation_selected": False},
            "occupation": None,
            "retrieved_knowledge": [
                {
                    "document_type": "hazard_body_association",
                    "metadata": {
                        "hazard_variable": "Spend Time Bending",
                        "hazard_category": "Body Positioning",
                        "review_status": "approved",
                        "body_mappings": [
                            {
                                "body_part": "Lower back",
                                "strength": "Strong",
                                "association_score": 3,
                            }
                        ],
                    },
                }
            ],
        },
    )

    assert "Spend Time Bending" in answer
    assert "Telosia's separate annotation layer" in answer
    assert "not body-part mappings or injury claims published in BOHD" in answer


def _test_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(chat_route.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        chat_route,
        "build_chat_context",
        lambda _db, _occupation_id, _question: (
            {
                "occupation": {"title": "Test occupation"},
                "retrieved_knowledge": [],
            },
            [],
        ),
    )
    monkeypatch.setattr(
        chat_route,
        "generate_chat_answer",
        lambda _question, _context: "Grounded response",
    )
    return TestClient(app)


def test_chat_endpoint_rejects_out_of_scope_without_model(monkeypatch):
    client = _test_client(monkeypatch)
    response = client.post(
        "/api/v1/chat",
        json={"message": "Tell me tomorrow's weather"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "out_of_scope"


def test_chat_endpoint_requests_an_occupation_when_needed(monkeypatch):
    client = _test_client(monkeypatch)
    response = client.post(
        "/api/v1/chat",
        json={"message": "Show the lower back exposure"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_occupation"


def test_chat_endpoint_returns_grounded_answer(monkeypatch):
    client = _test_client(monkeypatch)
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Show the lower back exposure",
            "occupation_id": 237,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "answered",
        "answer": "Grounded response",
        "occupation_id": 237,
        "occupation_results": [],
        "sources": [],
    }


def test_chat_endpoint_returns_structured_low_exposure_occupations(
    monkeypatch,
):
    client = _test_client(monkeypatch)
    result = {
        "occupation_id": 42,
        "title": "Example Occupation",
        "comparison": "lower",
        "relative_exposure_score": 18,
        "body_regions": ["Lower back"],
        "leading_demands": ["Spend Time Sitting"],
    }
    monkeypatch.setattr(
        chat_route,
        "rank_occupations_by_body_demand",
        lambda **_kwargs: ([result], {3}),
    )
    monkeypatch.setattr(
        chat_route,
        "load_supporting_sources",
        lambda _db, _source_ids: [],
    )

    response = client.post(
        "/api/v1/chat",
        json={
            "message": (
                "I have an issue with my lower back. What kind of job "
                "should I choose?"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered"
    assert payload["occupation_results"] == [result]
    assert "lower recorded physical-demand exposure" in payload["answer"]
    assert "does not determine" in payload["answer"]


def test_cross_occupation_question_ignores_selected_occupation(monkeypatch):
    client = _test_client(monkeypatch)
    result = {
        "occupation_id": 51,
        "title": "High Demand Occupation",
        "comparison": "higher",
        "relative_exposure_score": 96,
        "body_regions": ["Lower back"],
        "leading_demands": ["Spend Time Bending or Twisting the Body"],
    }
    captured = {}

    def fake_rank(**kwargs):
        captured.update(kwargs)
        return [result], {3}

    monkeypatch.setattr(
        chat_route,
        "rank_occupations_by_body_demand",
        fake_rank,
    )
    monkeypatch.setattr(
        chat_route,
        "load_supporting_sources",
        lambda _db, _source_ids: [],
    )

    response = client.post(
        "/api/v1/chat",
        json={
            "message": "What job demands are associated with the lower back?",
            "occupation_id": 237,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["occupation_id"] is None
    assert payload["occupation_results"] == [result]
    assert "Across Telosia's profile occupations" in payload["answer"]
    assert captured["limit"] == 4
