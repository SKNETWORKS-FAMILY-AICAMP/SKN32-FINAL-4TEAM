"""/session HTTP handlers."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.errors import NotFound
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service, session_service

router = APIRouter(prefix="/session", tags=["session"])

@router.post("", response_model=schemas.SessionOut)
def create(response: Response, principal: Principal = Depends(optional_principal)) -> schemas.SessionOut:
    with get_conn() as conn:
        result = session_service.create_session(conn, principal)
    response.set_cookie(
        "truefit_guest", result["browser_token"],
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180,
    )
    return schemas.SessionOut(list_id=result["list_id"])

@router.get("/{list_id}", response_model=schemas.ConditionState)
def get_session(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.get_session_state(conn, list_id, principal))

@router.post("/{list_id}/category", response_model=schemas.ConditionState)
def choose_category(list_id: UUID, body: schemas.CategoryIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.choose_category(conn, list_id, body.category, body.mode, principal))

@router.patch("/{list_id}/slot", response_model=schemas.ConditionState)
def patch_slot(list_id: UUID, body: schemas.SlotPatchIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.patch_slot(conn, list_id, body.field, body.value, principal))

@router.post("/{list_id}/message", response_model=schemas.ConditionState)
def message(list_id: UUID, body: schemas.MessageIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_message(conn, list_id, body.text, principal))

@router.post("/{list_id}/answer", response_model=schemas.ConditionState)
def answer(list_id: UUID, body: schemas.AnswerIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_answer(conn, list_id, body.question_id, body.selected, principal))

@router.post("/{list_id}/reset", response_model=schemas.ConditionState)
def reset(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.reset_conditions(conn, list_id, principal))

@router.post("/{list_id}/recommend", response_model=schemas.RecommendAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
def recommend(list_id: UUID, body: schemas.RecommendIn = schemas.RecommendIn(), background_tasks: BackgroundTasks = None, principal: Principal = Depends(optional_principal)) -> schemas.RecommendAcceptedOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        accepted = recommendation_service.start_recommendation(conn, revision["id"], strategy=body.strategy or "default")
    background_tasks.add_task(recommendation_service.execute_recommendation, revision["id"], UUID(accepted["run_id"]))
    return schemas.RecommendAcceptedOut(**accepted)

@router.get("/{list_id}/result", response_model=schemas.RecommendResultOut)
def result(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.get_stored_result(conn, revision["id"])
    if stored is None:
        raise NotFound("추천 실행 결과가 없습니다. 먼저 /recommend 를 호출하세요.")
    return schemas.RecommendResultOut(**stored)
