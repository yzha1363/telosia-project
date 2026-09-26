"""Opt-in synthetic, read-only protocol probe; no DB, no secrets/content logged."""
import argparse
import json
import os
from pathlib import Path
import sys
from time import monotonic
from threading import Timer

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--json', action='store_true', help='Test JSON action transport with the same synthetic tool')
    parser.add_argument('--json-prompt', action='store_true', help='Do not request provider JSON mode')
    parser.add_argument('--roundtrip', action='store_true', help='Feed a synthetic result back; only with --json and without --full')
    parser.add_argument('--seconds', type=int, choices=[45, 90], default=45)
    parser.add_argument('--question', default='What jobs do people move into from retail?')
    args = parser.parse_args()
    if args.roundtrip and (not args.json or args.full):
        parser.error('--roundtrip requires --json and cannot use project tools')
    load_dotenv(ROOT / '.env', override=True)
    from app.services.nvidia_chat import _create_client, DEFAULT_MODEL, _reasoning_parameters, SYSTEM_PROMPT
    from app.services.chat_tools import get_chat_tools
    from app.services.chat_data import prompt_catalog
    client = _create_client()
    payload = dict(model=os.getenv('NVIDIA_CHAT_MODEL', DEFAULT_MODEL), max_tokens=2048,
                   temperature=0.2, **_reasoning_parameters())
    payload['tools'] = get_chat_tools() if args.full else [{
        'type': 'function', 'function': {'name': 'lookup_public_data',
        'description': 'Look up public occupational data.', 'parameters': {
        'type': 'object', 'properties': {'topic': {'type': 'string'}},
        'required': ['topic'], 'additionalProperties': False}}}]
    system = SYSTEM_PROMPT + '\nCONTEXT:\n' + json.dumps(prompt_catalog()) if args.full else 'Use the provided tool to look up data. Do not invent data.'
    payload.update(messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': args.question}], tool_choice='auto', stream=args.stream, timeout=min(60, args.seconds))
    if args.json:
        from app.services.chat_protocol import action_messages, decode_reply
        definitions = payload.pop('tools')
        payload.pop('tool_choice')
        original_messages = payload['messages']
        payload['messages'] = action_messages(original_messages, definitions, final=False)
        if not args.json_prompt:
            payload['response_format'] = {'type': 'json_object'}
    result = {'model': payload['model'], 'stream': args.stream, 'full': args.full}
    started = monotonic()
    timer = Timer(args.seconds, client.close)
    timer.daemon = True
    timer.start()
    content = ''
    names = []
    try:
        response = client.chat.completions.create(**payload)
        if args.stream:
            with response:
                for part in response:
                    if not part.choices:
                        continue
                    choice = part.choices[0]
                    content += choice.delta.content or ''
                    names += [call.function.name for call in choice.delta.tool_calls or [] if call.function and call.function.name]
                    if choice.finish_reason:
                        result['finish_reason'] = choice.finish_reason
        else:
            choice = response.choices[0]
            content = choice.message.content or ''
            names = [call.function.name for call in choice.message.tool_calls or []]
            result['finish_reason'] = choice.finish_reason
        result.update(tool_names=names, content_chars=len(content),
                      text_protocol_markers=[m for m in ('DSML', '<tool_call', '<function_call') if m in content])
        if args.json:
            _, actions = decode_reply(content, definitions, final=False)
            result['json_action_names'] = [call['function']['name'] for call in actions]
            if args.roundtrip and actions:
                original_messages.append({'role': 'assistant', 'content': None, 'tool_calls': actions})
                for call in actions:
                    original_messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps({
                        'synthetic_test_only': True, 'rows': [{'occupation': 'Synthetic example role', 'recorded_movements': 17}],
                        'note': 'Synthetic fixture, not real occupational evidence. Summarize only this test fixture.',
                    })})
                payload['messages'] = action_messages(original_messages, definitions, final=False)
                payload['stream'] = False
                followup = client.chat.completions.create(**payload).choices[0]
                final_text = followup.message.content or ''
                result['followup'] = {'finish_reason': followup.finish_reason, 'content_chars': len(final_text),
                                      'fenced': final_text.lstrip().startswith('```'),
                                      'dsml': 'DSML' in final_text}
                try:
                    shape = json.loads(final_text)
                    result['followup']['keys'] = list(shape) if isinstance(shape, dict) else type(shape).__name__
                    if isinstance(shape, dict):
                        result['followup']['action'] = shape.get('action')
                except ValueError:
                    result['followup']['valid_json'] = False
                answer, more_calls = decode_reply(final_text, definitions, final=False)
                result.update(roundtrip_answer=bool(answer), additional_calls=len(more_calls),
                              synthetic_value_in_answer='17' in answer)
    except Exception as exc:
        result.update(error_type=type(exc).__name__, status=getattr(exc, 'status_code', None))
    finally:
        timer.cancel()
        client.close()
    result['elapsed_ms'] = round((monotonic() - started)*1000)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
