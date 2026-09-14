"""/lists/* — 사이드바 목록 · S5-a 확정 · S5-b 리포트 · 목표가 알림 (§D-4-3)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.i18n import Locale, resolve_locale
from src.services import list_service

router = APIRouter(prefix="/lists", tags=["lists"])


@router.get("", response_model=schemas.ListsOut)
def my_lists(principal: Principal = Depends(optional_principal)) -> schemas.ListsOut:
    """사이드바 "내 장바구니" — 로그인 사용자 또는 guest 쿠키 소유분, 최근 수정순."""
    with get_conn() as conn:
        items = list_service.list_conversations(conn, principal)
    return schemas.ListsOut(items=[schemas.ListSummaryOut(**item) for item in items])


@router.patch("/{list_id}", response_model=schemas.ListSummaryOut)
def rename(
    list_id: UUID, body: schemas.ListRenameIn, principal: Principal = Depends(optional_principal)
) -> schemas.ListSummaryOut:
    with get_conn() as conn:
        summary = list_service.rename(conn, list_id, principal, name=body.name)
    return schemas.ListSummaryOut(**summary)


@router.delete("/{list_id}", status_code=204)
def delete(list_id: UUID, principal: Principal = Depends(optional_principal)) -> None:
    with get_conn() as conn:
        list_service.delete(conn, list_id, principal)


@router.post("/{list_id}/confirm", response_model=schemas.ReportOut)
def confirm(
    list_id: UUID,
    body: schemas.ConfirmIn,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ReportOut:
    """draft → confirmed. 비로그인이면 401 (프론트가 로그인 모달)."""
    with get_conn() as conn:
        report = list_service.confirm(
            conn, list_id, principal,
            name=body.name, planned_purchase_at=body.planned_purchase_at,
            target_amount=body.target_amount, memo=body.memo, locale=locale,
        )
    return schemas.ReportOut(**report)


@router.get("/{list_id}/report", response_model=schemas.ReportOut)
def report(
    list_id: UUID,
    principal: Principal = Depends(optional_principal),
    locale: Locale = Depends(resolve_locale),
) -> schemas.ReportOut:
    with get_conn() as conn:
        report = list_service.get_report(conn, list_id, principal, locale=locale)
    return schemas.ReportOut(**report)


@router.post("/{list_id}/alert")
def set_alert(
    list_id: UUID, body: schemas.AlertIn, principal: Principal = Depends(optional_principal)
) -> dict:
    """목표가 추적 생성/갱신."""
    with get_conn() as conn:
        result = list_service.set_alert(
            conn, list_id, principal, enabled=body.enabled, target_amount=body.target_amount
        )
    return {"price_watch": schemas.PriceWatchOut(**result["price_watch"]).model_dump()}
