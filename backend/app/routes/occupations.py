"""Occupation search routes for the Telosia backend.

This module implements occupation-related API functionality required by
Epic 1: "Say what you do".

The first supported user story is US-1.1:
"Search for my job in plain language".

Users search using everyday occupation names rather than ASCO2 or ANZSCO
classification codes.
"""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.occupation import (
    AiExposureResponse,
    BodyRegionsResponse,
    Destination,
    DestinationDetail,
    DestinationsResponse,
    OccupationDetail,
    OccupationSearchResponse,
    PayGapResponse,
)
from app.services.injury_model import score_occupations
from database.connection import get_db


# ---------------------------------------------------------------------------
# Router configuration
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/occupations",
    tags=["Occupations"],
)


# ---------------------------------------------------------------------------
# US-1.1 - Search for occupation in plain language
# ---------------------------------------------------------------------------

# Tier 2: full-text search, for multi-word / voice-style queries that don't
# appear as a literal substring anywhere (e.g. "I work as an electrician",
# "aged care worker" against an alias reading "Registered Nurse (Aged
# Care)"). Only reached when the tier-1 exact/prefix/substring match above
# finds nothing.
#
# Terms are OR-combined, not AND-combined (plainto_tsquery/websearch_to_
# tsquery both AND by default and were tested to return zero rows for
# "I work as an electrician" - "work" doesn't appear in any title/alias,
# so an AND search fails outright). English stop words ("i", "as", "an")
# are still handled correctly - to_tsquery's 'english' config drops them
# as no-ops within the OR chain, not something handled in Python.
_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")


def _build_or_tsquery(search_term: str) -> str | None:
    """Turn user input into a safe, OR-combined raw tsquery string.

    tsquery's mini-language treats &, |, !, (, ), : as operators - passed
    through unescaped, a raw "&" or unbalanced "(" in user input would
    raise a Postgres syntax error rather than just fail to match.

    Splits on any run of non-alphanumeric characters, not just
    whitespace - "IT/support (urgent)" must become the two words
    ["IT", "support"] (plus "urgent"), not one garbled "ITsupport" token.
    An earlier version of this only split on whitespace and stripped
    punctuation from within each word, which is exactly the bug that
    would have produced ("IT/support" -> "ITsupport"); caught by testing
    real punctuated input before shipping, not by inspection.
    """
    tokens = [token for token in _TOKEN_RE.split(search_term) if token]
    return " | ".join(tokens) if tokens else None


_FULLTEXT_SEARCH_QUERY = text(
    """
    SELECT
        occupation_id,
        title
    FROM (
        SELECT
            o.occupation_id,
            o.occupation_title AS title,
            to_tsvector(
                'english',
                o.occupation_title || ' ' || COALESCE(
                    (
                        SELECT string_agg(oa.alias_text, ' ')
                        FROM telosia.occupation_alias AS oa
                        WHERE oa.occupation_id = o.occupation_id
                    ),
                    ''
                )
            ) AS document
        FROM telosia.occupation AS o
    ) AS occupation_documents
    CROSS JOIN to_tsquery('english', :tsquery) AS search_query
    WHERE document @@ search_query
    ORDER BY ts_rank(document, search_query) DESC, title
    LIMIT 10
    """
)

# Tier 3: trigram similarity, for single-word typos/misspellings of an
# occupation's TITLE (e.g. "nurrse", "electrican", "plummer") - reached
# only when both tier 1 and tier 2 find nothing. Deliberately NOT trusted
# for multi-word voice-style queries: tested directly against "i am a
# nurse" and it scored the correct answer (Registered Nurses) at only
# 0.19 similarity, below any safe threshold - that failure mode is tier
# 2's job, not this one's.
#
# Deliberately title-only, not title+alias. Comparing against every
# individual alias too was tried and reverted after live testing found
# real, confusing false positives: "plummer" matched "Music
# Professionals" (via its "Drummer" alias, 0.333 similarity - a pure
# coincidental collision, the same dynamic as "cop"/Cooks, just recurring
# because short alias strings have few distinguishing trigrams) ahead of
# "Plumbers" itself. Comparing against one combined title+aliases
# document per occupation instead of each alias individually was also
# tried - that made every score collapse toward zero and penalised
# occupations with the richest alias coverage the most, so it isn't used
# either. Title-only trades some recall (a typo of a specific alias
# phrase, rather than the title, won't be caught here) for not
# surfacing results like that.
#
# Threshold calibrated against real data, not guessed: genuine typos of a
# title score 0.29-0.57 ("nurrse"->Nurse Managers 0.294, "plummer"->
# Plumbers 0.308, "electrican"->Electricians 0.5, "acountant"->
# Accountants 0.571), while the known coincidental short-string collision
# "cop"->Cooks scores 0.25. 0.28 sits cleanly between them.
_TRIGRAM_SIMILARITY_THRESHOLD = 0.28

_TRIGRAM_SEARCH_QUERY = text(
    """
    SELECT
        occupation_id,
        title
    FROM (
        SELECT
            o.occupation_id,
            o.occupation_title AS title,
            similarity(lower(o.occupation_title), lower(:search_term)) AS title_similarity
        FROM telosia.occupation AS o
    ) AS scored_occupations
    WHERE title_similarity >= :min_similarity
    ORDER BY title_similarity DESC, title
    LIMIT 10
    """
)

_FULLTEXT_MATCH_MESSAGE = "No exact match found - showing closely related results."
_TRIGRAM_MATCH_MESSAGE = "No exact match found - showing similarly spelled results."
_NO_MATCH_MESSAGE = "No matching occupation found. Try another job title."

# AC1.1-b's zero-result fallback: the few most claimed physically
# demanding occupations, offered as selectable alternatives when a
# search genuinely matches nothing (all three tiers above). "Most
# claimed" is real WCIFR injury-frequency data (the same data that
# powers Epic 2), never fabricated - averaged across every non-
# suppressed financial year on record for that occupation. Requires at
# least 8 of the 10 loaded years (339 of ~356 occupations with any real
# data clear this bar) so an occupation with only 2-3 years on record -
# and no way to know if that's typical for it - can't dominate the list
# on a thin sample.
_TOP_CLAIMS_HEAVY_OCCUPATIONS = text(
    """
    SELECT
        o.occupation_id,
        o.occupation_title AS title
    FROM telosia.injury_frequency AS f
    JOIN telosia.occupation AS o
        ON o.occupation_id = f.occupation_id
    WHERE
        f.is_suppressed = FALSE
        AND f.frequency_rate IS NOT NULL
    GROUP BY
        o.occupation_id,
        o.occupation_title
    HAVING COUNT(*) >= 8
    ORDER BY
        AVG(f.frequency_rate) DESC,
        title
    LIMIT 5
    """
)

