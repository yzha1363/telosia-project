"""Request-local cancellation, timing and safe progress events for chat."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Any
from uuid import uuid4

logger = logging.getLogger("uvicorn.error.chat")
EventSink = Callable[[str, dict[str, Any]], None]


class ChatCancelled(RuntimeError):
    pass


class ChatControl:
    """Close this request's model client on disconnect/deadline, never a shared client."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._close: Callable[[], None] | None = None
        self.expired = False
        self.disconnected = False

    def bind(self, close: Callable[[], None]):
        with self._lock:
            self._close = close
            stopped = self._event.is_set()
        if stopped:
            close()

    def cancel(self, *, expired: bool = False):
        with self._lock:
            self.expired = self.expired or expired
            self.disconnected = self.disconnected or not expired
            self._event.set()
            close = self._close
        if close:
            try:
                close()
            except Exception:
                pass

    def is_set(self) -> bool:
        return self._event.is_set()


class ChatTrace:
    def __init__(self, context: dict, sink: EventSink | None = None):
        self.context = context
        self.sink = sink
        self.request_id = context.setdefault("request_id", uuid4().hex)
        self.started = time.monotonic()
        self.timings: list[dict] = []
        context["timings"] = self.timings

    def emit(self, event: str, data: dict):
        if self.sink:
            self.sink(event, {"request_id": self.request_id, **data})

    def status(self, stage: str, message: str):
        self.context["current_stage"] = stage
        self.emit("status", {"stage": stage, "message": message})

    def record(self, stage: str, duration: float, **details):
        entry = {"stage": stage, "elapsed_ms": round(duration * 1000), **details}
        self.timings.append(entry)
        # Only execution metadata: never log questions, answers, rows or keys.
        logger.info("chat_timing request_id=%s stage=%s elapsed_ms=%s round=%s attempt=%s tool=%s outcome=%s event_kind=%s",
                    self.request_id, stage, entry["elapsed_ms"], details.get("round"),
                    details.get("attempt"), details.get("tool"), details.get("outcome"), details.get("event_kind"))
