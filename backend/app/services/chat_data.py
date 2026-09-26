"""Structured, read-only access to the public Telosia research datasets.

The LLM supplies a query *description*, never SQL. Column references resolve to
reflected SQLAlchemy columns in this registry, and all values become parameters.
Sam's existing body-region mapping is read at query time; nothing is written to
the database and missing exposure measurements remain missing.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Any, Literal
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Boolean, Date, DateTime, Float, Integer, MetaData, Numeric, Table,
    and_, func, inspect, literal, or_, select, true, union_all,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement


# Deliberately restricted to public research tables, not arbitrary schemas,
# application credentials, pg_catalog, or future account/session tables.
DATASET_NOTES: dict[str, tuple[str, str, list[str]]] = {
    "occupation": (
        "Australian occupation directory, including source-only occupations.",
        "One four-digit ANZSCO occupation.",
        ["Use is_profile_occupation for jobs with JSA profiles; source-only jobs may lack other measures."],
    ),
    "occupation_profile": (
        "JSA occupation employment, earnings, demographics and qualifications.",
        "One four-digit ANZSCO occupation profile.",
        ["Earnings are published median weekly earnings, not annual pay or gender pay gaps.",
         "A mean of occupation statistics is unweighted; it is not a population-weighted estimate."],
    ),
    "occupation_task": ("Published occupation task descriptions.", "One ordered task per occupation.", []),
    "occupation_alias": ("Alternative occupation names.", "One alias per occupation.", []),
    "source_reference": ("Dataset publishers, URLs, coverage, licences and attribution.", "One source dataset.", []),
    "injury_frequency": (
        "Yearly workers' compensation injury frequency rates.",
        "One occupation, financial year and measure_type.",
        ["frequency_rate is claims per million hours worked. Average yearly rates; never sum them.",
         "Suppressed or blank values are NULL, never zero. Keep is_suppressed/is_preliminary in explanations.",
         "These data do not publish occupation-by-body-part injury claims."],
    ),
    "hazard_variable": ("BOHD hazard variable definitions and categories.", "One hazard variable.", []),
    "hazard_exposure": (
        "BOHD published occupational work-demand exposure scores.",
        "One four-digit occupation and hazard variable.",
        ["Scores are 0–100 exposure, not injury probabilities or claims.",
         "BOHD is a beta release derived partly by mapping U.S. O*NET data onto Australian occupations.",
         "Exposure is a snapshot without a financial-year dimension."],
    ),
    "body_region_exposure": (
        "Reproducible body-region work-demand scores using Sam's existing mapping.",
        "One occupation and one of six body regions.",
        ["score = MAX of published contributing hazard scores; no new mapping or annotation weights.",
         "Filter complete_coverage=true when ranking low exposure so missing contributors cannot appear safer.",
         "Regions: Lower back; Shoulders and upper arms; Hands and wrists; Knees; Legs and feet; Whole body and fall risk.",
         "BOHD is a beta release derived partly from U.S. O*NET mapped to Australian occupations.",
         "Snapshot work-demand exposure, not injury probability, diagnoses or individual job suitability.",
         "Display rounded whole scores or bands. A missing score is NULL, never zero."],
    ),
    "mobility_flow": (
        "Recorded national occupation-to-occupation worker movements.",
        "One source occupation, destination occupation and financial year.",
        ["Exclude is_self_transition=true when asking where workers move next.",
         "National movements cannot be interpreted as regional flows. Summed yearly counts are movements, not unique people."],
    ),
    "pay_gap": (
        "Published JSA gender pay-gap and annual income figures by specialisation.",
        "One six-digit ANZSCO specialisation and cohort.",
        ["Use is_headline_cohort=true for whole-workforce headline comparisons unless another cohort is requested.",
         "gender_pay_gap, hours_difference and ten_year_pay_gap are fractions: 0.25 means 25%; negative values are valid.",
         "Difference of two gap fractions multiplied by 100 is percentage points, not a salary difference.",
         "Do not pool six-digit specialisation medians into four-digit medians or invent a parent-occupation gap.",
         "Min/max grouped by parent describes an extremal specialisation, not a parent-level published estimate.",
         "A mean of published gap fractions is an unweighted descriptive mean, not a pooled workforce gender pay gap."],
    ),
    "ai_exposure": (
        "JSA published generative-AI exposure and related indicators.",
        "One four-digit occupation.",
        ["automation_exposure and augmentation_exposure are fractions from 0 to 1.",
         "Exposure indicates potential task assistance/performance, not a forecast of job loss."],
    ),
    "nds_category": ("NDS occupation and industry classifications.", "One dimension and category code.", []),
    "nds_claim_statistic": (
        "NDS national claims, rates, compensation and time-lost statistics.",
        "One category, financial year and measure, with explicit unit.",
        ["Occupation measures are published at ANZSCO major/sub-major group levels (one/two digits); never relabel them as four-digit observations.",
         "Keep measure, unit and dimension separate when aggregating; counts and rates are different quantities.",
         "A total and its child categories overlap. Do not sum across classification levels.",
         "is_not_published values remain NULL; these are not zero claims.",
         "No occupation-by-body-part cross-tabulation is present."],
    ),
    "occupation_nds_link": (
        "Classification links from occupations to their broader published NDS group.",
        "One four-digit occupation mapped to a broader NDS category.",
        ["A link does not turn broader-group claim data into an occupation-specific observation."],
    ),
    "region": ("SA4 region names and state codes.", "One SA4 region.", []),
    "regional_employment": (
        "JSA NERO regional employment levels and changes.",
        "One occupation, SA4 region and reference date.",
        ["Employment levels, not regional movements or job vacancies.",
         "Do not sum employment snapshots across dates as if they were distinct workers."],
    ),
    "crosswalk_status": ("Classification crosswalk and verification information.", "One source-to-target occupation mapping.", []),
    "model_run": ("Project model-run provenance and evaluation metadata.", "One model training run.", []),
    "injury_insight": (
        "Project model-generated insights and model-run provenance.",
        "One occupation, model run and insight type.",
        ["Model outputs are distinct from published observed claims."],
    ),
    "hazard_annotation": (
        "Separate project hazard annotation evidence and review status.",
        "One hazard annotation.",
        ["Project annotation, not a body-part mapping published in BOHD. Respect review_status.",
         "These annotations are not used to calculate Sam's body_region_exposure dataset."],
    ),
    "hazard_body_part_mapping": (
        "Separate project hazard-to-body-part association annotations.",
        "One hazard and annotated body-part association.",
        ["Association scores are project annotations, not observed claims or injury probabilities.",
         "Review status/evidence are joined from hazard_annotation when available.",
         "These annotations do not replace Sam's approved six-region mapping."],
    ),
    "body_part_code": (
        "Body-part classification codes used by project annotations.",
        "One body-part code.",
        ["A classification code is not evidence of observed injuries for an occupation."],
    ),
}


# Hints describe the supported schema, not the contents of a connected database.
# Joined titles/codes and body-region fields match the projections below.
_PROMPT_FIELDS: dict[str, tuple[str, ...]] = {
    "occupation_profile": (
        "occupation_id", "occupation_title", "anzsco_code", "employed",
        "median_weekly_earnings", "female_share_pct", "part_time_share_pct",
        "median_age", "annual_employment_growth",
    ),
    "occupation": (
        "occupation_id", "occupation_title", "anzsco_code",
        "occupation_description", "is_profile_occupation",
    ),
    "injury_frequency": (
        "occupation_id", "occupation_title", "financial_year", "measure_type",
        "frequency_rate", "is_suppressed", "is_preliminary",
    ),
    "body_region_exposure": (
        "occupation_id", "occupation_title", "anzsco_code", "region", "score",
        "available_variable_count", "expected_variable_count", "complete_coverage",
    ),
    "pay_gap": (
        "parent_occupation_id", "occupation_title", "anzsco_6digit_code",
        "anzsco_6digit_title", "cohort", "is_headline_cohort", "gender_pay_gap",
        "female_income_median", "male_income_median", "hours_difference", "ten_year_pay_gap",
    ),
    "mobility_flow": (
        "source_occupation_id", "source_occupation_title", "destination_occupation_id",
        "destination_occupation_title", "financial_year", "worker_count", "is_self_transition",
    ),
    "ai_exposure": (
        "occupation_id", "occupation_title", "automation_exposure", "augmentation_exposure",
        "occupation_matrix_group", "rate_of_skill_change", "high_fit_transition_rate",
        "entry_level_ad_share",
    ),
}


def prompt_catalog() -> dict[str, Any]:
    """Compact schema hints for the first model call, without inspecting a DB."""
    return {
        "datasets": [{"name": name, "description": notes[0]} for name, notes in DATASET_NOTES.items()],
        "common_fields": {name: list(fields) for name, fields in _PROMPT_FIELDS.items()},
        "availability_note": (
            "These are supported dataset and field hints, not confirmation that tables or data are loaded. "
            "Query known fields directly; use describe_data when live fields or availability are uncertain."
        ),
        "unit_notes": [
            "median_weekly_earnings is AUD/week; income medians in pay_gap are AUD/year. Do not pool medians.",
            "Fields ending _pct are already percentages. gender_pay_gap, hours_difference, ten_year_pay_gap, automation_exposure and augmentation_exposure are fractions; multiply by 100 for percent.",
            "Pay gaps describe six-digit specialisations and cohorts; use is_headline_cohort=true for headline comparisons.",
            "frequency_rate is claims per million hours worked. Rates and exposure indices cannot be summed.",
            "Body-region score is a work-demand exposure index, not injury probability. Filter complete_coverage=true for low-exposure rankings.",
            "Exclude is_self_transition=true for onward mobility. worker_count counts national movements, not unique people.",
            "NULL is missing or unpublished, never zero. Queries return live units, grain, caveats and provenance.",
        ],
    }


_UNITS = {
    "frequency_rate": "claims per million hours worked",
    "exposure_score": "exposure index, 0–100",
    "score": "maximum contributing exposure index, 0–100",
    "gender_pay_gap": "fraction; multiply by 100 to display percent",
    "hours_difference": "fraction; multiply by 100 to display percent",
    "ten_year_pay_gap": "fraction; multiply by 100 to display percent",
    "female_income_median": "AUD per year, published median",
    "male_income_median": "AUD per year, published median",
    "median_weekly_earnings": "AUD per week, published median",
    "median_age": "years",
    "employed": "people",
    "estimated_employment": "estimated people",
    "employment_1y_ago": "estimated people",
    "employment_5y_ago": "estimated people",
    "worker_count": "recorded worker movements",
    "automation_exposure": "fraction, 0–1",
    "augmentation_exposure": "fraction, 0–1",
    "automation_sd": "standard deviation on the 0–1 exposure scale",
    "augmentation_sd": "standard deviation on the 0–1 exposure scale",
    "high_fit_transition_rate": "fraction, 0–1",
    "entry_level_ad_share": "fraction, 0–1",
    "association_score": "project association score, 0–3",
    "overall_association_score": "project association score, 0–3",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryFilter(_StrictModel):
    field: str = Field(min_length=1, max_length=100)
    op: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "contains", "is_null", "not_null"]
    value: Any = None


class QueryMetric(_StrictModel):
    function: Literal["count", "count_distinct", "min", "max", "avg", "sum"]
    field: str | None = Field(default=None, max_length=100)
    alias: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


class QueryOrder(_StrictModel):
    field: str = Field(min_length=1, max_length=100)
    direction: Literal["asc", "desc"] = "asc"


class DataQuery(_StrictModel):
    dataset: str = Field(min_length=1, max_length=100)
    select: list[str] = Field(default_factory=list, max_length=35)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(default_factory=list, max_length=12)
    metrics: list[QueryMetric] = Field(default_factory=list, max_length=12)
    order_by: list[QueryOrder] = Field(default_factory=list, max_length=8)
    distinct: bool = False
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, le=10000, strict=True)

    @model_validator(mode="after")
    def check_names(self):
        for names in (self.select, self.group_by, [m.alias for m in self.metrics]):
            if len(names) != len(set(names)):
                raise ValueError("Duplicate fields or metric aliases are not allowed.")
        return self


def get_query_schema() -> dict[str, Any]:
    """OpenAI-compatible function parameters, with local Pydantic refs inlined."""
    schema = DataQuery.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(item):
        if isinstance(item, dict):
            if "$ref" in item:
                return expand(definitions[item["$ref"].rsplit("/", 1)[-1]])
            return {k: expand(v) for k, v in item.items() if k != "title"}
        if isinstance(item, list):
            return [expand(v) for v in item]
        return item

    return expand(schema)


@dataclass
class Dataset:
    name: str
    relation: Any
    columns: dict[str, ColumnElement]
    source_relation: Any = None
    source_column: ColumnElement | None = None


_TABLE_CACHE: WeakKeyDictionary[Engine, dict[str, Table]] = WeakKeyDictionary()
_TABLE_LOCK = Lock()
_CATALOG_CACHE: WeakKeyDictionary[Engine, tuple[float, dict[str, Any]]] = WeakKeyDictionary()
_CATALOG_LOCK = Lock()
CATALOG_CACHE_TTL_SECONDS = 300.0


def _session_engine(db: Session) -> Engine:
    bind = db.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def clear_catalog_cache(engine: Engine | None = None) -> None:
    """Invalidate catalog and reflection metadata for one engine, or all engines."""
    with _CATALOG_LOCK, _TABLE_LOCK:
        if engine is None:
            _CATALOG_CACHE.clear()
            _TABLE_CACHE.clear()
        else:
            _CATALOG_CACHE.pop(engine, None)
            _TABLE_CACHE.pop(engine, None)


@contextmanager
def _read_connection(db: Session):
    """Use an isolated read-only transaction without changing the caller session."""
    engine = _session_engine(db)
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection = connection.execution_options(postgresql_readonly=True)
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET LOCAL statement_timeout = '5000ms'")
            yield connection


def _tables(connection: Connection) -> dict[str, Table]:
    with _TABLE_LOCK:
        cached = _TABLE_CACHE.get(connection.engine)
        if cached is not None:
            return cached
        existing = set(inspect(connection).get_table_names(schema="telosia"))
        names = sorted(existing.intersection(DATASET_NOTES) - {"body_region_exposure"})
        metadata = MetaData()
        # resolve_fks=False prevents reflection from following references outside
        # the explicit dataset registry; joins below are explicitly registered.
        result = {
            name: Table(name, metadata, schema="telosia", autoload_with=connection, resolve_fks=False)
            for name in names
        }
        _TABLE_CACHE[connection.engine] = result
        return result


def _regular_dataset(name: str, tables: dict[str, Table]) -> Dataset:
    table = tables[name]
    relation = table
    columns = dict(table.c.items())

    def add_join(target_name, local_key, target_key, fields, alias):
        nonlocal relation
        if target_name not in tables or local_key not in columns:
            return
        target = tables[target_name].alias(alias)
        relation = relation.outerjoin(target, columns[local_key] == target.c[target_key])
        for field, output in fields.items():
            if field in target.c and output not in columns:
                columns[output] = target.c[field].label(output)

    if name != "occupation":
        for key, prefix in (("occupation_id", ""), ("parent_occupation_id", ""),
                            ("source_occupation_id", "source_"), ("destination_occupation_id", "destination_")):
            add_join("occupation", key, "occupation_id", {
                "occupation_title": f"{prefix}occupation_title",
                "anzsco_code": f"{prefix}anzsco_code",
                "is_profile_occupation": f"{prefix}is_profile_occupation",
            }, f"{prefix or 'linked_'}occupation")
    if name != "hazard_variable":
        add_join("hazard_variable", "hazard_variable_id", "hazard_variable_id", {
            "hazard_variable": "hazard_variable", "hazard_category": "hazard_category",
            "question_text": "question_text",
        }, "linked_hazard")
    if name != "region":
        add_join("region", "region_id", "region_id", {
            "sa4_code": "sa4_code", "sa4_name": "sa4_name", "state_name": "state_name",
        }, "linked_region")
    if name != "nds_category":
        add_join("nds_category", "nds_category_id", "nds_category_id", {
            "dimension": "dimension", "classification": "classification",
            "category_code": "category_code", "category_label": "category_label",
            "level": "level", "parent_code": "parent_code", "is_nfd": "is_nfd",
        }, "linked_nds_category")
    if name == "hazard_body_part_mapping":
        add_join("body_part_code", "body_part_code", "body_part_code", {
            "title_en": "body_part_title", "display_region": "display_region",
            "risk_channel": "risk_channel", "source_url": "body_code_source_url",
        }, "linked_body_part")
        add_join("hazard_annotation", "hazard_variable_id", "hazard_variable_id", {
            "review_status": "review_status", "evidence_url_1": "evidence_url_1",
            "evidence_url_2": "evidence_url_2", "evidence_summary": "evidence_summary",
        }, "linked_annotation")
    return Dataset(name, relation, columns, relation, columns.get("source_reference_id"))


def _body_dataset(tables: dict[str, Table]) -> Dataset:
    from app.routes.occupations import BODY_REGION_MAPPING

    occupation, hazard, exposure = (tables[n] for n in ("occupation", "hazard_variable", "hazard_exposure"))
    # UNION ALL literals are portable to SQLite tests, and remain parameters.
    mapping = union_all(*[
        select(literal(region).label("region"), literal(variable).label("variable"),
               literal(len(variables)).label("expected_variable_count"))
        for region, variables in BODY_REGION_MAPPING.items() for variable in variables
    ]).subquery("approved_body_mapping")
    inputs = occupation.join(mapping, true()).outerjoin(
        hazard, hazard.c.hazard_variable == mapping.c.variable,
    ).outerjoin(exposure, and_(
        exposure.c.occupation_id == occupation.c.occupation_id,
        exposure.c.hazard_variable_id == hazard.c.hazard_variable_id,
    ))
    available = func.count(exposure.c.exposure_score)
    expected = func.max(mapping.c.expected_variable_count)
    scores = select(
        occupation.c.occupation_id, occupation.c.occupation_title, occupation.c.anzsco_code,
        mapping.c.region, func.max(exposure.c.exposure_score).label("score"),
        available.label("available_variable_count"), expected.label("expected_variable_count"),
        (available == expected).label("complete_coverage"),
    ).select_from(inputs).group_by(
        occupation.c.occupation_id, occupation.c.occupation_title, occupation.c.anzsco_code, mapping.c.region,
    ).subquery("body_region_exposure")
    provenance = scores.join(mapping, mapping.c.region == scores.c.region).join(
        hazard, hazard.c.hazard_variable == mapping.c.variable,
    ).join(exposure, and_(
        exposure.c.occupation_id == scores.c.occupation_id,
        exposure.c.hazard_variable_id == hazard.c.hazard_variable_id,
    ))
    return Dataset("body_region_exposure", scores, dict(scores.c.items()), provenance, exposure.c.source_reference_id)


def _dataset(name: str, tables: dict[str, Table]) -> Dataset:
    if name == "body_region_exposure" and all(n in tables for n in ("occupation", "hazard_variable", "hazard_exposure")):
        return _body_dataset(tables)
    if name not in DATASET_NOTES or name not in tables:
        raise ValueError(f"Unknown or unavailable dataset: {name}. Use describe_data to discover datasets.")
    return _regular_dataset(name, tables)


def _field_type(expression: ColumnElement) -> str:
    kind = expression.type
    if isinstance(kind, Boolean):
        return "boolean"
    if isinstance(kind, Integer):
        return "integer"
    if isinstance(kind, (Float, Numeric)):
        return "number"
    if isinstance(kind, DateTime):
        return "datetime"
    if isinstance(kind, Date):
        return "date"
    return "string"


def _field_metadata(name: str, expression: ColumnElement) -> dict[str, Any]:
    result = {"type": _field_type(expression)}
    unit = _UNITS.get(name)
    if name.endswith("_pct"):
        unit = "percent, already multiplied by 100"
    if unit:
        result["unit"] = unit
    return result


def catalog(db: Session) -> dict[str, Any]:
    """Inspect live schema on demand and reuse its catalog for a short interval."""
    engine = _session_engine(db)
    with _CATALOG_LOCK:
        cached = _CATALOG_CACHE.get(engine)
        if cached is not None and monotonic() - cached[0] < CATALOG_CACHE_TTL_SECONDS:
            return deepcopy(cached[1])
        if cached is not None:
            # Refresh reflected tables too, so newly loaded datasets and fields
            # become discoverable after the catalog's TTL expires.
            with _TABLE_LOCK:
                _TABLE_CACHE.pop(engine, None)
        result = _live_catalog(db)
        _CATALOG_CACHE[engine] = (monotonic(), result)
        return deepcopy(result)


def _live_catalog(db: Session) -> dict[str, Any]:
    with _read_connection(db) as connection:
        tables = _tables(connection)
        names = sorted(tables)
        if all(n in tables for n in ("occupation", "hazard_variable", "hazard_exposure")):
            names.append("body_region_exposure")
        datasets = []
        for name in names:
            dataset = _dataset(name, tables)
            description, grain, notes = DATASET_NOTES[name]
            datasets.append({
                "name": name, "description": description, "grain": grain, "notes": notes,
                "fields": {key: _field_metadata(key, value) for key, value in dataset.columns.items()},
            })
    return {
        "datasets": datasets,
        "query_notes": [
            "All filters are ANDed; use the in operator for alternatives on one field.",
            "select lists raw fields. With metrics, select and group_by may only contain grouping fields.",
            "Metrics accept count (field omitted means row count), count_distinct, min, max, avg, sum.",
            "order_by may use raw fields or metric aliases. NULL values always sort last.",
            "All data values remain in published units. No implicit fraction-to-percent conversion.",
            "NULL means missing/unpublished, never zero. Aggregates ignore NULL observations.",
            "Results are bounded to 100 rows per query; use filters/aggregation or offset for further pages.",
            "Use multiple queries and calculate for cross-dataset comparisons; there is no arbitrary SQL input.",
        ],
    }


def _column(dataset: Dataset, name: str) -> ColumnElement:
    if name not in dataset.columns:
        raise ValueError(f"Unknown field {name!r} for {dataset.name}. Use describe_data for available fields.")
    return dataset.columns[name]


def _typed_value(expression: ColumnElement, value: Any):
    kind = _field_type(expression)
    if isinstance(value, (dict, list)) or value is None:
        raise ValueError("Filter values must be scalar; use is_null/not_null for missing values.")
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A numeric field requires a numeric filter value.")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("Numeric filter values must be finite.")
        if kind == "integer" and not isinstance(value, int):
            raise ValueError("An integer field requires an integer value.")
    elif kind == "boolean":
        # Normalize only boolean literals, only for a boolean column.
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            value = value.strip().lower() == "true"
        if not isinstance(value, bool):
            raise ValueError("A boolean field requires true or false.")
    else:
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError("A text/date filter requires a string of at most 1000 characters.")
        if kind == "date":
            value = date.fromisoformat(value)
        elif kind == "datetime":
            value = datetime.fromisoformat(value)
    return value


def _filter_expression(dataset: Dataset, item: QueryFilter):
    expression = _column(dataset, item.field)
    if item.op in ("is_null", "not_null"):
        if item.value is not None:
            raise ValueError("is_null and not_null do not accept a value.")
        return expression.is_(None) if item.op == "is_null" else expression.is_not(None)
    if item.op == "in":
        if not isinstance(item.value, list) or not 1 <= len(item.value) <= 100:
            raise ValueError("in requires a nonempty list of at most 100 scalar values.")
        return expression.in_([_typed_value(expression, value) for value in item.value])
    value = _typed_value(expression, item.value)
    if item.op == "contains":
        if _field_type(expression) != "string":
            raise ValueError("contains is only available for text fields.")
        # Escape LIKE wildcard characters: a user's '_' or '%' is literal text.
        return expression.icontains(value, autoescape=True)
    if _field_type(expression) == "boolean" and item.op not in ("eq", "ne"):
        raise ValueError("Boolean fields support eq/ne/in/is_null/not_null only.")
    return {"eq": expression.__eq__, "ne": expression.__ne__, "gt": expression.__gt__,
            "ge": expression.__ge__, "lt": expression.__lt__, "le": expression.__le__}[item.op](value)


def _fixed_field(spec: DataQuery, name: str) -> bool:
    return name in spec.group_by or any(
        f.field == name and (f.op == "eq" or (f.op == "in" and isinstance(f.value, list) and len(f.value) == 1))
        for f in spec.filters
    )


def _validate_semantics(spec: DataQuery):
    for metric in spec.metrics:
        field = metric.field or "*"
        if metric.function == "sum":
            nonadditive = (field in _UNITS and field not in {
                "employed", "estimated_employment", "employment_1y_ago", "employment_5y_ago", "worker_count",
            }) or field.endswith(("_pct", "_share", "_exposure", "_rate", "_sd"))
            if nonadditive:
                raise ValueError(f"{field} is a rate, index, share or median and cannot be summed. Use an appropriate mean/min/max instead.")
        if metric.function in ("sum", "avg") and field in ("female_income_median", "male_income_median", "median_weekly_earnings", "median_age"):
            raise ValueError("Published medians cannot be combined into a pooled median; retrieve or compare them individually.")
        if spec.dataset == "regional_employment" and metric.function == "sum" and not _fixed_field(spec, "reference_date"):
            raise ValueError("Regional employment sums must filter or group by reference_date; snapshots are not distinct workers.")
        if spec.dataset == "pay_gap" and metric.function not in ("count", "count_distinct"):
            headline = any(f.field == "is_headline_cohort" and f.op == "eq" and f.value is True for f in spec.filters)
            if not headline and not _fixed_field(spec, "cohort"):
                raise ValueError("Pay-gap summaries must filter or group by cohort (or filter is_headline_cohort=true).")
        if spec.dataset == "nds_claim_statistic" and field == "value" and metric.function not in ("count", "count_distinct"):
            for required in ("measure", "unit", "dimension"):
                if not _fixed_field(spec, required):
                    raise ValueError(f"NDS value summaries must filter or group by {required}; unlike measures cannot be combined.")
            if metric.function == "sum":
                counts_only = any(f.field == "measure" and f.op == "eq" and f.value == "claim_count" for f in spec.filters)
                if not counts_only or not _fixed_field(spec, "level"):
                    raise ValueError("NDS sums require measure=claim_count and one/grouped classification level; do not sum rates, medians or overlapping levels.")


def _build_statement(dataset: Dataset, spec: DataQuery):
    _validate_semantics(spec)
    predicates = [_filter_expression(dataset, item) for item in spec.filters]
    grouped = bool(spec.metrics or spec.group_by)
    selected = spec.select or (spec.group_by if grouped else list(dataset.columns))
    if grouped and not set(selected).issubset(spec.group_by):
        raise ValueError("All selected raw fields must appear in group_by when aggregating.")
    if spec.select and spec.group_by and set(spec.select) != set(spec.group_by):
        raise ValueError("Include every group_by field in select so grouped results and their sources are identifiable.")
    if spec.metrics and spec.distinct:
        raise ValueError("Use grouping or count_distinct rather than distinct together with metrics.")
    outputs = {name: _column(dataset, name) for name in selected}
    for name in spec.group_by:
        _column(dataset, name)
    for metric in spec.metrics:
        if metric.alias in dataset.columns or metric.alias in outputs:
            raise ValueError(f"Metric alias {metric.alias!r} collides with an existing field.")
        if metric.field in (None, "*"):
            if metric.function != "count":
                raise ValueError("Only count may omit a field or use '*'.")
            aggregate = func.count()
        else:
            expression = _column(dataset, metric.field)
            if metric.function in ("avg", "sum") and _field_type(expression) not in ("integer", "number"):
                raise ValueError("avg and sum require a numeric field.")
            if metric.function in ("min", "max") and _field_type(expression) == "boolean":
                raise ValueError("min/max are not supported for boolean fields.")
            aggregate = (func.count(expression.distinct()) if metric.function == "count_distinct"
                         else getattr(func, metric.function)(expression))
        outputs[metric.alias] = aggregate.label(metric.alias)
    if not outputs:
        raise ValueError("Select at least one field or metric.")
    statement = select(*outputs.values()).select_from(dataset.relation).where(*predicates)
    if spec.group_by:
        statement = statement.group_by(*[_column(dataset, field) for field in spec.group_by])
    if spec.distinct:
        statement = statement.distinct()
    for ordering in spec.order_by:
        expression = outputs.get(ordering.field)
        if expression is None:
            if grouped and ordering.field not in spec.group_by:
                raise ValueError("Aggregated queries can only order by grouping fields or metric aliases.")
            if spec.distinct:
                raise ValueError("Distinct queries can only order by selected fields.")
            expression = _column(dataset, ordering.field)
        statement = statement.order_by(
            (expression.desc() if ordering.direction == "desc" else expression.asc()).nulls_last()
        )
    # Add tie-breakers so pagination is stable without imposing a ranking rule.
    if not grouped:
        candidates = selected if spec.distinct else [c.name for c in dataset.columns.values() if getattr(c, "primary_key", False)]
        if dataset.name == "body_region_exposure":
            candidates = [k for k in ("occupation_id", "region") if not spec.distinct or k in selected]
    else:
        candidates = spec.group_by
    ordered = {item.field for item in spec.order_by}
    for name in candidates:
        if name not in ordered:
            statement = statement.order_by(_column(dataset, name).asc().nulls_last())
    return statement.limit(spec.limit + 1).offset(spec.offset), predicates, selected


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def query_dataset(db: Session, arguments: dict[str, Any]) -> tuple[dict[str, Any], set[int]]:
    spec = DataQuery.model_validate(arguments)
    with _read_connection(db) as connection:
        dataset = _dataset(spec.dataset, _tables(connection))
        statement, predicates, selected = _build_statement(dataset, spec)
        if spec.dataset == "nds_claim_statistic" and any(
            metric.field == "value" and metric.function in {"avg", "sum"} for metric in spec.metrics
        ):
            # NDS stores several unlike quantities in one generic value column.
            # Inspect the requested scope so grouping by measure cannot bypass
            # the no-pooling rule for published medians.
            median_query = select(dataset.columns["measure"]).select_from(dataset.relation).where(
                *predicates, dataset.columns["measure"].contains("median"),
            ).limit(1)
            if connection.execute(median_query).first() is not None:
                raise ValueError("The requested NDS scope includes published medians. Do not average/sum them; filter a non-median measure or compare the published values individually.")
        fetched = [dict(row) for row in connection.execute(statement).mappings()]
        truncated = len(fetched) > spec.limit
        rows = fetched[:spec.limit]
        source_ids: set[int] = set()
        if rows and dataset.source_column is not None:
            # Match returned raw/group fields, including NULLs, to collect the
            # sources of every contributing row rather than losing provenance
            # when source_reference_id was not selected or was aggregated out.
            keys = spec.group_by if (spec.metrics or spec.group_by) else selected
            source_predicates = list(predicates)
            if keys and all(key in rows[0] for key in keys):
                source_predicates.append(or_(*[
                    and_(*[_column(dataset, key).is_not_distinct_from(row[key]) for key in keys])
                    for row in rows
                ]))
            source_query = select(dataset.source_column).select_from(dataset.source_relation).where(
                *source_predicates, dataset.source_column.is_not(None),
            ).distinct()
            source_ids = {int(value) for value in connection.execute(source_query).scalars()}
    description, grain, notes = DATASET_NOTES[spec.dataset]
    fields = {name: _field_metadata(name, dataset.columns[name]) for name in selected}
    for metric in spec.metrics:
        original = _field_metadata(metric.field, dataset.columns[metric.field]) if metric.field in dataset.columns else {}
        fields[metric.alias] = {
            "type": "number", "calculation": f"{metric.function}({metric.field or '*'})",
            "source_field": metric.field,
            "unit": "count" if metric.function.startswith("count") else original.get("unit", "same as input field"),
        }
    return {
        "dataset": spec.dataset, "description": description, "grain": grain,
        "query": spec.model_dump(exclude_defaults=True),
        "rows": [{key: _json_value(value) for key, value in row.items()} for row in rows],
        "row_count": len(rows), "truncated": truncated,
        "offset": spec.offset, "next_offset": spec.offset + len(rows) if truncated else None,
        "fields": fields, "notes": notes,
        "source_reference_ids": sorted(source_ids),
        "aggregation_note": "Aggregates ignore NULL values; missing/unpublished observations are never treated as zero." if spec.metrics else None,
    }, source_ids