_FALLBACK_SUGGESTIONS_MESSAGE = (
    "No matching occupation found for \"{query}\". Here are some of the "
    "most frequently claimed physically demanding occupations - try a "
    "different word, or pick one of these."
)


@router.get("/search", response_model=OccupationSearchResponse)
def search_occupations(
    q: str = Query(
        ...,
        min_length=3,
        max_length=100,
        description="Plain-language occupation search term.",
    ),
    db: Session = Depends(get_db),
):
    """Search for occupations using plain-language aliases.

    This endpoint supports US-1.1. Three tiers are tried in order, each
    only reached if the previous one found nothing:

    1. Exact / prefix / substring match against occupation titles and
       aliases (handles most typed queries, including single-word
       synonyms once loaded as an alias).
    2. Full-text search (multi-word / voice-style queries that don't
       appear as a literal substring, e.g. "I work as an electrician").
    3. Trigram similarity (single-word typos/misspellings, e.g.
       "nurrse", "plummer").

    If all three tiers find nothing (AC1.1-b), the response carries
    fallback_suggestions: the few most claimed physically demanding
    occupations, from real WCIFR injury-frequency data - never blended
    into matches, since they didn't match the query, only offered as a
    starting point.

    Args:
        q:
            User-entered occupation text. At least three characters are
            required.

        db:
            SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: Search term, number of matches, matching occupations, and
        (for tier 2/3 results) a message noting the match wasn't exact.
        For a genuine zero-result search, matches is empty and
        fallback_suggestions carries the AC1.1-b alternatives instead.
    """

    search_term = q.strip()

    if len(search_term) < 3:
        return {
            "query": search_term,
            "count": 0,
            "matches": [],
            "fallback_available": False,
            "message": _NO_MATCH_MESSAGE,
        }

    # Escape LIKE metacharacters in the user-supplied term so a literal
    # "%" or "_" in a search term is not treated as a SQL wildcard.
    escaped_term = (
        search_term
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )

    query = text(
    """
    SELECT
        occupation_id,
        title
    FROM (
        SELECT
            o.occupation_id,
            o.occupation_title AS title,
            MIN(
                CASE
                    WHEN LOWER(oa.alias_text) = LOWER(:exact_term) THEN 1
                    WHEN LOWER(oa.alias_text) LIKE LOWER(:starts_with) ESCAPE '\\' THEN 2
                    WHEN LOWER(o.occupation_title) = LOWER(:exact_term) THEN 1
                    WHEN LOWER(o.occupation_title) LIKE LOWER(:starts_with) ESCAPE '\\' THEN 2
                    ELSE 3
                END
            ) AS search_rank
        FROM telosia.occupation AS o
        LEFT JOIN telosia.occupation_alias AS oa
            ON oa.occupation_id = o.occupation_id
        WHERE
            LOWER(oa.alias_text) LIKE LOWER(:search_pattern) ESCAPE '\\'
            OR LOWER(o.occupation_title) LIKE LOWER(:search_pattern) ESCAPE '\\'
        GROUP BY
            o.occupation_id,
            o.occupation_title
    ) AS ranked_occupations
    ORDER BY
        search_rank,
        title
    LIMIT 10
    """
    )

    result = db.execute(
        query,
        {
            "search_pattern": f"%{escaped_term}%",
            "starts_with": f"{escaped_term}%",
            "exact_term": search_term,
        },
    )

    matches = [
        dict(row)
        for row in result.mappings()
    ]

    if matches:
        return {
            "query": search_term,
            "count": len(matches),
            "matches": matches,
            "fallback_available": True,
        }

    # Tier 2: full-text search - multi-word / voice-style queries that
    # don't appear as a literal substring anywhere.
    tsquery = _build_or_tsquery(search_term)
    if tsquery:
        result = db.execute(
            _FULLTEXT_SEARCH_QUERY,
            {"tsquery": tsquery},
        )
        matches = [dict(row) for row in result.mappings()]

        if matches:
            return {
                "query": search_term,
                "count": len(matches),
                "matches": matches,
                "fallback_available": True,
                "message": _FULLTEXT_MATCH_MESSAGE,
            }

    # Tier 3: trigram similarity - single-word typos/misspellings.
    result = db.execute(
        _TRIGRAM_SEARCH_QUERY,
        {
            "search_term": search_term,
            "min_similarity": _TRIGRAM_SIMILARITY_THRESHOLD,
        },
    )
    matches = [dict(row) for row in result.mappings()]

    if matches:
        return {
            "query": search_term,
            "count": len(matches),
            "matches": matches,
            "fallback_available": True,
            "message": _TRIGRAM_MATCH_MESSAGE,
        }

    # AC1.1-b: all three tiers found nothing for this term specifically -
    # offer the top claims-heavy occupations as a starting point instead
    # of leaving the user with an empty screen. These are not matches
    # for the query (matches stays [] - nothing matched), so they're
    # returned separately as fallback_suggestions, never blended into
    # matches where they could be mistaken for real search results.
    fallback_rows = db.execute(_TOP_CLAIMS_HEAVY_OCCUPATIONS).mappings().all()
    fallback_suggestions = [dict(row) for row in fallback_rows]

    return {
        "query": search_term,
        "count": 0,
        "matches": [],
        "fallback_available": bool(fallback_suggestions),
        "fallback_suggestions": fallback_suggestions,
        "message": (
            _FALLBACK_SUGGESTIONS_MESSAGE.format(query=search_term)
            if fallback_suggestions
            else _NO_MATCH_MESSAGE
        ),
    }


# ---------------------------------------------------------------------------
# US-1.2 - Confirm or correct my selected job
# ---------------------------------------------------------------------------

