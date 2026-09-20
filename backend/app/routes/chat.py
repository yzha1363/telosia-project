"""Restricted, data-grounded chatbot endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_context import (
    NEEDS_OCCUPATION_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    build_chat_context,
    is_in_scope,
    load_supporting_sources,
    requires_occupation,
)
from app.services.chat_intent import parse_occupation_demand_intent
from app.services.nvidia_chat import (
    ChatModelConfigurationError,
    ChatModelUnavailableError,
    generate_chat_answer,
)
from app.services.occupation_demand_search import (
    OccupationDemandConfigurationError,
    build_occupation_demand_answer,
    rank_occupations_by_body_demand,
)
from app.services.rag_retriever import RagConfigurationError
from database.connection import get_db


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Answer only questions grounded in Telosia's published datasets."""

    if not is_in_scope(request.message):
        return {
            "status": "out_of_scope",
            "answer": OUT_OF_SCOPE_ANSWER,
            "occupation_id": request.occupation_id,
            "sources": [],
        }

    demand_intent = parse_occupation_demand_intent(request.message)
    if demand_intent is not None:
        try:
            occupation_results, source_ids = (
                rank_occupations_by_body_demand(
                    db=db,
                    intent=demand_intent,
                    limit=4,
                )
            )
        except OccupationDemandConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "status": "answered",
            "answer": build_occupation_demand_answer(
                demand_intent,
                occupation_results,
            ),
            # This is a cross-occupation comparison. A currently selected
            # occupation must not narrow or label the result set.
            "occupation_id": None,
            "occupation_results": occupation_results,
            "sources": load_supporting_sources(db, source_ids),
        }

    if request.occupation_id is None and requires_occupation(request.message):
        return {
            "status": "needs_occupation",
            "answer": NEEDS_OCCUPATION_ANSWER,
            "occupation_id": None,
            "sources": [],
        }

    try:
        context, sources = build_chat_context(
            db,
            request.occupation_id,
            request.message,
        )
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        answer = generate_chat_answer(request.message, context)
    except ChatModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ChatModelUnavailableError as exc:
        return {
            "status": "temporarily_unavailable",
            "answer": str(exc),
            "occupation_id": request.occupation_id,
            "sources": [],
        }

    return {
        "status": "answered",
        "answer": answer,
        "occupation_id": request.occupation_id,
        "sources": sources,
    }
