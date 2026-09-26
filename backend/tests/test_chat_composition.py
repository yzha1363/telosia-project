"""A model can ask for validated query + arithmetic in a single tool round."""

from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from app.services import chat_context, chat_data, nvidia_chat
from app.services.chat_tools import ChatToolRuntime, get_chat_tools


@pytest.fixture
def query_stub(monkeypatch):
    source = {
        "dataset": "occupation_profile",
        "rows": [{"occupation_title": "Example A", "median_weekly_earnings": 1800},
                 {"occupation_title": "Example B", "median_weekly_earnings": 1200}],
        "fields": {"median_weekly_earnings": {"unit": "AUD/week; published median"}},
        "truncated": False,
    }
    requests = []
    def query(db, arguments):
        requests.append(deepcopy(arguments))
        return deepcopy(source), {3}
    monkeypatch.setattr(chat_data, "query_dataset", query)
    monkeypatch.setattr(chat_context, "load_supporting_sources", lambda *_: [{
        "source_id": 3, "publisher": "Fixture", "dataset_title": "Synthetic data",
    }])
    return source, requests


def test_sources_are_reused_only_within_one_request(query_stub, monkeypatch):
    loads = []

    def load_sources(db, ids):
        loads.append(set(ids))
        return [{"source_id": source_id, "publisher": "Fixture"} for source_id in sorted(ids)]

    monkeypatch.setattr(chat_context, "load_supporting_sources", load_sources)
    runtime = ChatToolRuntime(object())
    first = runtime.execute("query_data", {"dataset": "occupation_profile"})
    first["sources"][0]["publisher"] = "Changed by caller"
    second = runtime.execute("query_data", {"dataset": "occupation_profile"})
    assert loads == [{3}]
    assert second["sources"] == [{"source_id": 3, "publisher": "Fixture"}]
    assert runtime.previews["q2"]["sources"] == second["sources"]
    ChatToolRuntime(object()).execute("query_data", {"dataset": "occupation_profile"})
    assert loads == [{3}, {3}]


def query_arguments(operation="absolute_difference"):
    return {"dataset": "occupation_profile", "select": ["occupation_title", "median_weekly_earnings"],
            "order_by": [{"field": "median_weekly_earnings", "direction": "desc"}], "limit": 2,
            "calculations": [{"operation": operation, "operands": [
                {"row": 0, "field": "median_weekly_earnings"},
                {"row": 1, "field": "median_weekly_earnings"},
            ]}]}


def test_composed_query_returns_actual_rows_calculation_and_sources(query_stub):
    source, requests = query_stub
    runtime = ChatToolRuntime(object())
    arguments = query_arguments()
    original = deepcopy(arguments)
    result = runtime.execute("query_data", arguments)
    assert arguments == original
    assert "calculations" not in requests[0]
    assert result["query_id"] == "q1"
    assert result["rows"] == source["rows"]
    assert result["calculations"][0]["result"] == 600
    assert result["calculations"][0]["operands"][0]["query_id"] == "q1"
    assert result["sources"][0]["source_id"] == 3
    assert runtime.source_ids == {3}
    assert runtime.tools_used == ["query_data"]


@pytest.mark.parametrize("operation", ["sum", "mean", "median", "percentage_point_difference"])
def test_composition_keeps_unit_and_median_guards(query_stub, operation):
    result = ChatToolRuntime(object()).execute("query_data", query_arguments(operation))
    assert result["rows"]
    assert "error" in result["calculations"][0]
    assert "result" not in result["calculations"][0]


@pytest.mark.parametrize("rows", [[{"median_weekly_earnings": None}, {"median_weekly_earnings": 1200}], []])
def test_composition_does_not_invent_missing_cells(query_stub, rows):
    source, _ = query_stub
    source["rows"] = rows
    result = ChatToolRuntime(object()).execute("query_data", query_arguments())
    calculation = result["calculations"][0]
    assert calculation.get("unavailable") or calculation.get("error")
    assert "result" not in calculation


@pytest.mark.parametrize("invalid", [
    [{"operation": "eval", "operands": []}],
    [{"operation": "difference", "operands": [{"row": 0, "field": "x", "query_id": "invented"}]}],
    query_arguments()["calculations"] * 6,
])
def test_malformed_composition_is_rejected_before_db(query_stub, invalid):
    _, requests = query_stub
    arguments = query_arguments()
    arguments["calculations"] = invalid
    assert "error" in ChatToolRuntime(object()).execute("query_data", arguments)
    assert requests == []


def test_exposure_calculations_use_the_returned_rounded_cells(query_stub):
    source, _ = query_stub
    source.update(dataset="body_region_exposure", rows=[{"score": 13.5}, {"score": 14.75}],
                  fields={"score": {"unit": "maximum contributing exposure index, 0-100"}})
    result = ChatToolRuntime(object()).execute("query_data", {
        "dataset": "body_region_exposure", "select": ["score"],
        "calculations": [{"operation": "difference", "operands": [
            {"row": 1, "field": "score"}, {"row": 0, "field": "score"},
        ]}],
    })
    assert result["rows"] == [{"score": 14}, {"score": 15}]
    assert result["calculations"][0]["result"] == 1


def test_tool_schema_documents_composition_without_changing_db_contract():
    tools = {item["function"]["name"]: item["function"] for item in get_chat_tools()}
    schema = tools["query_data"]["parameters"]
    assert schema["properties"]["calculations"]["maxItems"] == 5
    assert "query_id" not in schema["properties"]["calculations"]["items"]["properties"]["operands"]["items"]["properties"]
    assert "calculations" not in chat_data.get_query_schema()["properties"]
    assert "$ref" not in json.dumps(tools)


def test_model_query_and_comparison_complete_in_two_rounds(query_stub, monkeypatch):
    call = NS(id="one", function=NS(name="query_data", arguments=json.dumps(query_arguments())))
    replies = iter([
        NS(choices=[NS(message=NS(content=None, tool_calls=[call]), finish_reason="tool_calls")]),
        NS(choices=[NS(message=NS(content="The published weekly earnings differ by AUD 600.", tool_calls=[]), finish_reason="stop")]),
    ])
    requests = []
    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        return next(replies)
    monkeypatch.setattr(nvidia_chat, "_create_client", lambda: NS(
        chat=NS(completions=NS(create=create)), close=lambda: None,
    ))
    context = {}
    answer = nvidia_chat.generate_chat_answer("Compare weekly earnings.", context, db=object())
    assert "600" in answer and len(requests) == 2
    assert context["database_tool_names"] == ["query_data"]
    evidence = json.loads(requests[1]["messages"][-1]["content"])
    assert evidence["calculations"][0]["result"] == 600
    assert context["tool_source_ids"] == [3]
