"""Build a bounded, read-only Telosia context for chatbot answers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.routes.occupations import (
    get_body_regions,
    get_destinations,
    get_occupation,
)
from app.services.rag_retriever import retrieve_knowledge


KNOWLEDGE_FILE = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "telosia_chat_knowledge.md"
)

OUT_OF_SCOPE_ANSWER = (
    "I can only answer questions supported by Telosia's occupation, "
    "physical-demand exposure, injury-frequency, mobility, and data-source "
    "information."
)

NEEDS_OCCUPATION_ANSWER = (
    "Please select an occupation first so I can answer that question using "
    "Telosia's data."
)

_ALLOWED_TERMS = {
    "telosia", "occupation", "occupations", "job", "jobs", "work", "worker",
    "task", "tasks", "career", "body", "back", "shoulder", "arm", "hand",
    "wrist", "knee", "leg", "feet", "foot", "fall", "hazard", "exposure",
    "physical", "demand", "bending", "twisting", "lifting", "standing",
    "sitting", "walking", "injury", "injuries", "claim", "claims",
    "frequency", "rate", "million", "hours", "year", "years", "mobility",
    "move", "moving", "destination", "destinations", "source", "sources",
    "data", "dataset", "information", "metric", "measure", "meaning",
    "available", "published", "beta", "anzsco", "bohd", "wcifr",
    "role", "roles", "choose", "suitable", "issue", "issues",
    "problem", "problems", "difficulty", "limited", "limitation",
    "impairment", "pain", "avoid", "lower", "higher", "high", "low",
    "use", "using", "lumbar", "waist", "balance", "climbing",
}

_GREETING_TERMS = {"hello", "hi", "hey", "help"}

_OUT_OF_SCOPE_TERMS = {
    "weather", "recipe", "football", "soccer", "cricket", "lottery",
    "president", "prime minister", "movie", "music", "joke", "homework",
    "bitcoin", "share price",
}

_MEDICAL_TERMS = {
    "diagnose", "diagnosis", "treatment", "medicine", "medication",
    "symptom", "symptoms", "doctor", "hospital", "emergency",
}

_OCCUPATION_REQUIRED_TERMS = {
    "exposure", "frequency", "rate", "mobility", "destination",
    "destinations",
}

_OCCUPATION_REQUIRED_PHRASES = {
    "this occupation", "this job", "selected occupation", "selected job",
}


def _normalise_words(message: str) -> set[str]:
    cleaned = "".join(
        character.lower() if character.isalnum() else " "
        for character in message
    )
    return set(cleaned.split())


def is_in_scope(message: str) -> bool:
    """Conservatively allow only questions covered by Telosia data."""

    lowered = message.lower()
    words = _normalise_words(message)
    out_of_scope_words = {
        term for term in _OUT_OF_SCOPE_TERMS if " " not in term
    }
    out_of_scope_phrases = {
        term for term in _OUT_OF_SCOPE_TERMS if " " in term
    }
    if words & out_of_scope_words:
        return False
    if any(phrase in lowered for phrase in out_of_scope_phrases):
        return False
    if words & _MEDICAL_TERMS:
        return False
    return bool(words & (_ALLOWED_TERMS | _GREETING_TERMS))


def requires_occupation(message: str) -> bool:
    lowered = message.lower()
    words = _normalise_words(message)
    return bool(words & _OCCUPATION_REQUIRED_TERMS) or any(
        phrase in lowered
        for phrase in _OCCUPATION_REQUIRED_PHRASES
    )


def calculate_frequency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate all-year and last-five-year means from published rates."""

    published = [
        {
            "financial_year": row["financial_year"],
            "frequency_rate": float(row["frequency_rate"]),
            "is_preliminary": bool(row["is_preliminary"]),
            "source_id": int(row["source_reference_id"]),
        }
        for row in rows
        if row["frequency_rate"] is not None
    ]
    published.sort(key=lambda row: row["financial_year"])
    latest_five = published[-5:]

    def mean(values: list[dict[str, Any]]) -> float | None:
        if not values:
            return None
        return round(
            sum(row["frequency_rate"] for row in values) / len(values),
            2,
        )

    return {
        "definition": "Lost-time workers' compensation claims per million hours worked.",
        "all_years_average": mean(published),
        "all_years_period": (
            [published[0]["financial_year"], published[-1]["financial_year"]]
            if published else None
        ),
        "last_five_years_average": mean(latest_five),
        "last_five_financial_years": [
            row["financial_year"] for row in latest_five
        ],
        "published_year_count": len(published),
        "suppressed_or_missing_year_count": len(rows) - len(published),
        "source_ids": sorted({row["source_id"] for row in published}),
    }


