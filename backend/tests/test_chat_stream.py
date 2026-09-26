"""Streaming and timeout behaviour without a live provider or database."""

import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import APITimeoutError

from app.routes import chat as route
from app.services import chat_context, chat_data, nvidia_chat
from app.services.chat_execution import ChatCancelled, ChatControl


class OfflineDB:
    def __getattribute__(self, name):
        raise AssertionError(f"Database accessed unexpectedly: {name}")


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self):
        self.closed = True


def chunk(content=None, calls=None, finish=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=calls or []), finish_reason=finish)])


def install_client(monkeypatch, create):
    client = NS(chat=NS(completions=NS(create=create)), close=lambda: None)
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: client)
    return client


def forbid(*args, **kwargs):
    raise AssertionError("Database/catalog access before a tool requested it")


def test_streaming_greeting_with_selected_occupation_never_reads_database(monkeypatch):
    monkeypatch.setattr(chat_data, "catalog", forbid)
    monkeypatch.setattr(chat_data, "_read_connection", forbid)
    monkeypatch.setattr(chat_context, "load_supporting_sources", forbid)
    response = Stream([chunk("Hello"), chunk("!"), chunk(finish="stop")])
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return response
    install_client(monkeypatch, create)
    context, sources = chat_context.build_chat_context(237)
    events = []
    answer = nvidia_chat.generate_chat_answer("Hi!", context, db=OfflineDB(), selected_occupation_id=237,
                                              on_event=lambda event, data: events.append((event, data)))
    assert answer == "Hello!" and sources == []
    assert context["data_queries"] == [] and context["database_tool_names"] == []
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert [data["text"] for event, data in events if event == "delta"] == ["Hello", "!"]
    assert response.closed
    assert any(item["stage"] == "first_text" for item in context["timings"])


def test_streamed_tool_json_is_assembled_before_one_execution(monkeypatch):
    calls = []
    def execute(self, name, arguments):
        calls.append((name, arguments))
        return {"query_id": "q1", "rows": [{"total": 358}]}
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, "execute", execute)
    first = Stream([
        chunk("Let me check."),
        chunk(calls=[NS(index=0, id="call1", function=NS(name="query_data", arguments='{"dataset":'))]),
        chunk(calls=[NS(index=0, id=None, function=NS(name=None, arguments='"occupation"}'))]),
        chunk(finish="tool_calls"),
    ])
    second = Stream([chunk("There are 358 records."), chunk(finish="stop")])
    responses = iter([first, second])
    requests = []
    def create(**kwargs):
        requests.append(json.loads(json.dumps(kwargs)))
        return next(responses)
    install_client(monkeypatch, create)
    events = []
    answer = nvidia_chat.generate_chat_answer("Count occupations", {}, db=OfflineDB(),
                                              on_event=lambda event, data: events.append((event, data)))
    assert calls == [("query_data", {"dataset": "occupation"})]
    assert answer == "There are 358 records."
    assert any(event == "answer_reset" for event, _ in events)
    assert any(data.get("stage") == "querying" for _, data in events)
    assert requests[-1]["messages"][-1]["role"] == "tool"
    assert first.closed and second.closed


@pytest.mark.parametrize("finish", [None, "length"])
def test_partial_or_length_limited_stream_never_becomes_final_answer(monkeypatch, finish):
    stream = Stream([chunk("Partial answer"), chunk(finish=finish)])
    install_client(monkeypatch, lambda **_: stream)
    events = []
    with pytest.raises(nvidia_chat.ChatModelUnavailableError):
        nvidia_chat.generate_chat_answer("Question", {}, on_event=lambda e, d: events.append((e, d)))
    assert events[-1][0] == "answer_reset"
    assert stream.closed


def test_transient_model_timeout_is_retried_only_once_without_database_work(monkeypatch):
    attempts = []
    def create(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))
        return Stream([chunk("Hello!"), chunk(finish="stop")])
    install_client(monkeypatch, create)
    events = []
    context = {}
    assert nvidia_chat.generate_chat_answer("Hi", context, db=OfflineDB(), on_event=lambda e, d: events.append((e, d))) == "Hello!"
    assert len(attempts) == 2
    assert any(data.get("stage") == "retrying" for _, data in events)
    assert context["data_queries"] == []
    assert next(item for item in context["timings"] if item["stage"] == "model")["outcome"] == "APITimeoutError"


def test_repeated_timeout_has_specific_error_code_stage_and_timings(monkeypatch):
    attempts = []
    def create(**kwargs):
        attempts.append(kwargs)
        raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    install_client(monkeypatch, create)
    context = {}
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as failure:
        nvidia_chat.generate_chat_answer("Hello", context, db=OfflineDB())
    assert failure.value.code == "model_timeout"
    assert failure.value.stage == "understanding"
    assert len(attempts) == 2
    assert context["database_tool_names"] == []
    assert context["timings"][-1]["outcome"] == "error"


