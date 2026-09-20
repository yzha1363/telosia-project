"""Source (provenance) routes for the Telosia backend.

Implements Epic 6: "Show the source". Every figure the frontend displays
is meant to trace back to a row here - publisher, dataset, coverage
period, retrieval date, and a plain-language note on what the figure
actually counts (US-6.1, US-6.2).
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.source import Source, SourceListResponse
from database.connection import get_db

router = APIRouter(
    prefix="/sources",
    tags=["Sources"],
)

_SOURCE_COLUMNS = """
    source_reference_id AS source_id,
    publisher,
    dataset_title,
    dataset_url,
    licence,
    coverage_period_start,
    coverage_period_end,
    retrieval_date,
    update_frequency,
    plain_language_note
"""


@router.get("", response_model=SourceListResponse)
def list_sources(db: Session = Depends(get_db)):
    """List every source currently loaded.

    Supports US-6.1. There are 4 sources right now, one per loaded
    dataset (JSA occupation profiles, Safe Work Australia WCIFR, BOHD,
    and JSA occupation mobility) - not one per figure or per table.

    Args:
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: Every source, ordered by ID.
    """

    rows = db.execute(
        text(f"SELECT {_SOURCE_COLUMNS} FROM telosia.source_reference ORDER BY source_reference_id")
    ).mappings().all()

    return {
        "count": len(rows),
        "sources": list(rows),
    }


@router.get("/{source_id}", response_model=Source)
def get_source(
    source_id: int = Path(..., description="Source ID, as returned in a figure's source_id."),
    db: Session = Depends(get_db),
):
    """Look up a single source by ID.

    Supports US-6.1 and US-6.2: this is what a "where does this number
    come from" tap opens. plain_language_note is the AC6.2 field -
    verified under 60 words for every currently loaded source (longest
    is 19), not just assumed to fit.

    Args:
        source_id: The source's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: The source's full provenance record.

    Raises:
        HTTPException: 404 if no source exists with that ID.
    """

    row = db.execute(
        text(f"SELECT {_SOURCE_COLUMNS} FROM telosia.source_reference WHERE source_reference_id = :source_id"),
        {"source_id": source_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No source found with id {source_id}.",
        )

    return dict(row)