@router.get("/{occupation_id}", response_model=OccupationDetail)
def get_occupation(
    occupation_id: int = Path(
        ...,
        description="Occupation ID returned by /occupations/search.",
    ),
    db: Session = Depends(get_db),
):
    """Look up a single occupation by ID.

    This endpoint supports US-1.2: after a user selects a match from
    search, the frontend confirms the selection by re-fetching it here
    before loading any risk data for it.

    Args:
        occupation_id: The occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: The occupation's ID, title, aliases, description, tasks,
        and (from occupation_profile, where one exists) median weekly
        earnings, part-time share and women's share. description/tasks
        are null/empty and the profile fields are null for the 43
        source-only occupation codes with no JSA profile - never a
        fabricated placeholder.

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    # Aliases and tasks are both one-to-many from occupation, so a single
    # LEFT JOIN to both (with a GROUP BY) would fan out into every
    # alias/task combination and corrupt both array_aggs. Scalar
    # subqueries keep each aggregation independent. occupation_profile is
    # one-to-one (at most one row per occupation), so it's a plain LEFT
    # JOIN.
    query = text(
        """
        SELECT
            o.occupation_id,
            o.occupation_title AS title,
            o.occupation_description AS description,
            COALESCE(
                (
                    SELECT array_agg(oa.alias_text)
                    FROM telosia.occupation_alias AS oa
                    WHERE oa.occupation_id = o.occupation_id
                ),
                ARRAY[]::text[]
            ) AS aliases,
            COALESCE(
                (
                    SELECT array_agg(ot.task_text ORDER BY ot.task_order)
                    FROM telosia.occupation_task AS ot
                    WHERE ot.occupation_id = o.occupation_id
                ),
                ARRAY[]::text[]
            ) AS tasks,
            op.median_weekly_earnings,
            op.part_time_share_pct,
            op.female_share_pct,
            op.source_reference_id AS profile_source_id
        FROM telosia.occupation AS o
        LEFT JOIN telosia.occupation_profile AS op
            ON op.occupation_id = o.occupation_id
        WHERE o.occupation_id = :occupation_id
        """
    )

    result = db.execute(query, {"occupation_id": occupation_id})
    row = result.mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No occupation found with id {occupation_id}.",
        )

    return {
        "id": row["occupation_id"],
        "title": row["title"],
        "description": row["description"],
        "aliases": row["aliases"],
        "tasks": row["tasks"],
        "median_weekly_earnings": row["median_weekly_earnings"],
        "part_time_share_pct": row["part_time_share_pct"],
        "female_share_pct": row["female_share_pct"],
        "profile_source_id": row["profile_source_id"],
    }


# ---------------------------------------------------------------------------
# US-3.1 / US-3.2 - See the doors
# ---------------------------------------------------------------------------

_DESTINATIONS_FOR_OCCUPATION = text(
    """
    SELECT
        mf.destination_occupation_id,
        dest.occupation_title AS destination_title,
        SUM(mf.worker_count) AS worker_count,
        MIN(mf.source_reference_id) AS source_reference_id
    FROM telosia.mobility_flow AS mf
    JOIN telosia.occupation AS dest
        ON dest.occupation_id = mf.destination_occupation_id
    WHERE
        mf.is_self_transition = FALSE
        AND mf.source_occupation_id = :occupation_id
    GROUP BY
        mf.destination_occupation_id,
        dest.occupation_title
    ORDER BY
        worker_count DESC
    """
)

_DESTINATIONS_FOR_MINOR_GROUP = text(
    """
    SELECT
        mf.destination_occupation_id,
        dest.occupation_title AS destination_title,
        SUM(mf.worker_count) AS worker_count,
        MIN(mf.source_reference_id) AS source_reference_id
    FROM telosia.mobility_flow AS mf
    JOIN telosia.occupation AS src
        ON src.occupation_id = mf.source_occupation_id
    JOIN telosia.occupation AS dest
        ON dest.occupation_id = mf.destination_occupation_id
    WHERE
        mf.is_self_transition = FALSE
        AND LEFT(src.anzsco_code, 3) = :minor_group
        AND mf.source_occupation_id != :occupation_id
    GROUP BY
        mf.destination_occupation_id,
        dest.occupation_title
    ORDER BY
        worker_count DESC
    """
)

# The page size returned to the frontend, and the size of the candidate
# pool every Iteration 2 sort/filter below operates within. Share itself
# is still computed (in _rank_destinations) against the TRUE total
# across every destination before this cap is applied - slicing before
# that was a real, shipped bug once (comparing the list endpoint's share
# for a transition against the detail endpoint's share for the same
# pair caught it: 30.8% vs the correct 22.5%).
#
# The cap is applied to the real-transition-share ranking specifically,
# before any other sort runs - not after. Tried it the other way first
# (sort the full destination list, cap to 10 afterward) and it broke the
# product's own promise ("every row is a move people actually made...
# not careers advice"): sorting the full list by kindest_overall
# surfaced occupations like "Psychologists and Psychotherapists" that
# essentially nobody from a given occupation actually moved into,
# replacing the real top-10 destinations entirely. Every sort/filter
# here re-orders or narrows that same top-10-by-real-share set; none of
# them widen it.
_MAX_DESTINATIONS_RETURNED = 10


def _get_occupation_or_404(db: Session, occupation_id: int):
    row = db.execute(
        text(
            "SELECT occupation_id, occupation_title, anzsco_code "
            "FROM telosia.occupation WHERE occupation_id = :occupation_id"
        ),
        {"occupation_id": occupation_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No occupation found with id {occupation_id}.",
        )
    return row


def _rank_destinations(rows):
    """Attach a share (% of the TRUE total worker_count, across every
    destination) and a tag to every row - the full set, not a top-10
    slice. Tag reflects each destination's true rank in this base
    most-common-move order regardless of what sort/filter runs
    afterward, matching what's already shipped: "Registered Nurses"
    keeps its "Most common move" tag even when a different sort moves it
    elsewhere in the list.
    """
    total = sum(r["worker_count"] for r in rows)
    ranked = []
    for i, r in enumerate(rows):
        ranked.append({
            "occupation_id": r["destination_occupation_id"],
            "title": r["destination_title"],
            "share": round((r["worker_count"] / total) * 100, 1) if total else 0.0,
            "source_id": r["source_reference_id"],
            "tag": "Most common move" if i == 0 else "Common move",
        })
    return ranked


def _get_destination_occupation_ids(db: Session, occupation) -> list[int]:
    """The same up-to-10 destination occupations get_destinations would
    show for this occupation (including its minor-group fallback for
    the couple of occupations with no direct mobility data), as just a
    list of ids. Used by get_body_regions so its "compared to other
    occupations" percentile matches the actual set of occupations shown
    on the Destinations page, not the whole 401-occupation population -
    same real-top-10 principle as get_destinations' own sort/filter
    pipeline, not a wider or different pool.
    """
    rows = db.execute(
        _DESTINATIONS_FOR_OCCUPATION,
        {"occupation_id": occupation["occupation_id"]},
    ).mappings().all()
    if not rows:
        minor_group = occupation["anzsco_code"][:3]
        rows = db.execute(
            _DESTINATIONS_FOR_MINOR_GROUP,
            {"minor_group": minor_group, "occupation_id": occupation["occupation_id"]},
        ).mappings().all()
    ranked = _rank_destinations(rows)[:_MAX_DESTINATIONS_RETURNED]
    return [r["occupation_id"] for r in ranked]


# ---------------------------------------------------------------------------
# Iteration 2 - destinations list sort/filter (Wenlu's API_REQUIREMENTS.md)
# ---------------------------------------------------------------------------

SortOption = Literal[
    "most_common",
    "kindest_overall",
    "best_relief",
    "highest_pay",
    "most_part_time",
    "most_women",
    "least_automation",
    "a_to_z",
]

_HAZARD_EXPOSURE_FOR_OCCUPATIONS = text(
    """
    SELECT
        he.occupation_id,
        hv.hazard_variable,
        he.exposure_score
    FROM telosia.hazard_exposure AS he
    JOIN telosia.hazard_variable AS hv
        ON hv.hazard_variable_id = he.hazard_variable_id
    WHERE he.occupation_id = ANY(:occupation_ids)
    """
)


def _fetch_exposures(db: Session, occupation_ids: list[int]) -> dict[int, dict[str, float]]:
    """Raw BOHD hazard-exposure scores per occupation, keyed by
    occupation_id -> {hazard_variable: score}. An occupation with no
    BOHD coverage at all is simply absent as a key - never present with
    an empty dict - so callers can tell "no data" apart from "scored"
    with a plain `in`/`.get` check. Shared by the body-load calculation
    below and by the injury-frequency model (app/services/injury_model.py)
    - both need the same raw scores, just aggregated differently.
    """
    if not occupation_ids:
        return {}
    rows = db.execute(
        _HAZARD_EXPOSURE_FOR_OCCUPATIONS, {"occupation_ids": occupation_ids}
    ).mappings().all()
    exposures: dict[int, dict[str, float]] = {}
    for row in rows:
        exposures.setdefault(row["occupation_id"], {})[row["hazard_variable"]] = row["exposure_score"]
    return exposures


def _overall_body_load(body_regions: list[dict]) -> float | None:
    """Mean of every region's score, over regions that have one. Mirrors
    the frontend's regionScore(id, 'overall') in DestinationsView.vue
    exactly, so this field can replace that client-side computation
    without changing a single number shown on screen.
    """
    scores = [r["score"] for r in body_regions if r["score"] is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _body_load_scores(db: Session, occupation_ids: list[int]) -> dict[int, dict]:
    """Batched body-region + overall-load scores for many occupations in
    one query, instead of the N+1 /body-regions calls the frontend
    currently makes per destination to compute the same thing client-
    side. Returns {occupation_id: {"regions": {region: score|None},
    "overall": float|None}}.
    """
    exposures_by_occupation = _fetch_exposures(db, occupation_ids)

    result = {}
    for occupation_id in occupation_ids:
        regions = _calculate_body_regions(exposures_by_occupation.get(occupation_id, {}))
        result[occupation_id] = {
            "regions": {r["region"]: r["score"] for r in regions},
            "overall": _overall_body_load(regions),
        }
    return result


def _attach_tiers(db: Session, ranked: list[dict]) -> list[dict]:
    """Score each ranked destination's injury-frequency tier via the
    in-process model, mutating "tier" in place. Occupations with no BOHD
    coverage, or that the model never loaded for, simply keep tier=None -
    the same "no estimate" case every consumer already handles for
    missing data elsewhere in this file.

    For the full story of how a tier gets computed - the trained model,
    why only a tier is ever shown and never a raw number, how a missing
    model degrades gracefully - see app/services/injury_model.py (the
    model itself) and app/routes/injury_insight.py (the dedicated
    endpoint that exercises the same path end to end). This function
    just reuses that model for a second feature (destinations), so it
    stays intentionally thin.
    """
    exposures = _fetch_exposures(db, [r["occupation_id"] for r in ranked])
    result = score_occupations(exposures)
    for r in ranked:
        r["tier"] = result.tiers.get(r["occupation_id"])
    return ranked


def _body_load_band(source_score: float | None, destination_score: float | None) -> str | None:
    """'down' / 'up' / 'same' vs. the source occupation's overall body
    load, or null when either side has no data to compare. The +/-8
    tolerance matches the frontend's own loadBand() exactly (same
    constant, same comparison) - not a guess at a "reasonable" band.
    """
    if source_score is None or destination_score is None:
        return None
    diff = destination_score - source_score
    if diff <= -8:
        return "down"
    if diff >= 8:
        return "up"
    return "same"


_PROFILE_FIELDS_FOR_OCCUPATIONS = text(
    """
    SELECT occupation_id, median_weekly_earnings, part_time_share_pct, female_share_pct
    FROM telosia.occupation_profile
    WHERE occupation_id = ANY(:occupation_ids)
    """
)

_AUTOMATION_EXPOSURE_FOR_OCCUPATIONS = text(
    """
    SELECT occupation_id, automation_exposure
    FROM telosia.ai_exposure
    WHERE occupation_id = ANY(:occupation_ids)
    """
)

# Wenlu's frontend uses short slugs for Victorian SA4 regions rather than
# the numeric sa4_code region.py actually stores - verified 1:1 against
# the 17 VIC rows loaded (region.state_name = 'VIC').
_SA4_SLUG_TO_CODE = {
    "mel-inner": "206",
    "mel-inner-east": "207",
    "mel-inner-south": "208",
    "mel-north-east": "209",
    "mel-north-west": "210",
    "mel-outer-east": "211",
    "mel-south-east": "212",
    "mel-west": "213",
    "mornington": "214",
    "ballarat": "201",
    "bendigo": "202",
    "geelong": "203",
    "hume": "204",
    "latrobe": "205",
    "nw-vic": "215",
    "shepparton": "216",
    "warrnambool": "217",
}

_REGION_IDS_FOR_STATES = text(
    "SELECT region_id FROM telosia.region WHERE state_name = ANY(:states)"
)
_REGION_IDS_FOR_SA4_CODES = text(
    "SELECT region_id FROM telosia.region WHERE sa4_code = ANY(:codes)"
)


def _resolve_region_ids(db: Session, states: str | None, sa4_regions: str | None) -> list[int] | None:
    """Turn the states/sa4Regions query params into the set of region_id
    rows to filter and total against. Returns None when neither param
    was given (no region filtering requested), which is a different
    thing from an empty list (filtering was requested but matched no
    real region - e.g. an unrecognised sa4 slug).
    """
    if not states and not sa4_regions:
        return None

    region_ids: set[int] = set()

    if states:
        state_codes = [s.strip().upper() for s in states.split(",") if s.strip()]
        if state_codes:
            rows = db.execute(_REGION_IDS_FOR_STATES, {"states": state_codes}).mappings().all()
            region_ids.update(row["region_id"] for row in rows)

    if sa4_regions:
        slugs = [s.strip().lower() for s in sa4_regions.split(",") if s.strip()]
        codes = [_SA4_SLUG_TO_CODE[slug] for slug in slugs if slug in _SA4_SLUG_TO_CODE]
        if codes:
            rows = db.execute(_REGION_IDS_FOR_SA4_CODES, {"codes": codes}).mappings().all()
            region_ids.update(row["region_id"] for row in rows)

    return list(region_ids)


_REGIONAL_EMPLOYMENT_FOR_OCCUPATIONS = text(
    """
    SELECT occupation_id, SUM(estimated_employment) AS employment
    FROM telosia.regional_employment
    WHERE region_id = ANY(:region_ids)
        AND occupation_id = ANY(:occupation_ids)
    GROUP BY occupation_id
    """
)

_TOTAL_EMPLOYMENT_FOR_REGIONS = text(
    """
    SELECT SUM(estimated_employment) AS total_employment
    FROM telosia.regional_employment
    WHERE region_id = ANY(:region_ids)
    """
)


def _region_share_percentages(
    db: Session, region_ids: list[int], occupation_ids: list[int]
) -> dict[int, float | None]:
    """Each occupation's share of total employment across the requested
    region(s) - same "share of the real total" pattern as
    _rank_destinations: the denominator is every occupation's employment
    in these regions, not just the ones already in the candidate list.
    An occupation with no regional_employment row in any requested
    region gets None (filtered out by the caller), not a fabricated 0.
    """
    total_row = db.execute(
        _TOTAL_EMPLOYMENT_FOR_REGIONS, {"region_ids": region_ids}
    ).mappings().first()
    total = total_row["total_employment"] if total_row else None

    if not total:
        return {occupation_id: None for occupation_id in occupation_ids}

    rows = db.execute(
        _REGIONAL_EMPLOYMENT_FOR_OCCUPATIONS,
        {"region_ids": region_ids, "occupation_ids": occupation_ids},
    ).mappings().all()
    employment_by_occupation = {row["occupation_id"]: row["employment"] for row in rows}

    return {
        occupation_id: (
            round((employment_by_occupation[occupation_id] / total) * 100, 2)
            if occupation_id in employment_by_occupation
            else None
        )
        for occupation_id in occupation_ids
    }


def _sort_by(items, key_fn, ascending: bool = True):
    """Sort with missing values always last, regardless of direction -
    mirrors the frontend's byAscendingScore, which sinks unscored
    destinations to the bottom either way rather than treating a null as
    zero.
    """
    def sort_key(item):
        value = key_fn(item)
        if value is None:
            return (1, 0)
        return (0, value if ascending else -value)
    return sorted(items, key=sort_key)


def _apply_sort(destinations, sort, compare_region, body_loads, profile_by_id, automation_by_id):
    if sort == "kindest_overall":
        return _sort_by(destinations, lambda d: body_loads[d["occupation_id"]]["overall"])
    if sort == "best_relief":
        region = compare_region if compare_region in BODY_REGION_MAPPING else None
        if region is None:
            return _sort_by(destinations, lambda d: body_loads[d["occupation_id"]]["overall"])
        return _sort_by(destinations, lambda d: body_loads[d["occupation_id"]]["regions"].get(region))
    if sort == "highest_pay":
        return _sort_by(
            destinations,
            lambda d: profile_by_id.get(d["occupation_id"], {}).get("median_weekly_earnings"),
            ascending=False,
        )
    if sort == "most_part_time":
        return _sort_by(
            destinations,
            lambda d: profile_by_id.get(d["occupation_id"], {}).get("part_time_share_pct"),
            ascending=False,
        )
    if sort == "most_women":
        return _sort_by(
            destinations,
            lambda d: profile_by_id.get(d["occupation_id"], {}).get("female_share_pct"),
            ascending=False,
        )
    if sort == "least_automation":
        return _sort_by(destinations, lambda d: automation_by_id.get(d["occupation_id"]))
    if sort == "a_to_z":
        return sorted(destinations, key=lambda d: d["title"])
    return destinations  # "most_common" - already in that order from _rank_destinations


@router.get("/{occupation_id}/destinations", response_model=DestinationsResponse)
def get_destinations(
    occupation_id: int = Path(..., description="Source occupation ID."),
    sort: SortOption = Query(
        "most_common",
        description=(
            "most_common, kindest_overall, best_relief, highest_pay, "
            "most_part_time, most_women, least_automation, or a_to_z."
        ),
    ),
    compare_region: str | None = Query(
        None,
        alias="compareRegion",
        description="Body region name for best_relief. Ignored (falls back to overall) if unrecognised.",
    ),
    show_harder_moves: bool = Query(
        True,
        alias="showHarderMoves",
        description="Include destinations with equal or higher overall body load than the current occupation.",
    ),
    states: str | None = Query(
        None, description="Comma-separated state codes, e.g. VIC,NSW."
    ),
    sa4_regions: str | None = Query(
        None,
        alias="sa4Regions",
        description="Comma-separated Victorian SA4 slugs, e.g. mel-inner.",
    ),
    db: Session = Depends(get_db),
):
    """Return real destination occupations for a given source occupation.

    This endpoint supports US-3.1 and (via sort/compareRegion/
    showHarderMoves/states/sa4Regions) Iteration 2's destinations-page
    filters, per Wenlu's API_REQUIREMENTS.md. Destinations are ranked by
    observed transition share by default (AC3.1-a); self-transitions
    (staying in the same occupation) are always excluded.

    If the occupation has no outbound mobility data of its own (2 of 401
    loaded occupations, both "nfd"/"Other" catch-all codes), this falls
    back to aggregated data from other occupations sharing the same
    3-digit ANZSCO minor group - the actual classification's own next
    level up, not an invented grouping (AC3.1-b). The fallback list goes
    through the exact same sort/filter pipeline as a normal result.

    Args:
        occupation_id: The source occupation's surrogate key.
        sort: Which ordering to apply.
        compare_region: Body region to sort by for best_relief.
        show_harder_moves: False hides destinations with equal/higher
            overall body load than the current occupation (matches the
            board's "hidden by default" AC by being explicit here, but
            the query param itself defaults to True to match what's
            already live and Wenlu's own doc - the default value is a
            product decision for the frontend to set, not this endpoint).
        states: Comma-separated state codes to filter/report share by.
        sa4_regions: Comma-separated Victorian SA4 slugs, same purpose.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: Ranked, filtered destinations (top 10), or a fallback
        group's destinations with is_fallback set. Empty destinations
        list (not a 404) if a region filter matches nothing.

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    occupation = _get_occupation_or_404(db, occupation_id)

    rows = db.execute(
        _DESTINATIONS_FOR_OCCUPATION, {"occupation_id": occupation_id}
    ).mappings().all()

    is_fallback = False
    group = None

    if not rows:
        minor_group = occupation["anzsco_code"][:3]
        rows = db.execute(
            _DESTINATIONS_FOR_MINOR_GROUP,
            {"minor_group": minor_group, "occupation_id": occupation_id},
        ).mappings().all()
        is_fallback = True
        group = f"Occupations similar to {occupation['occupation_title']}"

    # Share is computed (in _rank_destinations) against the TRUE total
    # across every destination, but the candidate pool every sort/filter
    # below operates on is capped to the top _MAX_DESTINATIONS_RETURNED
    # by real transition share right here, deliberately, not after
    # sorting. "Every row is a move people actually made... not careers
    # advice" is the product's own stated promise - opening "highest
    # pay" or "kindest overall" up to the full destination list would
    # let a single-worker, statistically negligible transition outrank
    # a real common move on a secondary metric, contradicting that
    # promise. Verified this the hard way: sorting the full list by
    # kindest_overall surfaced occupations like "Psychologists and
    # Psychotherapists" that essentially nobody from this occupation
    # actually moved into, replacing the real top-10 entirely.
    destinations = _rank_destinations(rows)[:_MAX_DESTINATIONS_RETURNED]

    if not destinations:
        return {
            "occupation_id": occupation_id,
            "is_fallback": is_fallback,
            "group": group,
            "destinations": [],
        }

    destination_ids = [d["occupation_id"] for d in destinations]

    # Body load, compared one-vs-many against the source occupation only
    # (never destination-vs-destination) - same comparison the frontend
    # already makes client-side per destination.
    body_loads = _body_load_scores(db, [occupation_id] + destination_ids)
    source_overall = body_loads[occupation_id]["overall"]

    for d in destinations:
        d["body_load_band"] = _body_load_band(
            source_overall, body_loads[d["occupation_id"]]["overall"]
        )

    if not show_harder_moves and source_overall is not None:
        destinations = [
            d for d in destinations
            if body_loads[d["occupation_id"]]["overall"] is None
            or body_loads[d["occupation_id"]]["overall"] < source_overall
        ]

    # Region filter: attaches regionSharePercentage and drops any
    # destination with no employment recorded in the requested region(s)
    # at all (None, never a fabricated 0).
    region_ids = _resolve_region_ids(db, states, sa4_regions)
    if region_ids is not None:
        if region_ids:
            shares = _region_share_percentages(
                db, region_ids, [d["occupation_id"] for d in destinations]
            )
        else:
            shares = {}
        for d in destinations:
            d["region_share_percentage"] = shares.get(d["occupation_id"])
        destinations = [d for d in destinations if d["region_share_percentage"] is not None]

    profile_rows = db.execute(
        _PROFILE_FIELDS_FOR_OCCUPATIONS, {"occupation_ids": destination_ids}
    ).mappings().all()
    profile_by_id = {row["occupation_id"]: dict(row) for row in profile_rows}

    automation_rows = db.execute(
        _AUTOMATION_EXPOSURE_FOR_OCCUPATIONS, {"occupation_ids": destination_ids}
    ).mappings().all()
    automation_by_id = {row["occupation_id"]: row["automation_exposure"] for row in automation_rows}

    destinations = _apply_sort(
        destinations, sort, compare_region, body_loads, profile_by_id, automation_by_id
    )
    destinations = _attach_tiers(db, destinations)

    return {
        "occupation_id": occupation_id,
        "is_fallback": is_fallback,
        "group": group,
        "destinations": destinations,
    }


