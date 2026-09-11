"""/session/* — S1~S3 대화·조건 수집 + [추천 실행]. 인증 불요(browser_token or JWT)."""
from __future__ import annotations

from fastapi import APIRouter

from src import schemas
from src.services import recommendation_service, session_service

router = APIRouter(prefix="/session", tags=["session"])


@router.post("", response_model=schemas.SessionOut)
def create() -> schemas.SessionOut:
    raise NotImplementedError


@router.post("/{list_id}/category")
def choose_category(list_id: str, body: schemas.CategoryIn) -> dict:
    """카테고리 미선택 상태에서 /message 호출 시 400."""
    raise NotImplementedError


@router.post("/{list_id}/message", response_model=schemas.ConditionStateOut)
def message(list_id: str, body: schemas.MessageIn) -> schemas.ConditionStateOut:
    raise NotImplementedError


@router.post("/{list_id}/answer", response_model=schemas.ConditionStateOut)
def answer(list_id: str, body: schemas.AnswerIn) -> schemas.ConditionStateOut:
    raise NotImplementedError


@router.patch("/{list_id}/slot", response_model=schemas.ConditionStateOut)
def patch_slot(list_id: str, body: schemas.SlotPatchIn) -> schemas.ConditionStateOut:
    raise NotImplementedError


@router.post("/{list_id}/recommend", response_model=schemas.RecommendResultOut)
def recommend(list_id: str) -> schemas.RecommendResultOut:
    """엔진 파이프라인 트리거. required_inputs 미충족이면 422."""
    raise NotImplementedError


@router.get("/{list_id}/result", response_model=schemas.RecommendResultOut)
def result(list_id: str) -> schemas.RecommendResultOut:
    """S4 폴링. (SSE 스트리밍 vs 폴링은 프론트와 확정 — 기획서 §18-1)"""
    raise NotImplementedError
