"""Provider-independent tool transport, not question-specific routing."""
import json
from types import SimpleNamespace as NS

import pytest

from app.services.chat_protocol import ActionProtocolError, action_messages, decode_action, decode_reply
from app.services import nvidia_chat
from test_chat_stream import Stream, chunk, install_client

TOOLS = [{'type': 'function', 'function': {'name': 'query_data', 'parameters': {'type': 'object'}}}]


def completion(value, finish='stop'):
    return NS(choices=[NS(message=NS(content=json.dumps(value), tool_calls=[]), finish_reason=finish)])


@pytest.mark.parametrize('query', [
    {'dataset': 'mobility_flow', 'filters': [{'field': 'source_occupation_id', 'op': 'eq', 'value': 42}]},
    {'dataset': 'body_region_exposure', 'filters': [{'field': 'complete_coverage', 'op': 'eq', 'value': True}]},
    {'dataset': 'occupation_profile', 'select': ['occupation_title', 'median_weekly_earnings']},
])
def test_envelope_preserves_model_selected_arguments(query):
    text, calls = decode_action(json.dumps({'action': 'tool_calls', 'calls': [{'name': 'query_data', 'arguments': query}]}), TOOLS, final=False)
    assert text == ''
    assert json.loads(calls[0]['function']['arguments']) == query


@pytest.mark.parametrize('value', [
    'null', '[]', '```json\n{}\n```', '{"action":"answer","text":"ok","calls":[]}',
    '{"action":"answer","text":""}', '{"action":"answer","text":17}',
    '{"action":"tool_calls","calls":[]}', '{"action":"answer","action":"answer","text":"ok"}',
    '{"action":"tool_calls","calls":[{"name":"shell","arguments":{}}]}',
    '{"action":"tool_calls","calls":[{"name":"query_data","arguments":"{}"}]}',
    '{"action":"tool_calls","calls":[{"name":"query_data","arguments":{"value":NaN}}]}',
])
def test_rejects_ambiguous_or_executable_text(value):
    with pytest.raises(ActionProtocolError):
        decode_action(value, TOOLS, final=False)


def test_final_budget_cannot_call_more_tools():
    with pytest.raises(ActionProtocolError):
        decode_action(json.dumps({'action': 'tool_calls', 'calls': [{'name': 'query_data', 'arguments': {}}]}), TOOLS, final=True)


def test_normal_final_answer_is_not_mistaken_for_a_tool_request():
    answer, calls = decode_reply('The synthetic fixture records 17 movements. This is not real data.', TOOLS, final=False)
    assert '17' in answer and calls == []


@pytest.mark.parametrize('text', [
    'Let me execute {"action":"tool_calls","calls":[]}',
    '```json\n{"action":"tool_calls","calls":[]}\n```',
    '{"action":"tool_calls","calls":',
])
def test_embedded_or_incomplete_packets_never_become_final_answers(text):
    with pytest.raises(ActionProtocolError):
        decode_reply(text, TOOLS, final=False)


def test_history_keeps_tool_ids_and_results_without_executing_text():
    history = [{'role': 'system', 'content': 'Analyst'}, {'role': 'user', 'content': 'Compare'},
               {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'query_data', 'arguments': '{bad json'}}]},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"error":"Invalid JSON"}'}]
    converted = action_messages(history, TOOLS, final=False)
    assert json.loads(converted[-1]['content'])['tool_result_for'] == 'c1'
    assert json.loads(converted[-2]['content'])['calls'][0]['arguments']['invalid_original_arguments'] == '{bad json'
    assert history[0]['content'] == 'Analyst'


def test_native_failure_recovers_into_model_chosen_tools_then_answer(monkeypatch):
    monkeypatch.setenv('CHAT_TOOL_PROTOCOL', 'auto')
    executed = []
    def execute(self, name, arguments):
        executed.append((name, arguments))
        return {'query_id': 'q1', 'rows': [{'total': 17}]}
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, 'execute', execute)
    responses = iter([
        Stream([chunk('Let me look. <'), chunk('｜DSML｜ calls>')]),
        completion({'action': 'tool_calls', 'calls': [{'name': 'query_data', 'arguments': {'dataset': 'occupation'}}]}),
        completion({'action': 'answer', 'text': 'There are 17 records.'}),
    ])
    requests = []
    def create(**kwargs):
        requests.append(json.loads(json.dumps(kwargs)))
        return next(responses)
    install_client(monkeypatch, create)
    events, context = [], {}
    answer = nvidia_chat.generate_chat_answer('How many occupations?', context, db=object(), on_event=lambda *args: events.append(args))
    assert answer == 'There are 17 records.'
    assert executed == [('query_data', {'dataset': 'occupation'})]
    assert requests[0]['stream'] is True and 'tools' in requests[0]
    assert all(request['stream'] is False and 'tools' not in request and 'response_format' not in request for request in requests[1:])
    assert any('tool_result_for' in msg['content'] for msg in requests[-1]['messages'])
    assert any(t['stage'] == 'protocol_recovery' for t in context['timings'])
    assert not any('action' in data.get('text', '') or 'DSML' in data.get('text', '') for event, data in events if event == 'delta')
    # A later request on the same provider/model/schema bypasses the already
    # demonstrated broken native transport. It still asks the model what to do.
    requests.clear()
    def cached_create(**kwargs):
        requests.append(kwargs)
        return completion({'action': 'answer', 'text': 'Which occupations would you like to compare?'})
    install_client(monkeypatch, cached_create)
    nvidia_chat.generate_chat_answer('Compare some jobs', {}, db=object(), on_event=lambda *args: None)
    assert len(requests) == 1 and 'tools' not in requests[0]


