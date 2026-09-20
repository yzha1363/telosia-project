"""Deterministic English intent parsing for cross-occupation chat searches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OccupationDemandIntent:
    """A bounded request to compare occupations by body-related demand."""

    regions: tuple[str, ...]
    direction: Literal["high", "low"]
    personal_constraint: bool


_BODY_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "Lower back": (
        "lower back",
        "low back",
        "lumbar",
        "waist",
        "back",
    ),
    "Shoulders and upper arms": (
        "shoulder",
        "shoulders",
        "upper arm",
        "upper arms",
        "arm",
        "arms",
    ),
    "Hands and wrists": (
        "hand",
        "hands",
        "wrist",
        "wrists",
        "finger",
        "fingers",
        "thumb",
        "thumbs",
    ),
    "Knees": ("knee", "knees"),
    "Legs and feet": (
        "leg",
        "legs",
        "foot",
        "feet",
        "ankle",
        "ankles",
    ),
    "Whole body and fall risk": (
        "balance",
        "balancing",
        "climbing",
        "fall risk",
        "falling",
    ),
}

_OCCUPATION_SEARCH_PATTERNS = (
    r"\bwhat\s+(?:kind|type)\s+of\s+jobs?\b",
    r"\bwhat\s+jobs?\b",
    r"\bwhich\s+jobs?\b",
    r"\bwhat\s+occupations?\b",
    r"\bwhich\s+occupations?\b",
    r"\bwhat\s+(?:kind|type)\s+of\s+work\b(?!\s+demands?\b)",
    r"\bwhat\s+roles?\b",
    r"\bwhich\s+roles?\b",
    r"\bjobs?\s+(?:should|could|can)\s+i\b",
    r"\boccupations?\s+(?:should|could|can)\s+i\b",
    r"\broles?\s+(?:should|could|can)\s+i\b",
    r"\bjobs?\s+(?:require|use|involve|need)\b",
    r"\boccupations?\s+(?:require|use|involve|need)\b",
    r"\broles?\s+(?:require|use|involve|need)\b",
    r"\b(?:find|show|suggest|list)\s+(?:me\s+)?(?:some\s+)?jobs?\b",
    r"\b(?:find|show|suggest|list)\s+(?:me\s+)?(?:some\s+)?occupations?\b",
    r"\bsuitable\s+(?:jobs?|occupations?|careers?)\b",
    r"\bcareers?\s+(?:should|could|can)\s+i\b",
    r"\bwork\s+(?:should|could|can)\s+i\b",
    r"\bjob\s+options?\b",
    r"\bcareer\s+options?\b",
)

_LOW_EXPOSURE_PATTERNS = (
    r"\bissue(?:s)?\s+(?:with|in)\b",
    r"\bissue(?:s)?\b",
    r"\bproblem(?:s)?\s+(?:with|in)\b",
    r"\bproblem(?:s)?\b",
    r"\bdifficulty\s+(?:with|using|moving)\b",
    r"\btrouble\s+(?:with|using|moving)\b",
    r"\blimited\b",
    r"\blimitation(?:s)?\b",
    r"\bimpairment\b",
    r"\bpain\b",
    r"\binjury\b",
    r"\binjured\b",
    r"\bavoid\b",
    r"\blower\s+exposure\b",
    r"\blow\s+exposure\b",
    r"\bless\s+(?:use|demand|exposure)\b",
    r"\bminimal\s+(?:use|demand|exposure)\b",
    r"\b(?:cannot|can't|struggle\s+to)\s+(?:use|move|stand|walk|bend)\b",
)


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(rf"\b{re.escape(alias)}\b", text) is not None


def parse_occupation_demand_intent(
    message: str,
) -> OccupationDemandIntent | None:
    """Recognise English requests to rank jobs by body-related exposure."""

    normalised = " ".join(message.lower().split())
    if not any(
        re.search(pattern, normalised)
        for pattern in _OCCUPATION_SEARCH_PATTERNS
    ):
        return None

    regions = tuple(
        region
        for region, aliases in _BODY_REGION_ALIASES.items()
        if any(_contains_alias(normalised, alias) for alias in aliases)
    )
    if not regions:
        return None

    personal_constraint = any(
        re.search(pattern, normalised)
        for pattern in _LOW_EXPOSURE_PATTERNS
    )
    return OccupationDemandIntent(
        regions=regions,
        direction="low" if personal_constraint else "high",
        personal_constraint=personal_constraint,
    )
