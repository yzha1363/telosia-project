"""Transport compatibility: no live model, database, or credentials required."""

import json
from types import SimpleNamespace as NS

import httpx
import httpx2
import pytest
from openai import APIError, OpenAI

from app.services import nvidia_chat
from app.services.chat_execution import ChatCancelled, ChatControl


class OfflineDB:
    def __getattribute__(self, name):
        raise AssertionError(f"Unexpected database access: {name}")


class Stream:
    def __init__(self, fragments):
        self.fragments = fragments
        self.closed = False

    def __iter__(self):
        yield from self.fragments

    def close(self):
        self.closed = True


def chunk(content=None, reasoning=None, calls=None, finish=None):
    return NS(choices=[NS(delta=NS(content=content, reasoning_content=reasoning,
                                   tool_calls=calls), finish_reason=finish)])


@pytest.mark.parametrize("transport", [httpx, httpx2], ids=["httpx", "httpx2"])
@pytest.mark.parametrize("kind, code", [("ReadTimeout", "model_timeout"),
                                       ("RemoteProtocolError", "model_unavailable")])
@pytest.mark.parametrize("partial", [None, "text", "reasoning", "tool"])
def test_stream_transport_failure_retry_and_classification(monkeypatch, transport, kind, code, partial):
    monkeypatch.setenv("CHAT_MAX_TRANSIENT_RETRIES", "1")
    streams, attempts, events = [], [], []

    def fragments():
        if partial == "text":
            yield chunk(content="Partial answer")
        elif partial == "reasoning":
            yield chunk(reasoning="PRIVATE_THOUGHT")
        elif partial == "tool":
            yield chunk(calls=[NS(index=0, id="call_1", function=NS(
                name="query_data", arguments='{"dataset":'))])
        raise getattr(transport, kind)("PRIVATE_PROVIDER_DETAIL", request=transport.Request(
            "POST", "https://example.test"))

    def create(**kwargs):
        attempts.append(kwargs)
        stream = Stream(fragments())
        streams.append(stream)
        return stream

    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: NS(
        chat=NS(completions=NS(create=create)), close=lambda: None))
    context = {}
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as failure:
        nvidia_chat.generate_chat_answer("Hi", context, db=OfflineDB(),
                                        on_event=lambda e, d: events.append((e, d)))
    assert failure.value.code == code
    assert len(attempts) == (1 if partial else 2)
    assert all(stream.closed for stream in streams)
    assert events[-1][0] == "answer_reset"
    assert context["database_tool_names"] == []
    assert "PRIVATE_" not in json.dumps(context) + json.dumps(events) + str(failure.value)
    assert [t["outcome"] for t in context["timings"] if t["stage"] == "model"] == [
        "APITimeoutError" if kind == "ReadTimeout" else "APIConnectionError"
    ] * len(attempts)


@pytest.mark.parametrize("partial", [False, True])
def test_real_sdk_sse_error_event_is_classified_without_replay(monkeypatch, partial, caplog):
    attempts = []

    def respond(request):
        attempts.append(request)
        frames = []
        if partial:
            frames.append({"id": "chatcmpl-test", "object": "chat.completion.chunk",
                           "created": 0, "model": "test", "choices": [
                               {"index": 0, "delta": {"content": "Partial"}, "finish_reason": None}]})
        frames.append({"error": {"message": "PRIVATE_PROVIDER_DETAIL", "type": "server_error"}})
        body = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    sdk = OpenAI(api_key="synthetic-test-key", base_url="https://example.test/v1", max_retries=0,
                 http_client=httpx2.Client(transport=httpx2.MockTransport(respond)))
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: sdk)
    context, events = {}, []
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as failure:
        nvidia_chat.generate_chat_answer("Hi", context, on_event=lambda e, d: events.append((e, d)))
    assert failure.value.code == "model_stream_error"
    assert isinstance(failure.value.__cause__, APIError)
    assert len(attempts) == 1
    assert events[-1][0] == "answer_reset"
    assert "PRIVATE_PROVIDER_DETAIL" not in str(failure.value) + json.dumps(events) + caplog.text
    assert any(t.get("outcome") == "APIError" for t in context["timings"])
    assert sdk.is_closed()


def test_httpx2_timeout_can_recover_on_one_retry(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_TRANSIENT_RETRIES", "1")
    attempts = []

    def fail():
        raise httpx2.ReadTimeout("slow", request=httpx2.Request("POST", "https://example.test"))
        yield

    def create(**kwargs):
        attempts.append(kwargs)
        return Stream(fail() if len(attempts) == 1 else [chunk("Hello!", finish="stop")])

    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: NS(
        chat=NS(completions=NS(create=create)), close=lambda: None))
    assert nvidia_chat.generate_chat_answer("Hi", {}, on_event=lambda *_: None) == "Hello!"
    assert len(attempts) == 2


@pytest.mark.parametrize("expired, expected", [(False, "cancelled"), (True, "request_timeout")])
def test_transport_failure_during_cancellation_preserves_reason(monkeypatch, expired, expected):
    control = ChatControl()

    def fragments():
        control.cancel(expired=expired)
        raise httpx2.ReadError("closed", request=httpx2.Request("POST", "https://example.test"))
        yield  # generator that fails on first read

    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: NS(
        chat=NS(completions=NS(create=lambda **_: Stream(fragments()))), close=lambda: None))
    with pytest.raises((ChatCancelled, nvidia_chat.ChatModelUnavailableError)) as failure:
        nvidia_chat.generate_chat_answer("Hi", {}, control=control, on_event=lambda *_: None)
    if expected == "cancelled":
        assert isinstance(failure.value, ChatCancelled)
    else:
        assert failure.value.code == expected
