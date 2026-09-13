"""/lists/* — sidebar lists, confirmation and reports (HEAD schema)."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Response, status
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.services import list_service
router=APIRouter(prefix="/lists",tags=["lists"])
@router.post("/{list_id}/confirm",response_model=schemas.ReportOut)
def confirm(list_id:UUID,body:schemas.ConfirmIn,principal:Principal=Depends(optional_principal))->schemas.ReportOut:
 with get_conn() as conn: return schemas.ReportOut(**list_service.confirm(conn,list_id,principal,name=body.name,planned_purchase_at=body.planned_purchase_at,target_amount=body.target_amount,memo=body.memo))
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
