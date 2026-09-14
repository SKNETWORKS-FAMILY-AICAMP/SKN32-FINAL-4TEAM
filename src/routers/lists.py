"""/lists/* — sidebar lists, confirmation and reports (HEAD schema)."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Response, status
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.errors import ValidationFailed
from src.services import list_service
router=APIRouter(prefix="/lists",tags=["lists"])
def _parse_if_match(if_match:str|None)->int|None:
 """422(ValidationFailed), never an unhandled 500, on a malformed header (P7 review R3)."""
 if if_match is None: return None
 try: return int(if_match)
 except ValueError: raise ValidationFailed('If-Match 헤더 형식이 올바르지 않습니다.',field='if_match')
@router.post("/{list_id}/confirm",response_model=schemas.ReportOut)
def confirm(list_id:UUID,body:schemas.ConfirmIn,if_match:str|None=Header(default=None,alias="If-Match"),principal:Principal=Depends(optional_principal))->schemas.ReportOut:
 with get_conn() as conn: return schemas.ReportOut(**list_service.confirm(conn,list_id,principal,name=body.name,planned_purchase_at=body.planned_purchase_at,target_amount=body.target_amount,memo=body.memo,if_match=_parse_if_match(if_match)))
@router.post("/{list_id}/alert")
def set_alert(list_id:UUID,body:schemas.AlertIn,principal:Principal=Depends(optional_principal))->dict:
 """목표가 추적 생성/갱신 (develop `da79839`; P0 review R3)."""
 with get_conn() as conn: result=list_service.set_alert(conn,list_id,principal,enabled=body.enabled,target_amount=body.target_amount)
 return {"price_watch":schemas.PriceWatchOut(**result["price_watch"]).model_dump()}
@router.get("/{list_id}/report",response_model=schemas.ReportOut)
def report(list_id:UUID,principal:Principal=Depends(optional_principal))->schemas.ReportOut:
 with get_conn() as conn: return schemas.ReportOut(**list_service.get_report(conn,list_id,principal))
@router.get("")
def my_lists(principal:Principal=Depends(optional_principal))->dict:
 with get_conn() as conn: return {"items":list_service.list_conversations(conn,principal)}
@router.patch("/{list_id}",response_model=schemas.ListSummaryOut)
def rename(list_id:UUID,body:schemas.ListRenameIn,principal:Principal=Depends(optional_principal))->schemas.ListSummaryOut:
 with get_conn() as conn: return schemas.ListSummaryOut(**list_service.rename(conn,list_id,principal,name=body.name))
@router.delete("/{list_id}",status_code=status.HTTP_204_NO_CONTENT)
def delete(list_id:UUID,principal:Principal=Depends(optional_principal))->Response:
 with get_conn() as conn: list_service.delete(conn,list_id,principal)
 return Response(status_code=status.HTTP_204_NO_CONTENT)
