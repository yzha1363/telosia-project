"""Request and response models for the Telosia chatbot."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)
    occupation_id: int | None = Field(default=None, gt=0)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank.")
        return value


class ChatSource(BaseModel):
    source_id: int
    publisher: str
    dataset_title: str
    dataset_url: str | None = None
    licence: str | None = None
    coverage_period_start: date | None = None
    coverage_period_end: date | None = None
    retrieval_date: date | None = None
    plain_language_note: str | None = None


class ChatOccupationResult(BaseModel):
    occupation_id: int
    title: str
    comparison: Literal["higher", "lower"]
    relative_exposure_score: int = Field(ge=0, le=100)
    body_regions: list[str]
    leading_demands: list[str]


class ChatResponse(BaseModel):
    status: Literal[
        "answered",
        "out_of_scope",
        "needs_occupation",
        "temporarily_unavailable",
    ]
    answer: str
    occupation_id: int | None = None
    occupation_results: list[ChatOccupationResult] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
