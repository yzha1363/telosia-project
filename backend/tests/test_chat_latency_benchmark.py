"""The opt-in live benchmark itself is tested with no network access."""

from types import SimpleNamespace as NS

from scripts.benchmark_chat_latency import measure, summarise


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self):
        return iter(self.chunks)
    def close(self):
        self.closed = True


def test_benchmark_records_shape_not_answer_or_reasoning():
    stream = FakeStream([
        NS(choices=[NS(delta=NS(reasoning_content="SECRET REASONING"), finish_reason=None)]),
        NS(choices=[NS(delta=NS(content="PRIVATE ANSWER"), finish_reason="stop")]),
    ])
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return stream
    result = measure(NS(chat=NS(completions=NS(create=create)), close=lambda: None), {}, 5)
    assert result["status"] == "ok"
    assert result["first_event_ms"] is not None and result["first_text_ms"] is not None
    assert "SECRET" not in str(result) and "PRIVATE" not in str(result)
    assert len(requests) == 1 and stream.closed


def test_failure_duration_is_not_reported_as_successful_latency():
    rows = [
        {"case": "minimal", "effort": "default", "status": "ok", "total_ms": 100, "tool_names": []},
        {"case": "minimal", "effort": "default", "status": "ok", "total_ms": 200, "tool_names": []},
        {"case": "minimal", "effort": "default", "status": "error", "total_ms": 45000, "tool_names": []},
    ]
    result = summarise(rows)[0]
    assert result["attempts"] == 3 and result["failures"] == 1
    assert result["successful_median_ms"] == 150
    assert result["successful_max_ms"] == 200
    assert summarise(rows[2:])[0]["successful_median_ms"] is None
