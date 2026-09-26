"""Isolate process-local provider compatibility hints between offline tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_protocol_preferences():
    from app.services.chat_protocol import clear_protocol_preferences
    clear_protocol_preferences()
    yield
    clear_protocol_preferences()