@router.get(
    "/{occupation_id}/destinations/{destination_id}",
    response_model=DestinationDetail,
)
def get_destination_detail(
    occupation_id: int = Path(..., description="Source occupation ID."),
    destination_id: int = Path(..., description="Destination occupation ID."),
    db: Session = Depends(get_db),
):
    """Return detail for one destination, with its transition share from
    the given source occupation specifically.

    This endpoint supports US-3.2. Does not include task descriptions -
    that data isn't loaded anywhere yet (none of the four ETL sources
    contain occupation task/duty text). AC3.2 otherwise covered: title
    and transition share from the current occupation.

    Args:
        occupation_id: The source occupation's surrogate key.
        destination_id: The destination occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: The destination's ID, title, share, source, and its
        injury-frequency tier from the research model (null if it has
        no BOHD coverage - see app/services/injury_model.py).

    Raises:
        HTTPException: 404 if either occupation doesn't exist, or if
        no direct transition is recorded between the two.
    """

    _get_occupation_or_404(db, occupation_id)
    destination = _get_occupation_or_404(db, destination_id)

    query = text(
        """
        SELECT
            SUM(worker_count) FILTER (WHERE destination_occupation_id = :destination_id) AS to_destination,
            SUM(worker_count) AS total,
            MIN(source_reference_id) AS source_reference_id
        FROM telosia.mobility_flow
        WHERE source_occupation_id = :occupation_id
            AND is_self_transition = FALSE
        """
    )
    row = db.execute(
        query, {"occupation_id": occupation_id, "destination_id": destination_id}
    ).mappings().first()

    if row is None or not row["to_destination"]:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No recorded transition from occupation {occupation_id} "
                f"to occupation {destination_id}."
            ),
        )

    # See app/services/injury_model.py + app/routes/injury_insight.py for
    # how this tier is actually computed - reused here as-is, not redone.
    exposures = _fetch_exposures(db, [destination_id])
    tier = score_occupations(exposures).tiers.get(destination_id)

    return {
        "occupation_id": destination_id,
        "title": destination["occupation_title"],
        "share": round((row["to_destination"] / row["total"]) * 100, 1),
        "source_id": row["source_reference_id"],
        "tier": tier,
    }