def test_compatibility_hint_is_ttl_bounded_and_model_specific(monkeypatch):
    from app.services import chat_protocol as protocol
    now = {'value': 1000.0}
    monkeypatch.setattr(protocol.time, 'monotonic', lambda: now['value'])
    first = protocol.protocol_key('https://test.invalid', 'model-a', TOOLS)
    other = protocol.protocol_key('https://test.invalid', 'model-b', TOOLS)
    protocol.remember_json(first)
    assert protocol.prefers_json(first) and not protocol.prefers_json(other)
    now['value'] += 601
    assert not protocol.prefers_json(first)


def test_invalid_fallback_is_bounded_and_never_executes(monkeypatch):
    monkeypatch.setenv('CHAT_TOOL_PROTOCOL', 'auto')
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return Stream([chunk('<｜DSML｜ calls>')]) if kwargs['stream'] else completion({'unexpected': 'bad format'})
    def forbidden(*args):
        raise AssertionError('No tools may execute on invalid format')
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, 'execute', forbidden)
    install_client(monkeypatch, create)
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as error:
        nvidia_chat.generate_chat_answer('Find jobs', {}, db=object(), on_event=lambda *args: None)
    assert error.value.code == 'tool_protocol_error'
    assert len(requests) == 2


def test_json_mode_allows_model_to_answer_without_tools(monkeypatch):
    monkeypatch.setenv('CHAT_TOOL_PROTOCOL', 'json')
    install_client(monkeypatch, lambda **kwargs: completion({'action': 'answer', 'text': 'Do you mean qualifications or work demands?'}))
    answer = nvidia_chat.generate_chat_answer('Teacher requirements?', {}, db=object())
    assert answer.startswith('Do you mean')


def test_native_mode_does_not_change_transport(monkeypatch):
    monkeypatch.setenv('CHAT_TOOL_PROTOCOL', 'native')
    install_client(monkeypatch, lambda **kwargs: Stream([chunk('<｜DSML｜ calls>')]))
    with pytest.raises(nvidia_chat.ChatModelUnavailableError) as error:
        nvidia_chat.generate_chat_answer('Find jobs', {}, db=object(), on_event=lambda *args: None)
    assert error.value.code == 'tool_protocol_error'


@pytest.mark.parametrize('streaming', [True, False])
def test_provider_continuation_is_returned_only_to_provider(monkeypatch, streaming):
    monkeypatch.setenv('CHAT_TOOL_PROTOCOL', 'native')
    private = 'SYNTHETIC_PRIVATE_CONTINUATION'
    monkeypatch.setattr(nvidia_chat.ChatToolRuntime, 'execute', lambda *args: {'rows': [{'total': 17}]})
    call = NS(id='c1', function=NS(name='query_data', arguments='{"dataset":"occupation"}'))
    thought = chunk()
    thought.choices[0].delta.reasoning_content = private
    if streaming:
        responses = iter([Stream([thought, chunk(calls=[NS(index=0, id=call.id, function=call.function)]), chunk(finish='tool_calls')]),
                          Stream([chunk('17 records.'), chunk(finish='stop')])])
    else:
        responses = iter([NS(choices=[NS(message=NS(content='', tool_calls=[call], reasoning_content=private), finish_reason='tool_calls')]),
                          NS(choices=[NS(message=NS(content='17 records.', tool_calls=[]), finish_reason='stop')])])
    requests = []
    def create(**kwargs):
        requests.append(json.loads(json.dumps(kwargs)))
        return next(responses)
    install_client(monkeypatch, create)
    context, events = {}, []
    answer = nvidia_chat.generate_chat_answer('Count jobs', context, db=object(),
               on_event=(lambda *args: events.append(args)) if streaming else None)
    assistant = next(m for m in requests[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning_content'] == private
    assert private not in answer + json.dumps(context) + json.dumps(events)
    assert private not in repr(nvidia_chat._Reply('', [], 'stop', private))
