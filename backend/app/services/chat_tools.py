"""General data tools selected by the model, with request-local evidence."""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class ResultReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str = Field(min_length=1, max_length=20)
    row: int = Field(ge=0, le=99)
    field: str = Field(min_length=1, max_length=100)


class Calculation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str = Field(pattern="^(difference|absolute_difference|percentage_point_difference|ratio|percent_change|sum|mean|min|max|median)$")
    operands: list[ResultReference] = Field(min_length=1, max_length=100)


class QueryCell(BaseModel):
    """A cell in the query being requested; no guessed future query ID."""
    model_config = ConfigDict(extra="forbid")
    row: int = Field(ge=0, le=99)
    field: str = Field(min_length=1, max_length=100)


class QueryCalculation(Calculation):
    operands: list[QueryCell] = Field(min_length=1, max_length=100)


class QueryCalculations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculations: list[QueryCalculation] = Field(default_factory=list, max_length=5)


def _inline_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    def expand(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].rsplit("/", 1)[-1]])
            return {key: expand(item) for key, item in value.items() if key != "title"}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value
    return expand(schema)


def get_chat_tools() -> list[dict[str, Any]]:
    from app.services.chat_data import get_query_schema

    query_schema = get_query_schema()
    query_schema["properties"]["calculations"] = _inline_schema(QueryCalculations)["properties"]["calculations"]

    def tool(name: str, description: str, parameters: dict) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": description, "parameters": parameters,
        }}

    return [
        tool("describe_data", "Check live dataset availability or inspect fields, units, grain and calculation rules when uncertain. Known fields in the prompt catalog can be queried directly. No occupation selection required.", {
            "type": "object", "properties": {"dataset": {"type": "string"}},
            "additionalProperties": False,
        }),
        tool("query_data", "Select/filter/group/aggregate/sort/page a public dataset. Query known fields directly; describe_data is optional. For a comparison within these rows, attach calculations:[{operation,operands:[{row,field},...]}] (zero-based rows, no query_id) to get data AND arithmetic in ONE call. Returns query_id, rows, calculations and sources. Rankings use the database, not RAG.", query_schema),
        tool("calculate", "Arithmetic across previously returned query cells in THIS request; use query_data.calculations for arithmetic on a single new query. Operands use query_id, zero-based row and field. difference=a-b; absolute_difference=abs(a-b); percentage_point_difference=(a-b)*100 for fractions only; ratio=a/b; percent_change=(new-old)/old*100 with [old,new]. sum/mean/min/max/median cover referenced cells only, not a whole dataset.", _inline_schema(Calculation)),
        tool("search_knowledge", "Retrieve documented definitions and reviewed hazard association evidence from local RAG. Use for mapping/evidence explanations, not occupation rankings or numeric database values. Missing RAG does not prevent database queries.", {
            "type": "object", "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 500},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
            }, "required": ["query"], "additionalProperties": False,
        }),
    ]