# ---------------------------------------------------------------------------
# Body-region physical-demand exposure (BOHD)
# ---------------------------------------------------------------------------

# Design and mapping from Sam (see
# Telosia_Body_Region_Backend_Implementation.md). This is deliberately NOT
# the same thing as US-2.1's injury-mechanism proportions - that needs
# WorkSafe Victoria's claims data, which is still blocked on the ASCO2/
# ANZSCO crosswalk. This is Beta Occupational Hazards Dataset (BOHD)
# exposure scores, which are already loaded and ANZSCO-coded, so it
# doesn't need the crosswalk at all. It measures physical-demand exposure,
# not recorded injuries - the wording throughout reflects that on purpose.
#
# No schema change: computed dynamically from hazard_variable +
# hazard_exposure on every request, nothing derived is stored back.
BODY_REGION_MAPPING = {
    "Lower back": [
        "Spend Time Bending or Twisting the Body",
        "Cramped Work Space, Awkward Positions",
        "Spend Time Sitting",
        "Exposed to Whole Body Vibration",
    ],
    "Shoulders and upper arms": [
        "Spend Time Making Repetitive Motions",
        "Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls",
    ],
    "Hands and wrists": [
        "Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls",
        "Spend Time Making Repetitive Motions",
        "Exposed to Minor Burns, Cuts, Bites, or Stings",
    ],
    "Knees": [
        "Spend Time Kneeling, Crouching, Stooping, or Crawling",
        "Spend Time Standing",
    ],
    "Legs and feet": [
        "Spend Time Standing",
        "Spend Time Walking and Running",
    ],
    "Whole body and fall risk": [
        "Spend Time Climbing Ladders, Scaffolds, or Poles",
        "Spend Time Keeping or Regaining Balance",
        "Exposed to High Places",
    ],
}

