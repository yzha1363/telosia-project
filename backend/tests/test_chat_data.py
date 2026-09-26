"""Query behavior with an isolated SQLite copy of a tiny public-data schema."""

import os

import pytest
from pydantic import ValidationError
from sqlalchemy import (
    Boolean, Column, Float, Integer, MetaData, String, Table, create_engine, text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.services.chat_data import (
    DataQuery, _build_statement, _dataset, _read_connection, _tables,
    catalog, get_query_schema, query_dataset,
)


@pytest.fixture
def public_db(monkeypatch):
    # Importing Sam's route module initialises the shared DB module, but these
    # tests never use that engine. An actual PostgreSQL service is not required.
    if not os.getenv("DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", "sqlite://")
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS telosia")
        metadata = MetaData(schema="telosia")
        occupations = Table("occupation", metadata,
            Column("occupation_id", Integer, primary_key=True),
            Column("occupation_title", String), Column("anzsco_code", String),
            Column("is_profile_occupation", Boolean))
        hazards = Table("hazard_variable", metadata,
            Column("hazard_variable_id", Integer, primary_key=True),
            Column("hazard_variable", String), Column("hazard_category", String))
        exposure = Table("hazard_exposure", metadata,
            Column("hazard_exposure_id", Integer, primary_key=True),
            Column("occupation_id", Integer), Column("hazard_variable_id", Integer),
            Column("exposure_score", Float), Column("source_reference_id", Integer))
        frequency = Table("injury_frequency", metadata,
            Column("injury_frequency_id", Integer, primary_key=True),
            Column("occupation_id", Integer), Column("financial_year", String),
            Column("measure_type", String), Column("frequency_rate", Float),
            Column("is_suppressed", Boolean), Column("source_reference_id", Integer))
        pay_gap = Table("pay_gap", metadata,
            Column("pay_gap_id", Integer, primary_key=True),
            Column("parent_occupation_id", Integer), Column("anzsco_6digit_code", String),
            Column("anzsco_6digit_title", String), Column("cohort", String),
            Column("is_headline_cohort", Boolean), Column("gender_pay_gap", Float),
            Column("female_income_median", Float), Column("source_reference_id", Integer))
        categories = Table("nds_category", metadata,
            Column("nds_category_id", Integer, primary_key=True),
            Column("dimension", String), Column("category_label", String), Column("level", String))
        claims = Table("nds_claim_statistic", metadata,
            Column("nds_claim_statistic_id", Integer, primary_key=True),
            Column("nds_category_id", Integer), Column("measure", String),
            Column("unit", String), Column("value", Float), Column("source_reference_id", Integer))
        # Intentionally not an allowlisted public dataset, even inside telosia.
        Table("user_credentials", metadata, Column("password", String))
        metadata.create_all(connection)
        connection.execute(occupations.insert(), [
            {"occupation_id": i, "occupation_title": name, "anzsco_code": str(1000+i), "is_profile_occupation": True}
            for i, name in enumerate(["High exposure", "Incomplete", "Missing", "Measured zero"], 1)
        ])
        connection.execute(hazards.insert(), [
            {"hazard_variable_id": 1, "hazard_variable": "Spend Time Standing", "hazard_category": "Body Positioning"},
            {"hazard_variable_id": 2, "hazard_variable": "Spend Time Walking and Running", "hazard_category": "Body Positioning"},
        ])
        connection.execute(exposure.insert(), [
            {"occupation_id": job, "hazard_variable_id": hazard, "exposure_score": score, "source_reference_id": source}
            for job, hazard, score, source in [(1, 1, 10, 7), (1, 2, 80, 8), (2, 1, 20, 7), (4, 1, 0, 7), (4, 2, 0, 7)]
        ])
        connection.execute(frequency.insert(), [
            {"occupation_id": job, "financial_year": year, "measure_type": "claims_per_million_hours", "frequency_rate": rate,
             "is_suppressed": rate is None, "source_reference_id": source}
            for job, year, rate, source in [(1, "2020-21", 2, 2), (1, "2021-22", None, 3), (1, "2022-23", 6, 2), (2, "2022-23", 10, 4)]
        ])
        connection.execute(pay_gap.insert(), [
            {"parent_occupation_id": 1, "anzsco_6digit_code": "100101", "anzsco_6digit_title": "Specialist A",
             "cohort": "Whole workforce", "is_headline_cohort": True, "gender_pay_gap": .74,
             "female_income_median": 30000, "source_reference_id": 5},
            {"parent_occupation_id": 1, "anzsco_6digit_code": "100102", "anzsco_6digit_title": "Specialist B",
             "cohort": "Whole workforce", "is_headline_cohort": True, "gender_pay_gap": None,
             "female_income_median": None, "source_reference_id": 5},
        ])
        connection.execute(categories.insert(), [{"nds_category_id": 1, "dimension": "occupation",
                                                   "category_label": "Published broad group", "level": "sub_major_group"}])
        connection.execute(claims.insert(), [
            {"nds_category_id": 1, "measure": measure, "unit": unit, "value": value, "source_reference_id": 6}
            for measure, unit, value in [("claim_count", "claims", 20),
                                        ("frequency_rate", "claims per million hours worked", 2)]
        ])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_catalog_allows_public_datasets_and_enriches_foreign_keys(public_db):
    descriptions = {entry["name"]: entry for entry in catalog(public_db)["datasets"]}
    assert "user_credentials" not in descriptions
    assert "occupation_title" in descriptions["pay_gap"]["fields"]
    assert descriptions["pay_gap"]["fields"]["gender_pay_gap"]["unit"].startswith("fraction")
    assert "complete_coverage" in descriptions["body_region_exposure"]["fields"]


def test_leg_scores_reuse_max_mapping_and_do_not_replace_missing_with_zero(public_db):
    result, sources = query_dataset(public_db, {
        "dataset": "body_region_exposure",
        "filters": [{"field": "region", "op": "eq", "value": "Legs and feet"}],
        "order_by": [{"field": "score", "direction": "asc"}],
    })
    rows = result["rows"]
    assert [r["occupation_id"] for r in rows] == [4, 2, 1, 3]
    assert [r["score"] for r in rows] == [0, 20, 80, None]
    assert [r["complete_coverage"] for r in rows] == [True, False, True, False]
    assert [r["available_variable_count"] for r in rows] == [2, 1, 2, 0]
    assert all(r["expected_variable_count"] == 2 for r in rows)
    assert sources == {7, 8}


def test_low_exposure_ranking_can_exclude_incomplete_coverage(public_db):
    result, _ = query_dataset(public_db, {
        "dataset": "body_region_exposure",
        "filters": [{"field": "region", "op": "eq", "value": "Legs and feet"},
                    {"field": "complete_coverage", "op": "eq", "value": True}],
        "order_by": [{"field": "score", "direction": "asc"}],
    })
    assert [r["occupation_id"] for r in result["rows"]] == [4, 1]


def test_sources_only_cover_returned_page_and_include_all_region_contributors(public_db):
    first, first_sources = query_dataset(public_db, {
        "dataset": "body_region_exposure", "select": ["occupation_id", "region", "score"],
        "filters": [{"field": "region", "op": "eq", "value": "Legs and feet"},
                    {"field": "complete_coverage", "op": "eq", "value": True}],
        "order_by": [{"field": "score", "direction": "asc"}], "limit": 1,
    })
    assert first["truncated"] is True and first["next_offset"] == 1
    assert first_sources == {7}
    second, second_sources = query_dataset(public_db, {**first["query"], "offset": 1})
    assert second["rows"][0]["score"] == 80
    assert second_sources == {7, 8}


def test_grouping_ignores_null_values_and_retains_suppression_source(public_db):
    result, sources = query_dataset(public_db, {
        "dataset": "injury_frequency", "group_by": ["occupation_id", "occupation_title"],
        "metrics": [{"function": "avg", "field": "frequency_rate", "alias": "mean_rate"},
                    {"function": "count", "field": "frequency_rate", "alias": "published_years"},
                    {"function": "count", "alias": "all_years"}],
        "order_by": [{"field": "mean_rate", "direction": "asc"}], "limit": 1,
    })
    assert result["rows"] == [{"occupation_id": 1, "occupation_title": "High exposure", "mean_rate": 4,
                               "published_years": 2, "all_years": 3}]
    assert sources == {2, 3}


def test_pay_gap_preserves_specialisations_fractions_and_nulls(public_db):
    result, sources = query_dataset(public_db, {
        "dataset": "pay_gap", "select": ["anzsco_6digit_code", "gender_pay_gap", "occupation_title"],
        "order_by": [{"field": "gender_pay_gap", "direction": "desc"}],
    })
    assert [r["gender_pay_gap"] for r in result["rows"]] == [.74, None]
    assert len({r["anzsco_6digit_code"] for r in result["rows"]}) == 2
    assert sources == {5}


def test_nds_different_measures_require_distinct_unit_and_dimension_groups(public_db):
    with pytest.raises(ValueError, match="filter or group by measure"):
        query_dataset(public_db, {"dataset": "nds_claim_statistic", "metrics": [
            {"function": "avg", "field": "value", "alias": "average"},
        ]})
    result, sources = query_dataset(public_db, {
        "dataset": "nds_claim_statistic", "group_by": ["measure", "unit", "dimension"],
        "metrics": [{"function": "avg", "field": "value", "alias": "average"}],
    })
    assert {row["measure"]: row["average"] for row in result["rows"]} == {"claim_count": 20, "frequency_rate": 2}
    assert sources == {6}
    with pytest.raises(ValueError, match="NDS sums require"):
        query_dataset(public_db, {
            "dataset": "nds_claim_statistic", "group_by": ["measure", "unit", "dimension"],
            "metrics": [{"function": "sum", "field": "value", "alias": "total"}],
        })


@pytest.mark.parametrize("query", [
    {"dataset": "user_credentials"},
    {"dataset": "occupation; DROP TABLE occupation"},
    {"dataset": "occupation", "select": ["occupation_title; DROP TABLE occupation"]},
    {"dataset": "occupation", "limit": 101},
    {"dataset": "occupation", "limit": True},
    {"dataset": "occupation", "sql": "DELETE FROM telosia.occupation"},
    {"dataset": "occupation", "metrics": [{"function": "count", "alias": "x); DROP TABLE occupation;--"}]},
    {"dataset": "occupation", "filters": [{"field": "occupation_id", "op": "eq", "value": "1 OR 1=1"}]},
    {"dataset": "occupation", "filters": [{"field": "occupation_id", "op": "in", "value": list(range(101))}]},
    {"dataset": "injury_frequency", "metrics": [{"function": "sum", "field": "frequency_rate", "alias": "total"}]},
    {"dataset": "pay_gap", "metrics": [{"function": "avg", "field": "female_income_median", "alias": "mean_income"}]},
    {"dataset": "pay_gap", "metrics": [{"function": "avg", "field": "gender_pay_gap", "alias": "mean_gap"}]},
])
def test_invalid_queries_are_rejected(public_db, query):
    with pytest.raises((ValueError, ValidationError)):
        query_dataset(public_db, query)


def test_injection_text_remains_a_bound_value_and_like_wildcards_are_literal(public_db):
    attack = "%' OR 1=1; DROP TABLE occupation; --"
    spec = DataQuery(dataset="occupation", filters=[{"field": "occupation_title", "op": "contains", "value": attack}])
    with _read_connection(public_db) as connection:
        statement, _, _ = _build_statement(_dataset(spec.dataset, _tables(connection)), spec)
        compiled = statement.compile(dialect=postgresql.dialect())
    assert attack not in str(compiled)
    assert any(isinstance(value, str) and "DROP TABLE occupation" in value for value in compiled.params.values())
    result, _ = query_dataset(public_db, spec.model_dump())
    assert result["rows"] == []
    count, _ = query_dataset(public_db, {"dataset": "occupation", "metrics": [{"function": "count", "alias": "rows"}]})
    assert count["rows"][0]["rows"] == 4


def test_schema_is_inlined_for_openai_compatible_tool_payload():
    schema = get_query_schema()
    assert "$defs" not in schema
    assert schema["properties"]["metrics"]["items"]["properties"]["function"]["enum"] == [
        "count", "count_distinct", "min", "max", "avg", "sum",
    ]


def test_nds_generic_value_column_does_not_allow_pooling_published_medians(public_db):
    with public_db.get_bind().begin() as connection:
        connection.execute(text("""INSERT INTO telosia.nds_claim_statistic
            (nds_category_id, measure, unit, value, source_reference_id)
            VALUES (1, 'median_compensation', 'AUD', 1234, 6)"""))
    query = {"dataset": "nds_claim_statistic", "group_by": ["measure", "unit", "dimension"],
             "metrics": [{"function": "avg", "field": "value", "alias": "mean_value"}]}
    with pytest.raises(ValueError, match="published medians"):
        query_dataset(public_db, query)
    query["filters"] = [{"field": "measure", "op": "eq", "value": "frequency_rate"}]
    result, _ = query_dataset(public_db, query)
    assert result["rows"][0]["mean_value"] == 2
