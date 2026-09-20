"""Cross-occupation search using Sam's mapping, RAG IDs, and BOHD scores."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

# Sam's existing mapping remains in place and is consumed read-only here.
from app.routes.occupations import BODY_REGION_MAPPING
from app.services.chat_intent import OccupationDemandIntent
from app.services.rag_retriever import DEFAULT_RAG_DIRECTORY


class OccupationDemandConfigurationError(RuntimeError):
    """Raised when Sam's mapping cannot be linked to approved RAG IDs."""


_OCCUPATION_EXPOSURE_QUERY = text(
    """
    SELECT
        o.occupation_id,
        o.occupation_title,
        hv.hazard_variable_id,
        hv.hazard_variable,
        he.exposure_score,
        he.source_reference_id
    FROM telosia.occupation AS o
    JOIN telosia.hazard_exposure AS he
        ON he.occupation_id = o.occupation_id
    JOIN telosia.hazard_variable AS hv
        ON hv.hazard_variable_id = he.hazard_variable_id
    WHERE o.is_profile_occupation = TRUE
      AND hv.hazard_variable_id IN :hazard_ids
    ORDER BY o.occupation_id, hv.hazard_variable_id
    """
).bindparams(bindparam("hazard_ids", expanding=True))


def _rag_documents_path() -> Path:
    configured = os.getenv("RAG_INDEX_DIRECTORY")
    directory = Path(configured) if configured else DEFAULT_RAG_DIRECTORY
    return directory / "documents.jsonl"


@lru_cache(maxsize=1)
def _approved_rag_hazard_ids() -> dict[str, int]:
    """Return approved hazard names keyed to their RAG metadata IDs."""

    path = _rag_documents_path()
    if not path.exists():
        raise OccupationDemandConfigurationError(
            f"RAG documents file is missing: {path}"
        )

    catalog: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        document = json.loads(line)
        if document.get("document_type") != "hazard_body_association":
            continue
        metadata = document.get("metadata", {})
        if metadata.get("review_status") != "approved":
            continue
        name = metadata.get("hazard_variable")
        hazard_id = metadata.get("hazard_variable_id")
        if not isinstance(name, str) or hazard_id is None:
            continue
        numeric_id = int(hazard_id)
        existing = catalog.get(name)
        if existing is not None and existing != numeric_id:
            raise OccupationDemandConfigurationError(
                f"Conflicting RAG hazard IDs for {name}."
            )
        catalog[name] = numeric_id

    return catalog


def resolve_region_hazards(
    regions: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    """Link Sam's named variables to approved RAG hazard IDs."""

    rag_catalog = _approved_rag_hazard_ids()
    resolved: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []

    for region in regions:
        variables = BODY_REGION_MAPPING.get(region)
        if variables is None:
            raise OccupationDemandConfigurationError(
                f"Unsupported body region: {region}"
            )
        resolved[region] = []
        for variable in variables:
            hazard_id = rag_catalog.get(variable)
            if hazard_id is None:
                missing.append(variable)
                continue
            resolved[region].append(
                {
                    "hazard_variable_id": hazard_id,
                    "hazard_variable": variable,
                }
            )

    if missing:
        raise OccupationDemandConfigurationError(
            "Sam mapping variables are missing approved RAG IDs: "
            + ", ".join(sorted(set(missing)))
        )
    return resolved


def rank_occupations_by_body_demand(
    db: Session,
    intent: OccupationDemandIntent,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], set[int]]:
    """Rank profile occupations by maximum BOHD exposure for each region."""

    resolved = resolve_region_hazards(intent.regions)
    region_hazard_ids = {
        region: {
            item["hazard_variable_id"]
            for item in hazards
        }
        for region, hazards in resolved.items()
    }
    all_hazard_ids = sorted(
        set().union(*region_hazard_ids.values())
    )
    rows = db.execute(
        _OCCUPATION_EXPOSURE_QUERY,
        {"hazard_ids": all_hazard_ids},
    ).mappings().all()

    by_occupation: dict[int, dict[str, Any]] = {}
    for row in rows:
        occupation_id = int(row["occupation_id"])
        record = by_occupation.setdefault(
            occupation_id,
            {
                "occupation_id": occupation_id,
                "title": row["occupation_title"],
                "hazards": {},
                "source_ids": set(),
            },
        )
        record["hazards"][int(row["hazard_variable_id"])] = {
            "variable": row["hazard_variable"],
            "score": float(row["exposure_score"]),
        }
        record["source_ids"].add(int(row["source_reference_id"]))

    ranked: list[dict[str, Any]] = []
    source_ids: set[int] = set()
    for record in by_occupation.values():
        region_scores: dict[str, float] = {}
        contributors: list[dict[str, Any]] = []
        complete = True

        for region, hazard_ids in region_hazard_ids.items():
            region_contributors = [
                record["hazards"][hazard_id]
                for hazard_id in hazard_ids
                if hazard_id in record["hazards"]
            ]
            if not region_contributors:
                complete = False
                break
            region_contributors.sort(
                key=lambda item: item["score"],
                reverse=True,
            )
            region_scores[region] = region_contributors[0]["score"]
            contributors.extend(region_contributors)

        # Never treat missing BOHD values as zero, especially for low-demand
        # searches where that would create unsafe false recommendations.
        if not complete:
            continue

        contributors.sort(
            key=lambda item: item["score"],
            reverse=True,
        )
        leading_demands = []
        seen_variables = set()
        for contributor in contributors:
            if contributor["variable"] in seen_variables:
                continue
            seen_variables.add(contributor["variable"])
            leading_demands.append(contributor["variable"])
            if len(leading_demands) == 3:
                break

        overall_score = max(region_scores.values())
        ranked.append(
            {
                "occupation_id": record["occupation_id"],
                "title": record["title"],
                "comparison": (
                    "lower" if intent.direction == "low" else "higher"
                ),
                "relative_exposure_score": round(overall_score),
                "body_regions": list(intent.regions),
                "leading_demands": leading_demands,
            }
        )
        source_ids.update(record["source_ids"])

    if intent.direction == "high":
        ranked.sort(
            key=lambda item: (
                -item["relative_exposure_score"],
                item["title"],
            )
        )
    else:
        ranked.sort(
            key=lambda item: (
                item["relative_exposure_score"],
                item["title"],
            )
        )
    return ranked[: max(1, min(limit, 10))], source_ids


def build_occupation_demand_answer(
    intent: OccupationDemandIntent,
    results: list[dict[str, Any]],
) -> str:
    """Build a bounded explanation; occupation details remain structured."""

    regions = ", ".join(intent.regions)
    if not results:
        return (
            "Telosia does not have complete published occupation exposure "
            f"data for {regions}. Missing values were not treated as zero."
        )

    if intent.direction == "low":
        opening = (
            "I interpreted this as a request to explore occupations with "
            f"lower recorded physical-demand exposure related to {regions}."
        )
    else:
        opening = (
            "Across Telosia's profile occupations, these results have higher "
            f"recorded physical-demand exposure related to {regions}."
        )

    safety = (
        " This comparison does not determine whether a job is medically or "
        "personally suitable for someone."
        if intent.personal_constraint
        else ""
    )
    return (
        f"{opening}{safety}\n\n"
        "Results use the maximum available BOHD score across Telosia's "
        "approved body-region mapping, are rounded to whole numbers, and "
        "exclude occupations with no published measure. BOHD is a beta "
        "dataset constructed partly by mapping selected U.S. O*NET work-"
        "context data to Australian occupations. These are exposure "
        "comparisons, not body-part injury claims."
    )