class ChatToolRuntime:
    """One turn's queries, calculations, provenance and execution trace."""

    def __init__(self, db: Session):
        self.db = db
        self.source_ids: set[int] = set()
        self._sources: dict[int, dict[str, Any]] = {}
        self._loaded_source_ids: set[int] = set()
        self.results: dict[str, dict[str, Any]] = {}
        self.data_queries: list[dict[str, Any]] = []
        self.tools_used: list[str] = []
        self.occupation_results: list[dict[str, Any]] = []
        self._catalog: dict[str, Any] | None = None
        self.previews: dict[str, dict[str, Any]] = {}

    def catalog(self) -> dict[str, Any]:
        if self._catalog is None:
            from app.services.chat_data import catalog
            self._catalog = catalog(self.db)
        return self._catalog

    def overview(self) -> dict[str, Any]:
        data = self.catalog()
        return {
            "datasets": [{key: dataset.get(key) for key in ("name", "description", "grain")}
                         for dataset in data["datasets"]],
            "query_notes": data.get("query_notes", []),
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return correctable errors to the model without exposing DB internals."""
        self.tools_used.append(name)
        try:
            if name == "describe_data":
                dataset = arguments.get("dataset")
                if not dataset:
                    return self.overview()
                for descriptor in self.catalog()["datasets"]:
                    if descriptor["name"] == dataset:
                        return {"dataset": descriptor, "query_notes": self.catalog().get("query_notes", [])}
                return {"error": "Unknown dataset. Call describe_data without a dataset for available names."}
            if name == "query_data":
                return self._query(arguments)
            if name == "calculate":
                return self._calculate(Calculation.model_validate(arguments))
            if name == "search_knowledge":
                return self._knowledge(arguments)
            return {"error": "Unknown tool. Use one of the supplied tool names."}
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            return {"error": str(exc)[:1500], "retryable": True}
        except SQLAlchemyError:
            return {"error": "The database query could not be completed. Check fields and filters, or report that data is temporarily unavailable.", "retryable": False}

    def _query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.services.chat_data import query_dataset
        from app.services.chat_context import load_supporting_sources

        # Validate calculation structure before any DB access. DataQuery remains
        # the strict database-only contract; this composition is chat-local.
        query_arguments = dict(arguments)
        calculations = QueryCalculations.model_validate({
            "calculations": query_arguments.pop("calculations", []),
        }).calculations
        data, source_ids = query_dataset(self.db, query_arguments)
        query_id = f"q{len(self.results) + 1}"
        data = dict(data, query_id=query_id)
        # SQL orders original scores, but the data plan requires whole-number
        # display. Calculation references use these same returned cells.
        exposure_fields = {field for field, metadata in data.get("fields", {}).items()
                           if "exposure index" in metadata.get("unit", "")}
        if exposure_fields:
            data["rows"] = [{field: round(value) if field in exposure_fields and isinstance(value, (float, int)) else value
                             for field, value in row.items()} for row in data.get("rows", [])]
            data["presentation_note"] = "Exposure indices are rounded to whole numbers; ranking/filtering used original values before rounding. Calculations on these returned cells use rounded values."
        self.results[query_id] = data
        self.source_ids.update(source_ids)
        missing_sources = source_ids - self._loaded_source_ids
        if missing_sources:
            self._sources.update((source["source_id"], source)
                                 for source in load_supporting_sources(self.db, missing_sources))
            self._loaded_source_ids.update(missing_sources)
        data["sources"] = [dict(self._sources[source_id]) for source_id in sorted(source_ids)
                           if source_id in self._sources]
        self.data_queries.append({
            "query_id": query_id, "dataset": arguments["dataset"],
            "row_count": len(data.get("rows", [])), "truncated": bool(data.get("truncated", False)),
        })
        if calculations:
            data["calculations"] = []
            for calculation in calculations:
                resolved = Calculation(
                    operation=calculation.operation,
                    operands=[ResultReference(query_id=query_id, **cell.model_dump())
                              for cell in calculation.operands],
                )
                try:
                    result = self._calculate(resolved)
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    # Keep valid query evidence even when arithmetic is invalid.
                    # Missing rows/units never become invented values.
                    result = {"operation": calculation.operation, "error": str(exc)[:1000]}
                data["calculations"].append(result)
        # Generic analysis can query candidates, then discard them in a later
        # comparison. Do not turn intermediate rows into final recommendation
        # cards; the grounded final answer names the relevant occupations.
        columns = list(data.get("columns") or (list(data["rows"][0]) if data.get("rows") else data.get("fields", {})))
        self.previews[query_id] = {
            "query_id": query_id, "dataset": arguments["dataset"],
            "columns": columns, "rows": data.get("rows", [])[:10],
            "row_count": len(data.get("rows", [])),
            "truncated": bool(data.get("truncated", False)),
            "fields": data.get("fields", {}), "sources": data.get("sources", []),
            "query": data.get("query", {}), "notes": data.get("notes", []),
            "notice": "Query evidence, not a final recommendation. Missing values are not zero.",
        }
        if arguments["dataset"] in {"body_region_exposure", "hazard_exposure"}:
            self.previews[query_id]["notice"] += (
                " BOHD is a beta snapshot derived partly from U.S. O*NET mapped to Australian occupations."
                " Rounded exposure indices are not injury probabilities or medical suitability; rankings use original values."
            )
        return data

    @staticmethod
    def _cell_context(data: dict, row: dict, field: str):
        if row.get(field) is not None:
            return row[field]
        for item in data.get("query", {}).get("filters", []):
            if item.get("field") == field:
                if item.get("op") == "eq":
                    return item.get("value")
                if item.get("op") == "in" and len(item.get("value", [])) == 1:
                    return item["value"][0]
        return None

    def _calculate(self, calculation: Calculation) -> dict[str, Any]:
        values = []
        units = []
        contexts = []
        median_inputs = False
        for reference in calculation.operands:
            data = self.results.get(reference.query_id)
            if data is None:
                raise ValueError("Unknown query_id. Use cells from a successful query_data call in this turn.")
            rows = data.get("rows", [])
            if reference.row >= len(rows) or reference.field not in rows[reference.row]:
                raise ValueError("The referenced result row or field does not exist.")
            value = rows[reference.row][reference.field]
            if value is None:
                return {"unavailable": True, "reason": "A referenced value is not published. No value was estimated."}
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Calculations require finite numeric query-result cells.")
            values.append(value)
            metadata = data.get("fields", {}).get(reference.field, {})
            is_count = metadata.get("calculation", "").startswith("count")
            field = reference.field if is_count else (metadata.get("source_field") or reference.field)
            unit = metadata.get("unit")
            # Missing unit metadata permits same-field comparisons, not mixing
            # two unknown measures or treating an identifier as a percentage.
            if not unit or unit == "same as input field":
                unit = f"{data.get('dataset')}.{field}"
            if str(unit).startswith("fraction"):
                unit = "fraction"
            if field.endswith("_id") or field.endswith("_code"):
                raise ValueError("Identifiers are not numeric measures.")
            median_inputs = median_inputs or (not is_count and ("median" in field or "published median" in unit))
            row = rows[reference.row]
            context = None
            if data.get("dataset") == "nds_claim_statistic" and field == "value" and not is_count:
                details = [self._cell_context(data, row, key) for key in ("measure", "unit", "dimension", "level")]
                if any(value is None for value in details):
                    raise ValueError("Include or filter NDS measure, unit, dimension and level before calculating.")
                context = tuple(details)
                unit = details[1]
                median_inputs = median_inputs or "median" in str(details[0])
            if data.get("dataset") == "pay_gap" and not metadata.get("calculation", "").startswith("count"):
                cohort = self._cell_context(data, row, "cohort")
                if cohort is None and self._cell_context(data, row, "is_headline_cohort") is True:
                    cohort = "headline cohort"
                if cohort is None:
                    raise ValueError("Include cohort or filter is_headline_cohort=true before calculating pay-gap comparisons.")
                context = ("pay_gap", cohort)
            if data.get("dataset") == "regional_employment" and calculation.operation == "sum":
                period = self._cell_context(data, row, "reference_date")
                if period is None:
                    raise ValueError("Include or filter reference_date before summing regional employment snapshots.")
                context = ("regional_employment", period)
            units.append(unit)
            contexts.append(context)
        op = calculation.operation
        if op in {"difference", "absolute_difference", "percentage_point_difference", "ratio", "percent_change"} and len(values) != 2:
            raise ValueError("This calculation requires exactly two operands.")
        if len(set(units)) != 1:
            raise ValueError("Operands must have comparable units; do not combine yearly pay, weekly pay, counts and exposure scores.")
        if len(set(contexts)) != 1:
            raise ValueError("Operands have incompatible cohorts or classification measures. Query comparable records first.")
        if op == "percentage_point_difference" and units[0] != "fraction":
            raise ValueError("percentage_point_difference accepts fractions only; use difference for already-percent values.")
        if op in {"sum", "mean", "median"} and median_inputs:
            raise ValueError("Published medians cannot be pooled. Compare them individually with difference, ratio, min or max.")
        if op == "sum" and units[0] not in {"count", "people", "estimated people", "recorded worker movements", "claims"}:
            raise ValueError("Use query_data for dataset aggregates so rates, medians and units can be checked.")
        if (op == "ratio" and values[1] == 0) or (op == "percent_change" and values[0] == 0):
            return {"unavailable": True, "reason": "The requested calculation would divide by zero."}
        if op == "difference":
            result = values[0] - values[1]
        elif op == "absolute_difference":
            result = abs(values[0] - values[1])
        elif op == "percentage_point_difference":
            result = (values[0] - values[1]) * 100
        elif op == "ratio":
            result = values[0] / values[1]
        elif op == "percent_change":
            result = (values[1] - values[0]) / values[0] * 100
        elif op == "sum":
            result = sum(values)
        elif op == "mean":
            result = sum(values) / len(values)
        elif op == "min":
            result = min(values)
        elif op == "max":
            result = max(values)
        else:
            result = median(values)
        if not math.isfinite(result):
            raise ValueError("The calculation did not produce a finite result.")
        return {"operation": op, "operands": [ref.model_dump() for ref in calculation.operands],
                "values": values, "result": round(result, 6),
                "unit": {"percentage_point_difference": "percentage points", "percent_change": "percent", "ratio": "ratio"}.get(op, units[0]),
                "scope": "Only the referenced query-result cells; means are unweighted, not a pooled population statistic."}

    def _knowledge(self, arguments: dict) -> dict:
        query = arguments.get("query")
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 500:
            raise ValueError("Provide a knowledge query of 2 to 500 characters.")
        top_k = max(1, min(5, int(arguments.get("top_k", 3))))
        try:
            from app.services.rag_retriever import retrieve_knowledge
            documents = retrieve_knowledge(query, top_k=top_k)
        except Exception:
            return {"available": False, "documents": [], "message": "Local knowledge search is temporarily unavailable. Database queries remain available."}
        return {"available": True, "documents": documents,
                "note": "Similarity is relevance, not risk. Association labels are separate from published BOHD scores; preserve review_status and document attribution."}