def test_partial_stream_timeout_is_not_automatically_replayed(monkeypatch):
    attempts = []
    def fragments():
        yield chunk("Partial")
        raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    def create(**kwargs):
        attempts.append(kwargs)
        return Stream(fragments())
    install_client(monkeypatch, create)
    with pytest.raises(nvidia_chat.ChatModelUnavailableError):
        nvidia_chat.generate_chat_answer("Hi", {}, on_event=lambda *_: None)
    assert len(attempts) == 1


def test_raw_stream_read_timeout_keeps_timeout_classification(monkeypatch):
    def fragments():
        yield chunk("Partial")
        raise httpx.ReadTimeout("slow socket", request=httpx.Request("POST", "https://example.test"))
    install_client(monkeypatch, lambda **_: Stream(fragments()))
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as failure:
        nvidia_chat.generate_chat_answer("Hi", {}, on_event=lambda *_: None)
    assert failure.value.code == "model_timeout"


def test_disconnect_stops_before_model_or_tools(monkeypatch):
    install_client(monkeypatch, forbid)
    control = ChatControl()
    control.cancel()
    with pytest.raises(ChatCancelled):
        nvidia_chat.generate_chat_answer("Hi", {}, control=control)


def test_total_deadline_is_not_misreported_as_database_or_model_timeout(monkeypatch):
    control = ChatControl()
    def create(**kwargs):
        control.cancel(expired=True)
        raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    install_client(monkeypatch, create)
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as failure:
        nvidia_chat.generate_chat_answer("Question", {}, control=control)
    assert failure.value.code == "request_timeout"


def stream_client(monkeypatch, generate):
    @contextmanager
    def session():
        yield OfflineDB()
    monkeypatch.setattr(route, "SessionLocal", session)
    monkeypatch.setattr(route, "generate_chat_answer", generate)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/v1")
    return TestClient(app)


def test_sse_route_preserves_order_and_returns_authoritative_result(monkeypatch):
    def generate(question, context, **kwargs):
        emit = kwargs["on_event"]
        emit("status", {"stage": "generating", "message": "Writing…"})
        emit("delta", {"text": "Hello"})
        return "Hello!"
    with stream_client(monkeypatch, generate) as client:
        result = client.post("/api/v1/chat/stream", json={"message": "Hi!", "occupation_id": 237})
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/event-stream")
    assert result.text.index("event: status") < result.text.index("event: delta") < result.text.index("event: result")
    final = json.loads(result.text.split("event: result\ndata: ", 1)[1].split("\n\n")[0])
    assert final["answer"] == "Hello!" and final["sources"] == []
    assert final["request_id"] and final["data_queries"] == []


def test_sse_timeout_preserves_reason_and_does_not_publish_partial_success(monkeypatch):
    def generate(question, context, **kwargs):
        kwargs["on_event"]("answer_reset", {})
        raise nvidia_chat.ChatModelUnavailableError("The model service timed out.", "model_timeout", "understanding")
    with stream_client(monkeypatch, generate) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "Hello"})
    final = json.loads(response.text.split("event: result\ndata: ", 1)[1].split("\n\n")[0])
    assert final["status"] == "temporarily_unavailable"
    assert final["error_code"] == "model_timeout"
    assert final["error_stage"] == "understanding"


def test_reasoning_activity_is_timed_but_never_sent_to_frontend(monkeypatch):
    thought = chunk()
    thought.choices[0].delta.reasoning_content = "Private synthetic reasoning: do not display."
    install_client(monkeypatch, lambda **_: Stream([thought, chunk("Hello!"), chunk(finish="stop")]))
    context, events = {}, []
    assert nvidia_chat.generate_chat_answer("Hi", context, on_event=lambda e, d: events.append((e, d))) == "Hello!"
    first = next(item for item in context["timings"] if item["stage"] == "first_model_event")
    assert first["event_kind"] == "reasoning"
    assert "Private synthetic reasoning" not in json.dumps(context)
    assert "Private synthetic reasoning" not in json.dumps(events)


@pytest.mark.parametrize("setting, expected", [("default", None), ("low", "low"), ("medium", "medium"), ("high", "high"), ("invalid", None)])
def test_reasoning_effort_is_opt_in_and_validated(monkeypatch, setting, expected):
    monkeypatch.setenv("NVIDIA_CHAT_REASONING_EFFORT", setting)
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return Stream([chunk("Hello!"), chunk(finish="stop")])
    install_client(monkeypatch, create)
    nvidia_chat.generate_chat_answer("Hello", {}, on_event=lambda *_: None)
    assert captured[0].get("reasoning_effort") == expected
    assert ("reasoning_effort" in captured[0]) == (expected is not None)
