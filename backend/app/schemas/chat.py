"""Request and response models for the Telosia chatbot."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    occupation_id: int | None = Field(default=None, gt=0)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=10)
    page_context: str | None = Field(default=None, max_length=120)
    extended_analysis: bool = False
    previous_turn_token: str | None = Field(default=None, max_length=6000)

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


class ChatDataQuery(BaseModel):
    query_id: str
    dataset: str
    row_count: int
    truncated: bool


class ChatResponse(BaseModel):
    status: Literal[
        "answered",
        "partial",
        "out_of_scope",
        "needs_occupation",
        "temporarily_unavailable",
    ]
    answer: str
    occupation_id: int | None = None
    occupation_results: list[ChatOccupationResult] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
    data_queries: list[ChatDataQuery] = Field(default_factory=list)
    data_results: list[dict] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    request_id: str | None = None
    elapsed_ms: int | None = None
    error_code: str | None = None
    error_stage: str | None = None
    timings: list[dict] = Field(default_factory=list)
    turn_token: str | None = None
