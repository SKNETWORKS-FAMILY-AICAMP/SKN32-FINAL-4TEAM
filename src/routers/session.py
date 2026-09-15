"""/session HTTP handlers."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.errors import NotFound
from src.i18n import Locale, resolve_locale
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
def get_session(
    list_id: UUID,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.get_session_state(conn, list_id, principal, locale))

@router.post("/{list_id}/category", response_model=schemas.ConditionState)
def choose_category(
    list_id: UUID,
    body: schemas.CategoryIn,
    request: Request,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    # 프론트 언어 토글(localStorage) → X-TrueFit-Lang 헤더. 없으면 한국어(전과 동일).
    language = (request.headers.get("x-truefit-lang") or "").lower() or None
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.choose_category(
            conn, list_id, body.category, body.mode, principal, locale, language=language,
        ))

@router.patch("/{list_id}/slot", response_model=schemas.ConditionState)
def patch_slot(
    list_id: UUID,
    body: schemas.SlotPatchIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.patch_slot(
            conn, list_id, body.field, body.value, principal, locale,
        ))

@router.post("/{list_id}/message", response_model=schemas.ConditionState)
def message(
    list_id: UUID,
    body: schemas.MessageIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_message(conn, list_id, body.text, principal, locale))

@router.post("/{list_id}/answer", response_model=schemas.ConditionState)
def answer(
    list_id: UUID,
    body: schemas.AnswerIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_answer(
            conn, list_id, body.question_id, body.selected, principal, locale,
        ))

@router.post("/{list_id}/reset", response_model=schemas.ConditionState)
def reset(
    list_id: UUID,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.reset_conditions(conn, list_id, principal, locale))

@router.post("/{list_id}/recommend", response_model=schemas.RecommendAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
def recommend(
    list_id: UUID,
    body: schemas.RecommendIn = schemas.RecommendIn(),
    background_tasks: BackgroundTasks = None,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.RecommendAcceptedOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        accepted = recommendation_service.start_recommendation(
            conn,
            revision["id"],
            strategy=body.strategy or "default",
            locale=locale,
        )
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

@router.patch("/{list_id}/items/{item_id}", response_model=schemas.RecommendResultOut)
def patch_item(list_id: UUID, item_id: UUID, body: schemas.ItemPatchIn, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.patch_item(conn, revision["id"], item_id, selected=body.selected, qty=body.qty, timing=body.timing)
    return schemas.RecommendResultOut(**stored)

@router.get("/{list_id}/items/{item_id}/alternatives", response_model=schemas.AlternativesOut)
def alternatives(
    list_id: UUID,
    item_id: UUID,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.AlternativesOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.list_alternatives(conn, revision["id"], item_id, locale=locale)
    return schemas.AlternativesOut(**stored)

@router.post("/{list_id}/items/{item_id}/swap", response_model=schemas.RecommendResultOut)
def swap(list_id: UUID, item_id: UUID, body: schemas.SwapIn, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.swap_item(conn, revision["id"], item_id, UUID(body.candidate_id))
    return schemas.RecommendResultOut(**stored)

@router.post("/{list_id}/result-message", response_model=schemas.ResultMessageOut)
def result_message(
    list_id: UUID,
    body: schemas.ResultMessageIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ResultMessageOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.handle_result_message(
            conn,
            revision["id"],
            body.text,
            locale=locale,
        )
    return schemas.ResultMessageOut(**stored)

@router.post("/{list_id}/spec-file", response_model=schemas.ConditionState)
def spec_file(
    list_id: UUID,
    body: schemas.SpecFileIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.attach_spec_file(
            conn, list_id, body.file_name, body.content, principal, locale,
        ))
