"""Pydantic response models for the source (provenance) routes."""

from datetime import date

from pydantic import BaseModel


class Source(BaseModel):
    source_id: int
    publisher: str
    dataset_title: str
    dataset_url: str | None = None
    licence: str | None = None
    coverage_period_start: date | None = None
    coverage_period_end: date | None = None
    retrieval_date: date | None = None
    update_frequency: str | None = None
    plain_language_note: str | None = None


class SourceListResponse(BaseModel):
    count: int
    sources: list[Source]