_INJURY_FREQUENCY_QUERY = text(
    """
    SELECT
        financial_year,
        frequency_rate,
        is_preliminary,
        source_reference_id
    FROM telosia.injury_frequency
    WHERE occupation_id = :occupation_id
      AND measure_type = 'workers_compensation_injury_frequency_rate'
    ORDER BY financial_year
    """
)

_SOURCE_QUERY = text(
    """
    SELECT
        source_reference_id AS source_id,
        publisher,
        dataset_title,
        dataset_url,
        licence,
        coverage_period_start,
        coverage_period_end,
        retrieval_date,
        plain_language_note
    FROM telosia.source_reference
    WHERE source_reference_id IN :source_ids
    ORDER BY source_reference_id
    """
).bindparams(bindparam("source_ids", expanding=True))


def _load_knowledge() -> str:
    return KNOWLEDGE_FILE.read_text(encoding="utf-8")


def load_supporting_sources(
    db: Session,
    source_ids: set[int],
) -> list[dict[str, Any]]:
    """Load public source metadata for a bounded set of source IDs."""

    if not source_ids:
        return []
    return [
        dict(row)
        for row in db.execute(
            _SOURCE_QUERY,
            {"source_ids": sorted(source_ids)},
        ).mappings().all()
    ]


def build_chat_context(
    db: Session,
    occupation_id: int | None,
    question: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return prompt context and supporting source metadata."""

    retrieved_knowledge = retrieve_knowledge(
        question=question,
        top_k=5,
    )

    context: dict[str, Any] = {
        "site_knowledge": _load_knowledge(),
        "occupation": None,
        "answer_scope": {
            "occupation_selected": occupation_id is not None,
            "instruction": (
                "Answer for the selected occupation and name it explicitly."
                if occupation_id is not None
                else (
                    "No occupation was selected. Answer only as a general "
                    "hazard-to-body mapping and state that it is not an "
                    "occupation-specific result."
                )
            ),
        },
        "retrieved_knowledge": retrieved_knowledge,
    }
    source_ids: set[int] = set()

    if occupation_id is not None:
        occupation = get_occupation(occupation_id=occupation_id, db=db)
        body_regions = get_body_regions(occupation_id=occupation_id, db=db)
        destinations = get_destinations(
            occupation_id=occupation_id,
            sort="most_common",
            compare_region=None,
            show_harder_moves=True,
            states=None,
            sa4_regions=None,
            db=db,
        )

        frequency_rows = [
            dict(row)
            for row in db.execute(
                _INJURY_FREQUENCY_QUERY,
                {"occupation_id": occupation_id},
            ).mappings().all()
        ]
        frequency = calculate_frequency_summary(frequency_rows)

        source_ids.update(frequency["source_ids"])
        source_ids.update(
            destination["source_id"]
            for destination in destinations["destinations"]
        )

        hazard_source_rows = db.execute(
            text(
                """
                SELECT DISTINCT source_reference_id
                FROM telosia.hazard_exposure
                WHERE occupation_id = :occupation_id
                """
            ),
            {"occupation_id": occupation_id},
        ).scalars().all()
        source_ids.update(int(source_id) for source_id in hazard_source_rows)

        task_source_rows = db.execute(
            text(
                """
                SELECT DISTINCT source_reference_id
                FROM telosia.occupation_task
                WHERE occupation_id = :occupation_id
                """
            ),
            {"occupation_id": occupation_id},
        ).scalars().all()
        source_ids.update(int(source_id) for source_id in task_source_rows)

        context["occupation"] = {
            "profile": occupation,
            "physical_demand_exposure": body_regions,
            "injury_frequency": frequency,
            "mobility": destinations,
        }

    if not source_ids and any(
        document.get("document_type")
        in {"hazard_body_association", "body_part_hazards"}
        for document in retrieved_knowledge
    ):
        source_ids.update(
            int(source_id)
            for source_id in db.execute(
                text(
                    "SELECT source_reference_id "
                    "FROM telosia.source_reference "
                    "WHERE dataset_title ILIKE "
                    "'%Beta Occupational Hazards Dataset%'"
                )
            ).scalars().all()
        )

    if not source_ids:
        source_ids.update(
            int(source_id)
            for source_id in db.execute(
                text(
                    "SELECT source_reference_id "
                    "FROM telosia.source_reference ORDER BY source_reference_id"
                )
            ).scalars().all()
        )

    sources = load_supporting_sources(db, source_ids)

    context["supporting_sources"] = sources
    return context, sources
