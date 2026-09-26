"""Model-led chat with JSON compatibility and an incremental SSE endpoint."""

import asyncio
import json
import logging
from concurrent.futures import TimeoutError as FutureTimeout
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_context import build_chat_context, load_supporting_sources
from app.services.chat_execution import ChatCancelled, ChatControl, EventSink
from app.services.chat_budget import ChatBudget
from app.services.chat_receipt import issue_receipt, verify_receipt
from app.services.nvidia_chat import (
    ChatModelConfigurationError, ChatModelUnavailableError,
    generate_chat_answer,
)
from database.connection import SessionLocal, get_db

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("uvicorn.error.chat")


def _run_chat(request: ChatRequest, db: Session, *, on_event: EventSink | None = None,
              control: ChatControl | None = None, request_id: str | None = None) -> dict:
    context = {"request_id": request_id or uuid4().hex,
               "extended_analysis": request.extended_analysis,
               "previous_turn": verify_receipt(request.previous_turn_token)}
    try:
        initial, sources = build_chat_context(request.occupation_id)
        context.update(initial)
        context["page_context"] = request.page_context
        answer = generate_chat_answer(
            request.message, context, db=db,
            selected_occupation_id=request.occupation_id,
            history=[turn.model_dump() for turn in request.history],
            on_event=on_event, control=control,
        )
        source_ids = {int(source_id) for source_id in context.get("tool_source_ids", [])}
        if source_ids:
            existing_ids = {source["source_id"] for source in sources}
            for preview in context.get("data_results", []):
                for source in preview.get("sources", []):
                    if source["source_id"] not in existing_ids:
                        sources.append(source)
                        existing_ids.add(source["source_id"])
            missing_ids = source_ids - existing_ids
            if missing_ids:
                sources.extend(load_supporting_sources(db, missing_ids))
    except ChatModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ChatModelUnavailableError as exc:
        return _chat_result(request, context,
            status="partial" if context.get("data_results") else "temporarily_unavailable", answer=(
                "Query results are available below, but the analysis was not completed. "
                if context.get("data_results") else ""
            ) + str(exc), sources=[], error_code=exc.code,
            error_stage=exc.stage or context.get("current_stage"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Telosia's database is temporarily unavailable.") from exc
    return _chat_result(request, context,
        status="partial" if context.get("budget_limited") else "answered",
        answer=answer, sources=sources)


def _chat_result(request: ChatRequest, context: dict, **outcome) -> dict:
    """Keep evidence and receipt fields consistent on success and failure."""
    result = {
        "occupation_id": request.occupation_id,
        "occupation_results": context.get("occupation_results", []),
        "data_queries": context.get("data_queries", []),
        "data_results": context.get("data_results", []),
        "tools_used": context.get("database_tool_names", []),
        "request_id": context["request_id"], "timings": context.get("timings", []),
        "elapsed_ms": context.get("elapsed_ms"),
        **outcome,
    }
    result["turn_token"] = issue_receipt(result)
    return result


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Existing JSON endpoint; Session creation alone does not connect/query."""
    return _run_chat(request, db)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    """SSE progress/text; worker owns its lazy DB Session and model client."""
    request_id = uuid4().hex

    async def events():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        control = ChatControl()

        def emit(event: str, data: dict):
            if control.disconnected:
                raise ChatCancelled("Client disconnected or request expired.")
            future = asyncio.run_coroutine_threadsafe(queue.put((event, data)), loop)
            try:
                while True:
                    try:
                        future.result(timeout=0.25)
                        return
                    except FutureTimeout:
                        if control.disconnected:
                            raise ChatCancelled("Client disconnected.")
            except BaseException:
                future.cancel()
                raise

        def worker():
            try:
                # Session is constructed/used/closed entirely in this thread.
                # No connection is checked out until a data tool requests it.
                with SessionLocal() as db:
                    result = _run_chat(payload, db, on_event=emit, control=control, request_id=request_id)
                emit("result", ChatResponse.model_validate(result).model_dump(mode="json"))
            except ChatCancelled:
                pass
            except HTTPException as exc:
                emit("answer_reset", {})
                emit("error", {"message": str(exc.detail), "request_id": request_id,
                               "error_code": "backend_unavailable"})
            except Exception as exc:
                if not control.disconnected:
                    logger.error("chat_stream_error request_id=%s type=%s", request_id, type(exc).__name__)
                    emit("answer_reset", {})
                    emit("error", {"message": "The chat request could not be completed. Please try again.",
                                   "request_id": request_id, "error_code": "internal_error"})

        task = asyncio.create_task(asyncio.to_thread(worker))
        budget = ChatBudget.configured(payload.extended_analysis)
        deadline = loop.time() + budget.total + 5
        try:
            yield _sse("status", {"request_id": request_id, "stage": "understanding", "timeout_ms": (budget.total + 15) * 1000,
                                  "message": "Understanding your question…"})
            while True:
                if await request.is_disconnected():
                    break
                remaining = deadline - loop.time()
                if remaining <= 0:
                    yield _sse("answer_reset", {"request_id": request_id})
                    yield _sse("error", {"request_id": request_id, "error_code": "request_timeout",
                                         "message": "The analysis reached its time limit. Please try a smaller question."})
                    break
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=min(10, remaining))
                except asyncio.TimeoutError:
                    if task.done() and queue.empty():
                        yield _sse("error", {"request_id": request_id, "error_code": "incomplete_stream",
                                             "message": "The request ended before a complete answer was received."})
                        break
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event, data)
                if event in {"result", "error"}:
                    break
        finally:
            control.cancel()
            # Closing the model client interrupts its active stream. Do not keep
            # an HTTP connection open while waiting for an in-flight DB read.
            task.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