# Shown when a region has no mapped variable with a published score for
# this occupation - honest about *why* it's missing (no data exists for
# this occupation, a BOHD coverage gap) rather than reusing wording that
# would imply something was measured and suppressed (that's a different
# situation - see AC2.1-b's reporting-floor rule, once Epic 2 exists).
_NO_BODY_REGION_DATA_MESSAGE = "We don't have this information for this occupation yet."

_HAZARD_EXPOSURE_FOR_OCCUPATION = text(
    """
    SELECT
        hv.hazard_variable,
        he.exposure_score
    FROM telosia.hazard_exposure AS he
    JOIN telosia.hazard_variable AS hv
        ON hv.hazard_variable_id = he.hazard_variable_id
    WHERE he.occupation_id = :occupation_id
    """
)

# Overall physical-demand exposure, compared to this occupation's own
# destination occupations (the same set the Destinations page shows for
# it - see _get_destination_occupation_ids), not the whole 401-occupation
# population. Unlike the injury-frequency tier below, this is straight
# from published data, no model involved - so a real percentile is fine
# here, not just a coarse band. Averages every published hazard_variable
# score per occupation (not the 6 region maxes _calculate_body_regions
# produces - averaging those would double-count variables that feed
# multiple regions), then ranks this occupation's average against the
# comparison set. Computed fresh every request, nothing derived is
# stored back.
_OVERALL_EXPOSURE_PERCENTILE = text(
    """
    SELECT percentile
    FROM (
        SELECT
            occupation_id,
            PERCENT_RANK() OVER (ORDER BY avg_score) AS percentile
        FROM (
            SELECT occupation_id, AVG(exposure_score) AS avg_score
            FROM telosia.hazard_exposure
            WHERE occupation_id = ANY(:occupation_ids)
            GROUP BY occupation_id
        ) AS occupation_average
    ) AS ranked
    WHERE occupation_id = :occupation_id
    """
)


