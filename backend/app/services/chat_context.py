"""Lightweight conversation context; numeric data is fetched on demand by tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

_SOURCE_QUERY = text("""
    SELECT source_reference_id AS source_id, publisher, dataset_title, dataset_url,
           licence, coverage_period_start, coverage_period_end, retrieval_date,
           plain_language_note
    FROM telosia.source_reference
    WHERE source_reference_id IN :source_ids
    ORDER BY source_reference_id
""").bindparams(bindparam("source_ids", expanding=True))


def load_supporting_sources(db: Session, source_ids: set[int]) -> list[dict[str, Any]]:
    if not source_ids:
        return []
    return [dict(row) for row in db.execute(
        _SOURCE_QUERY, {"source_ids": sorted(source_ids)}
    ).mappings().all()]


def build_chat_context(occupation_id: int | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prepare selection metadata without file or database dependencies."""
    return {"selected_occupation_id": occupation_id}, []
