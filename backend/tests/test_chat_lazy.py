"""Chat preparation stays offline; live catalog work is bounded and cached."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session

from app.services import chat_context, chat_data
from app.services.chat_tools import ChatToolRuntime, get_chat_tools


class NoDatabaseAccess:
    def __getattribute__(self, name):
        raise AssertionError(f"Unexpected database access: {name}")


def _unexpected_read(*args, **kwargs):
    raise AssertionError("No live database work should happen during preparation")


@pytest.mark.parametrize("occupation_id", [None, 237])
def test_context_preserves_selection_without_database_access(monkeypatch, occupation_id):
    monkeypatch.setattr(chat_context, "load_supporting_sources", _unexpected_read)

    context, sources = chat_context.build_chat_context(occupation_id)
    assert context == {"selected_occupation_id": occupation_id}
    assert sources == []



def test_prompt_catalog_needs_no_database_and_does_not_claim_live_availability(monkeypatch):
    monkeypatch.setattr(chat_data, "catalog", _unexpected_read)
    monkeypatch.setattr(chat_data, "_read_connection", _unexpected_read)
    monkeypatch.setattr(chat_data, "_tables", _unexpected_read)

    result = chat_data.prompt_catalog()

    assert {item["name"] for item in result["datasets"]} == set(chat_data.DATASET_NOTES)
    assert "not confirmation" in result["availability_note"]
    assert set(result["common_fields"]) == {
        "occupation_profile", "occupation", "injury_frequency",
        "body_region_exposure", "pay_gap", "mobility_flow", "ai_exposure",
    }
    assert "median_weekly_earnings" in result["common_fields"]["occupation_profile"]
    assert "complete_coverage" in result["common_fields"]["body_region_exposure"]
    assert "is_headline_cohort" in result["common_fields"]["pay_gap"]
    assert "destination_occupation_id" in result["common_fields"]["mobility_flow"]
    result["common_fields"]["occupation"].clear()
    assert chat_data.prompt_catalog()["common_fields"]["occupation"]


def test_runtime_construction_and_calculation_do_not_load_catalog(monkeypatch):
    monkeypatch.setattr(chat_data, "catalog", _unexpected_read)
    monkeypatch.setattr(chat_data, "_read_connection", _unexpected_read)
    monkeypatch.setattr(chat_context, "load_supporting_sources", _unexpected_read)

    runtime = ChatToolRuntime(NoDatabaseAccess())
    assert {tool["function"]["name"] for tool in get_chat_tools()} == {
        "describe_data", "query_data", "calculate", "search_knowledge",
    }
    assert runtime._catalog is None
    runtime.results["q1"] = {
        "dataset": "occupation_profile", "rows": [{"employed": 100}, {"employed": 150}],
        "fields": {"employed": {"unit": "people"}},
    }
    result = runtime.execute("calculate", {
        "operation": "difference", "operands": [
            {"query_id": "q1", "row": 1, "field": "employed"},
            {"query_id": "q1", "row": 0, "field": "employed"},
        ],
    })
    assert result["result"] == 50
    assert runtime._catalog is None


@pytest.fixture
def fake_live_catalog(monkeypatch):
    """Real engine identities and table metadata, without connecting or writing."""
    engines = [create_engine("sqlite://"), create_engine("sqlite://")]
    tables = [
        {"occupation": Table(
            "occupation", MetaData(), Column("occupation_id", Integer, primary_key=True),
            Column("occupation_title", String), schema="telosia",
        )},
        {"occupation_profile": Table(
            "occupation_profile", MetaData(), Column("occupation_id", Integer),
            Column("employed", Integer), schema="telosia",
        )},
    ]
    table_sets = dict(zip(engines, tables))
    reads = []
    now = [100.0]

    @contextmanager
    def read_connection(db):
        engine = chat_data._session_engine(db)
        reads.append(engine)
        yield SimpleNamespace(engine=engine)

    monkeypatch.setattr(chat_data, "_read_connection", read_connection)
    monkeypatch.setattr(chat_data, "_tables", lambda connection: table_sets[connection.engine])
    monkeypatch.setattr(chat_data, "monotonic", lambda: now[0])
    chat_data.clear_catalog_cache()
    try:
        yield SimpleNamespace(engines=engines, reads=reads, now=now)
    finally:
        chat_data.clear_catalog_cache()
        for engine in engines:
            engine.dispose()


def test_live_catalog_cache_reuses_engine_across_sessions_and_expires(fake_live_catalog):
    state = fake_live_catalog
    engine = state.engines[0]
    with Session(engine) as first, Session(engine) as second:
        original = chat_data.catalog(first)
        cached = chat_data.catalog(second)
        assert original == cached
        assert state.reads == [engine]

        original["datasets"][0]["fields"].clear()
        assert "occupation_id" in chat_data.catalog(first)["datasets"][0]["fields"]
        state.now[0] += chat_data.CATALOG_CACHE_TTL_SECONDS - 1
        chat_data.catalog(second)
        assert state.reads == [engine]
        state.now[0] += 1
        chat_data.catalog(second)
        assert state.reads == [engine, engine]


def test_live_catalog_cache_isolates_engines_and_can_invalidate_one(fake_live_catalog):
    state = fake_live_catalog
    first_engine, second_engine = state.engines
    with Session(first_engine) as first, Session(second_engine) as second:
        assert [item["name"] for item in chat_data.catalog(first)["datasets"]] == ["occupation"]
        assert [item["name"] for item in chat_data.catalog(second)["datasets"]] == ["occupation_profile"]
        chat_data.clear_catalog_cache(first_engine)
        chat_data.catalog(second)
        assert state.reads == [first_engine, second_engine]
        chat_data.catalog(first)
        assert state.reads == [first_engine, second_engine, first_engine]


def test_describe_data_is_the_first_live_catalog_access(fake_live_catalog):
    state = fake_live_catalog
    engine = state.engines[0]
    with Session(engine) as session:
        runtime = ChatToolRuntime(session)
        chat_data.prompt_catalog()
        assert state.reads == []
        result = runtime.execute("describe_data", {"dataset": "occupation"})
        assert "occupation_id" in result["dataset"]["fields"]
        assert state.reads == [engine]
        runtime.execute("describe_data", {})
        assert state.reads == [engine]