def _calculate_body_regions(exposures: dict):
    """Apply BODY_REGION_MAPPING to an {variable: score} lookup.

    For each region: take the MAX score among its mapped variables that
    actually have one (not an average - a single very high exposure
    shouldn't get diluted by unrelated lower ones). Never substitutes 0
    for missing data.
    """

    results = []
    for region, variables in BODY_REGION_MAPPING.items():
        contributors = [
            {"variable": variable, "score": exposures[variable]}
            for variable in variables
            if variable in exposures
        ]

        if contributors:
            contributors.sort(key=lambda c: c["score"], reverse=True)
            results.append({
                "region": region,
                "score": contributors[0]["score"],
                "contributors": contributors,
                "message": None,
            })
        else:
            results.append({
                "region": region,
                "score": None,
                "contributors": [],
                "message": _NO_BODY_REGION_DATA_MESSAGE,
            })

    return results


@router.get("/{occupation_id}/body-regions", response_model=BodyRegionsResponse)
def get_body_regions(
    occupation_id: int = Path(..., description="Occupation ID."),
    db: Session = Depends(get_db),
):
    """Return physical-demand exposure by body region, from BOHD.

    This is exposure to physical work-context demands (bending, standing,
    repetitive motion, and so on), not a record of actual injuries - a
    high score means the occupation scores highly on BOHD variables
    associated with that body region, not that Safe Work Australia
    recorded injuries there. See BODY_REGION_MAPPING's comment for why
    this is deliberately separate from the (still-blocked) claims-based
    injury feature.

    Args:
        occupation_id: The occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: All 6 body regions, each with a score (or null and an
        honest message if this occupation has no BOHD data at all -
        true for roughly 83 of the 401 loaded occupations) and its
        contributing variables. Also an overall_exposure_percentile -
        this occupation's average exposure ranked against its own
        destination occupations (null if either side has no BOHD data
        to compare).

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    occupation = _get_occupation_or_404(db, occupation_id)

    rows = db.execute(
        _HAZARD_EXPOSURE_FOR_OCCUPATION, {"occupation_id": occupation_id}
    ).mappings().all()
    exposures = {row["hazard_variable"]: row["exposure_score"] for row in rows}

    # Compared against this occupation's own destination occupations (the
    # same set the Destinations page shows), not the whole population -
    # see _get_destination_occupation_ids.
    destination_ids = _get_destination_occupation_ids(db, occupation)
    percentile_row = db.execute(
        _OVERALL_EXPOSURE_PERCENTILE,
        {"occupation_id": occupation_id, "occupation_ids": [occupation_id, *destination_ids]},
    ).first()

    return {
        "occupation_id": occupation_id,
        "title": occupation["occupation_title"],
        "body_regions": _calculate_body_regions(exposures),
        "overall_exposure_percentile": round(percentile_row[0] * 100, 1) if percentile_row else None,
    }


# ---------------------------------------------------------------------------
# US-7.1 / AC7.1 - How exposed is this job to AI
# ---------------------------------------------------------------------------

# JSA's Generative AI Capacity Study - published exposure ratings only,
# nothing modelled by the team. Covers 357 of 401 loaded occupations; the
# other 44 (mostly source-only/nfd codes with no JSA profile) get an
# honest null rather than an invented score.
_AI_EXPOSURE_CAVEAT_MESSAGE = (
    "Exposure indicates potential for tasks to be performed or assisted "
    "by generative AI, based on published research. It is not a "
    "forecast that this occupation will be automated away or that "
    "workers will be displaced."
)

_NO_AI_EXPOSURE_DATA_MESSAGE = "We don't have this information for this occupation yet."

_AI_EXPOSURE_FOR_OCCUPATION = text(
    """
    SELECT
        occupation_matrix_group,
        automation_exposure,
        automation_sd,
        augmentation_exposure,
        augmentation_sd,
        rate_of_skill_change,
        high_fit_transition_rate,
        entry_level_ad_share,
        source_reference_id
    FROM telosia.ai_exposure
    WHERE occupation_id = :occupation_id
    """
)


@router.get("/{occupation_id}/ai-exposure", response_model=AiExposureResponse)
def get_ai_exposure(
    occupation_id: int = Path(..., description="Occupation ID."),
    db: Session = Depends(get_db),
):
    """Return published generative AI exposure ratings for an occupation.

    This endpoint supports US-7.1 / AC7.1: the rating is shown with its
    source and an explicit caveat that exposure is not the same as
    displacement - published research about task-level automation
    potential, not a prediction that this occupation disappears.

    Args:
        occupation_id: The occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: Automation/augmentation exposure scores and related
        figures, or null fields and an honest message if this
        occupation has no published rating (true for 44 of the 401
        loaded occupations).

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    occupation = _get_occupation_or_404(db, occupation_id)

    row = db.execute(
        _AI_EXPOSURE_FOR_OCCUPATION, {"occupation_id": occupation_id}
    ).mappings().first()

    if row is None:
        return {
            "occupation_id": occupation_id,
            "title": occupation["occupation_title"],
            "message": _NO_AI_EXPOSURE_DATA_MESSAGE,
        }

    return {
        "occupation_id": occupation_id,
        "title": occupation["occupation_title"],
        "occupation_matrix_group": row["occupation_matrix_group"],
        "automation_exposure": row["automation_exposure"],
        "automation_sd": row["automation_sd"],
        "augmentation_exposure": row["augmentation_exposure"],
        "augmentation_sd": row["augmentation_sd"],
        "rate_of_skill_change": row["rate_of_skill_change"],
        "high_fit_transition_rate": row["high_fit_transition_rate"],
        "entry_level_ad_share": row["entry_level_ad_share"],
        "source_id": row["source_reference_id"],
        "message": _AI_EXPOSURE_CAVEAT_MESSAGE,
    }


