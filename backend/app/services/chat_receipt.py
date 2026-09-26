"""Signed short-lived turn metadata, without storing user text or query rows."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

_KEY = os.getenv('CHAT_CONTEXT_SIGNING_KEY', '').encode() or secrets.token_bytes(32)


def issue_receipt(result: dict) -> str:
    payload = {'status': result['status'], 'request_id': result['request_id'],
               'datasets': list(dict.fromkeys(q['dataset'] for q in result.get('data_queries', [])))[:12],
               'issued_at': int(time.time())}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()
    return body + '.' + hmac.new(_KEY, body.encode(), hashlib.sha256).hexdigest()


def verify_receipt(token: str | None) -> dict | None:
    if not token or len(token) > 6000:
        return None
    try:
        body, signature = token.split('.')
        expected = hmac.new(_KEY, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body))
        age = time.time() - payload['issued_at']
        return payload if 0 <= age <= 3600 else None
    except (ValueError, KeyError, TypeError):
        return None
