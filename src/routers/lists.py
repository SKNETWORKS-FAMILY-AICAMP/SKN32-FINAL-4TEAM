"""/lists/* — S5-a 확정 · S5-b 리포트 · 목표가 알림. JWT 필수."""
from __future__ import annotations

from fastapi import APIRouter

from src import schemas

router = APIRouter(prefix="/lists", tags=["lists"])


@router.post("/{list_id}/confirm", response_model=schemas.ReportOut)
def confirm(list_id: str, body: schemas.ConfirmIn) -> schemas.ReportOut:
    """draft → confirmed. 비로그인이면 401 (프론트가 로그인 모달)."""
    raise NotImplementedError


@router.get("/{list_id}/report", response_model=schemas.ReportOut)
def report(list_id: str) -> schemas.ReportOut:
    raise NotImplementedError


@router.post("/{list_id}/alert")
def set_alert(list_id: str, body: schemas.ConfirmIn) -> dict:
    """목표가 추적 생성/갱신."""
    raise NotImplementedError


@router.get("")
def my_lists() -> list[dict]:
    """사이드바 대화 기록."""
    raise NotImplementedError
