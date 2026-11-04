"""Self-evolution suggestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import LLMDep, SessionDep
from app.api.schemas import DecisionRequest
from app.api.serializers import suggestion_payload
from app.core.errors import NotFoundError
from app.models.evolution import EvolutionSuggestion
from app.self_evolution.analyzer import EvolutionAnalyzer
from app.self_evolution.applier import EvolutionApplier

router = APIRouter(prefix="/evolution", tags=["evolution"])


@router.get("/suggestions")
def list_suggestions(
    session: Session = SessionDep, status: str | None = Query(default=None)
) -> dict:
    query = select(EvolutionSuggestion)
    if status:
        query = query.where(EvolutionSuggestion.status == status)
    rows = list(
        session.scalars(query.order_by(EvolutionSuggestion.created_at.desc()))
    )
    return {"items": [suggestion_payload(item) for item in rows]}


@router.post("/suggestions/generate")
def generate_suggestions(session: Session = SessionDep, llm=LLMDep) -> dict:
    result = EvolutionAnalyzer(session, llm).analyze()
    return {"items": [suggestion_payload(item) for item in result.suggestions]}


@router.get("/suggestions/{suggestion_id}")
def get_suggestion(suggestion_id: str, session: Session = SessionDep) -> dict:
    suggestion = session.get(EvolutionSuggestion, suggestion_id)
    if suggestion is None:
        raise NotFoundError("改进建议不存在")
    return suggestion_payload(suggestion)


@router.post("/suggestions/{suggestion_id}/approve")
def approve_suggestion(
    suggestion_id: str, payload: DecisionRequest, session: Session = SessionDep
) -> dict:
    suggestion = EvolutionApplier(session).decide(
        suggestion_id, approve=True, note=payload.note
    )
    return suggestion_payload(suggestion)


@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: str, payload: DecisionRequest, session: Session = SessionDep
) -> dict:
    suggestion = EvolutionApplier(session).reject(suggestion_id, note=payload.note)
    return suggestion_payload(suggestion)


@router.post("/suggestions/{suggestion_id}/apply")
def apply_suggestion(suggestion_id: str, session: Session = SessionDep) -> dict:
    return suggestion_payload(EvolutionApplier(session).apply(suggestion_id))


@router.post("/suggestions/{suggestion_id}/rollback")
def rollback_suggestion(suggestion_id: str, session: Session = SessionDep) -> dict:
    return suggestion_payload(EvolutionApplier(session).rollback(suggestion_id))


@router.post("/suggestions/{suggestion_id}/refresh-effect")
def refresh_effect(suggestion_id: str, session: Session = SessionDep) -> dict:
    return EvolutionApplier(session).refresh_effect(suggestion_id)
