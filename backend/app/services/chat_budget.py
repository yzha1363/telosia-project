"""One bounded deadline contract shared by the route and model loop."""
import os
from dataclasses import dataclass


def setting(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def model_call_timeout() -> int:
    """Share the per-call limit between client defaults and request overrides."""
    return setting("NVIDIA_CHAT_TIMEOUT_SECONDS", 60, 10, 120)


@dataclass(frozen=True)
class ChatBudget:
    total: int
    reserve: int

    @classmethod
    def configured(cls, extended: bool = False):
        normal = setting('CHAT_TOTAL_TIMEOUT_SECONDS', 240, 60, 300)
        total = max(normal, setting('CHAT_EXTENDED_TIMEOUT_SECONDS', 300, 60, 300)) if extended else normal
        return cls(total, min(total // 2, setting('CHAT_SUMMARY_RESERVE_SECONDS', 60, 15, 90)))

    def should_summarize(self, remaining: float) -> bool:
        return remaining <= self.reserve + 1

    def call_timeout(self, remaining: float, per_call: float, final: bool) -> float:
        return max(0.1, min(per_call, remaining if final else remaining - self.reserve))
