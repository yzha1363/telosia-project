"""Offline regression tests for early evidence and bounded tool failures."""
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from openai import APITimeoutError
from sqlalchemy import Boolean, String, column

from app.routes.chat import _run_chat
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_context, chat_data, nvidia_chat
from test_chat_stream import Stream, chunk, install_client


@pytest.mark.parametrize("value, expected", [(True, True), (False, False), ("true", True), (" FALSE ", False)])
def test_boolean_literals(value, expected):
    assert chat_data._typed_value(column("flag", Boolean), value) is expected
    assert chat_data._typed_value(column("name", String), "false") == "false"


@pytest.mark.parametrize("value", [1, 0, "yes", "0", "", None])
def test_ambiguous_boolean_rejected(value):
    with pytest.raises(ValueError):
        chat_data._typed_value(column("flag", Boolean), value)


@pytest.mark.parametrize("marker", nvidia_chat._TextGuard.markers)
def test_protocol_never_leaks_even_split_at_every_character(marker):
    guard = nvidia_chat._TextGuard()
    visible = guard.feed("Checking. ")
    with pytest.raises(nvidia_chat.ChatModelUnavailableError, match="tool-call format"):
        for char in marker:
            visible += guard.feed(char)
    assert visible == "Checking. "


def tool_stream(args, identifier="call1"):
    return Stream([
        chunk(calls=[NS(index=0, id=identifier, function=NS(name="query_data", arguments=json.dumps(args)))]),
        chunk(finish="tool_calls"),
    ])


def test_repeated_failure_stops_before_second_execution(monkeypatch):
    executions = []
    def execute(self, name, args):
        executions.append(args)
        return {"error": "Invalid field", "retryable": True}
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, "execute", execute)
    install_client(monkeypatch, lambda **kwargs: tool_stream({"dataset": "wrong"}))
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as error:
        nvidia_chat.generate_chat_answer("Compare jobs", {}, db=object(), on_event=lambda *args: None)
    assert error.value.code == "repeated_tool_error"
    assert len(executions) == 1


def test_early_evidence_survives_model_timeout_and_retains_sources(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_TRANSIENT_RETRIES", "0")
    monkeypatch.setattr(chat_data, "query_dataset", lambda *args: ({
        "dataset": "body_region_exposure", "rows": [{"occupation_title": "Example", "score": 21.3}],
        "fields": {"score": {"unit": "exposure index"}}, "truncated": False,
        "query": {"filters": [{"field": "region", "op": "eq", "value": "Lower back"}]},
    }, {1}))
    monkeypatch.setattr(chat_context, "load_supporting_sources", lambda *args: [
        {"source_id": 1, "publisher": "Test publisher", "dataset_title": "Test dataset"}])
    events = []
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            return tool_stream({"dataset": "body_region_exposure"})
        assert any(event == "data_result" for event, _ in events)
        raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    install_client(monkeypatch, create)
    result = _run_chat(ChatRequest(message="Which jobs have lower back exposure?"), object(),
                       on_event=lambda event, data: events.append((event, data)))
    validated = ChatResponse.model_validate(result)
    assert validated.status == "partial"
    assert validated.error_code == "model_timeout"
    preview = validated.data_results[0]
    assert preview["rows"][0]["score"] == 21
    assert preview["sources"][0]["source_id"] == 1
    assert "beta" in preview["notice"] and "medical suitability" in preview["notice"]
    assert len([e for e, _ in events if e == "data_result"]) == 1


def test_duplicate_success_reuses_query(monkeypatch):
    executions = []
    def execute(self, name, args):
        executions.append(args)
        return {"rows": [{"count": 4}]}
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, "execute", execute)
    responses = iter([tool_stream({"dataset": "occupation"}), tool_stream({"dataset": "occupation"}, "call2"),
                      Stream([chunk("Four records."), chunk(finish="stop")])])
    install_client(monkeypatch, lambda **kwargs: next(responses))
    answer = nvidia_chat.generate_chat_answer("How many jobs?", {}, db=object(), on_event=lambda *args: None)
    assert answer == "Four records."
    assert len(executions) == 1


def test_stream_protocol_error_resets_answer(monkeypatch):
    install_client(monkeypatch, lambda **kwargs: Stream([
        chunk("Checking... <"), chunk("｜DSML｜ calls>"), chunk(finish="stop")]))
    events = []
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as error:
        nvidia_chat.generate_chat_answer("Find jobs", {}, on_event=lambda *args: events.append(args))
    assert error.value.code == "tool_protocol_error"
    assert not any("<" in data.get("text", "") for event, data in events if event == "delta")
    assert events[-1][0] == "answer_reset"