# ---------------------------------------------------------------------------
# US-4.1 / AC4.1-a / AC4.1-b - Check a destination's pay gap
# ---------------------------------------------------------------------------

# JSA's Occupational Gender Pay Gap Dashboard is published at 6-digit
# ANZSCO, one level finer than Telosia's 4-digit occupation. Most 4-digit
# occupations (175/340 with any pay gap data) have exactly one 6-digit
# child, but a real number don't - Registered Nurses alone has 13, with
# real, meaningfully different pay gaps per specialisation (0.140 to
# 0.368 - more than double). Collapsing that to one "the" pay gap number
# for the occupation would misrepresent it, so this returns every
# specialisation rather than picking or averaging one.
#
# Only the "Whole workforce" headline cohort is returned, not the four
# age-band cohorts also held in pay_gap - a deliberate scope decision,
# not an oversight. AC4.1-b (never estimate an unpublished figure) needs
# no extra handling here: the underlying columns are already nullable
# and this returns them as-is, never filling a withheld figure.
_NO_PAY_GAP_DATA_MESSAGE = "We don't have this information for this occupation yet."

_PAY_GAP_FOR_OCCUPATION = text(
    """
    SELECT
        anzsco_6digit_code,
        anzsco_6digit_title,
        segregation_intensity,
        female_income_median,
        male_income_median,
        gender_pay_gap,
        hours_difference,
        ten_year_pay_gap,
        source_reference_id
    FROM telosia.pay_gap
    WHERE parent_occupation_id = :occupation_id
        AND is_headline_cohort = TRUE
    ORDER BY anzsco_6digit_code
    """
)


@router.get("/{occupation_id}/pay-gap", response_model=PayGapResponse)
def get_pay_gap(
    occupation_id: int = Path(..., description="Occupation ID."),
    db: Session = Depends(get_db),
):
    """Return published gender pay gap figures for an occupation.

    This endpoint supports US-4.1 / AC4.1-a / AC4.1-b. Figures are at
    6-digit ANZSCO granularity (Telosia occupations are 4-digit), so one
    occupation can return several specialisations, each with its own
    real pay gap - never averaged or picked down to one number.

    Args:
        occupation_id: The occupation's surrogate key.
        db: SQLAlchemy database session provided by FastAPI.

    Returns:
        dict: One entry per published 6-digit specialisation, or an
        empty list and an honest message if this occupation has no
        published pay gap data at all (61 of 401 loaded occupations).
        Any individual figure JSA withheld is null, never estimated.

    Raises:
        HTTPException: 404 if no occupation exists with that ID.
    """

    occupation = _get_occupation_or_404(db, occupation_id)

    rows = db.execute(
        _PAY_GAP_FOR_OCCUPATION, {"occupation_id": occupation_id}
    ).mappings().all()

    if not rows:
        return {
            "occupation_id": occupation_id,
            "title": occupation["occupation_title"],
            "specializations": [],
            "message": _NO_PAY_GAP_DATA_MESSAGE,
        }

    return {
        "occupation_id": occupation_id,
        "title": occupation["occupation_title"],
        "specializations": [
            {
                "anzsco_6digit_code": row["anzsco_6digit_code"],
                "anzsco_6digit_title": row["anzsco_6digit_title"],
                "segregation_intensity": row["segregation_intensity"],
                "female_income_median": row["female_income_median"],
                "male_income_median": row["male_income_median"],
                "gender_pay_gap": row["gender_pay_gap"],
                "hours_difference": row["hours_difference"],
                "ten_year_pay_gap": row["ten_year_pay_gap"],
            }
            for row in rows
        ],
        "source_id": rows[0]["source_reference_id"],
        "message": None,
    }
