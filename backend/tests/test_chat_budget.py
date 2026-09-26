import json
from types import SimpleNamespace as NS

import pytest

from app.services.chat_budget import ChatBudget, model_call_timeout
from app.services import chat_receipt, nvidia_chat
from app.routes import chat as route
from app.schemas.chat import ChatRequest
from test_chat_stream import Stream, chunk, install_client, stream_client
from test_chat_resilience import tool_stream


def test_shared_budget_defaults_and_bounds(monkeypatch):
    for key in ('CHAT_TOTAL_TIMEOUT_SECONDS', 'CHAT_EXTENDED_TIMEOUT_SECONDS', 'CHAT_SUMMARY_RESERVE_SECONDS'):
        monkeypatch.delenv(key, raising=False)
    assert ChatBudget.configured() == ChatBudget(240, 60)
    assert ChatBudget.configured(True) == ChatBudget(300, 60)
    monkeypatch.setenv('CHAT_TOTAL_TIMEOUT_SECONDS', '999')
    assert ChatBudget.configured().total == 300
    monkeypatch.setenv('CHAT_TOTAL_TIMEOUT_SECONDS', '60')
    assert ChatBudget.configured().reserve == 30
    monkeypatch.setenv('CHAT_TOTAL_TIMEOUT_SECONDS', 'invalid')
    assert ChatBudget.configured().total == 240


@pytest.mark.parametrize("configured, expected", [("180", 120), ("45", 45), ("invalid", 60)])
def test_client_and_request_share_call_timeout(monkeypatch, configured, expected):
    monkeypatch.setenv("NVIDIA_CHAT_TIMEOUT_SECONDS", configured)
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    captured = {}
    monkeypatch.setattr(nvidia_chat, "OpenAI", lambda **kwargs: captured.update(kwargs))
    nvidia_chat._create_client()
    assert captured["timeout"] == model_call_timeout() == expected


def test_calls_cannot_consume_summary_reserve():
    budget = ChatBudget(240, 60)
    assert budget.call_timeout(85, 60, False) == 25
    assert budget.call_timeout(59, 60, True) == 59
    assert budget.should_summarize(61)
    assert not budget.should_summarize(85)


@pytest.mark.parametrize('blocked_transport', [False, True])
def test_analysis_deadline_switches_to_one_summary_without_more_tools(monkeypatch, blocked_transport):
    monkeypatch.setenv('CHAT_TOTAL_TIMEOUT_SECONDS', '240')
    monkeypatch.setenv('CHAT_SUMMARY_RESERVE_SECONDS', '60')
    clock = {'now': 0.0}
    monkeypatch.setattr(nvidia_chat.time, 'monotonic', lambda: clock['now'])
    timers = []
    class FakeTimer:
        def __init__(self, seconds, callback):
            self.callback = callback
            timers.append(self)
        def start(self): pass
        def cancel(self): pass
    monkeypatch.setattr(nvidia_chat, 'Timer', FakeTimer)
    executions, requests = [], []
    def execute(self, name, args):
        executions.append(args)
        self.data_queries.append({'dataset': 'occupation', 'query_id': 'q1', 'row_count': 1, 'truncated': False})
        return {'rows': [{'total': 17}]}
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, 'execute', execute)
    def create(**kwargs):
        requests.append(json.loads(json.dumps(kwargs)))
        if len(requests) == 1:
            return tool_stream({'dataset': 'occupation'})
        if len(requests) == 2:
            clock['now'] = 181
            if blocked_transport:
                timers[-1].callback()
                raise OSError('Synthetic socket close')
            return Stream([chunk('Unfinished planning')])
        assert kwargs['tool_choice'] == 'none'
        return Stream([chunk('17 records were retrieved; the further comparison is unfinished.'), chunk(finish='stop')])
    install_client(monkeypatch, create)
    context = {}
    answer = nvidia_chat.generate_chat_answer('Compare records', context, db=object(), on_event=lambda *args: None)
    assert len(requests) == 3 and len(executions) == 1
    assert context['budget_limited'] is True
    assert requests[-1]['timeout'] == 59
    assert 'unfinished' in answer
    assert context['timings'][-1]['outcome'] == 'partial'


def test_signed_receipt_tampering_expiry_and_no_raw_data(monkeypatch):
    result = {'status': 'partial', 'request_id': 'r1', 'data_queries': [{'dataset': 'occupation_profile'}],
              'answer': 'PRIVATE', 'data_results': [{'rows': [{'salary': 123}]}]}
    monkeypatch.setattr(chat_receipt.time, 'time', lambda: 1000)
    token = chat_receipt.issue_receipt(result)
    payload = chat_receipt.verify_receipt(token)
    assert payload['status'] == 'partial'
    assert payload['datasets'] == ['occupation_profile']
    assert 'PRIVATE' not in json.dumps(payload) and 'salary' not in json.dumps(payload)
    assert chat_receipt.verify_receipt(token + 'x') is None
    monkeypatch.setattr(chat_receipt.time, 'time', lambda: 4601)
    assert chat_receipt.verify_receipt(token) is None


def test_partial_response_receipt_informs_next_turn(monkeypatch):
    def first(question, context, **kwargs):
        context['budget_limited'] = True
        context['data_queries'] = [{'dataset': 'occupation_profile', 'query_id': 'q1', 'row_count': 0, 'truncated': False}]
        return 'Incomplete comparison.'
    monkeypatch.setattr(route, 'generate_chat_answer', first)
    result = route._run_chat(ChatRequest(message='Compare jobs'), object())
    assert result['status'] == 'partial'
    def second(question, context, **kwargs):
        assert context['previous_turn']['status'] == 'partial'
        assert context['previous_turn']['datasets'] == ['occupation_profile']
        return 'The previous analysis did not finish.'
    monkeypatch.setattr(route, 'generate_chat_answer', second)
    route._run_chat(ChatRequest(message='What happened?', previous_turn_token=result['turn_token']), object())


def test_sse_advertises_same_extended_budget(monkeypatch):
    monkeypatch.setenv('CHAT_TOTAL_TIMEOUT_SECONDS', '240')
    monkeypatch.setenv('CHAT_EXTENDED_TIMEOUT_SECONDS', '300')
    client = stream_client(monkeypatch, lambda *args, **kwargs: 'Hello')
    response = client.post('/api/v1/chat/stream', json={'message': 'Hello', 'extended_analysis': True})
    assert '"timeout_ms": 315000' in response.text
