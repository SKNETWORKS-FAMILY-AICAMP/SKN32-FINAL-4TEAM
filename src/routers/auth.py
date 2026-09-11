"""/auth/* — 이메일 6자리 코드 → JWT."""
from __future__ import annotations

from fastapi import APIRouter

from src import schemas
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-code")
def request_code(body: schemas.RequestCodeIn) -> dict:
    """코드 발송. 이메일 존재 여부와 무관하게 항상 200."""
    auth_service.request_login_code(body.email)
    return {"ok": True}


@router.post("/verify", response_model=schemas.TokenOut)
def verify(body: schemas.VerifyCodeIn) -> schemas.TokenOut:
    """코드 검증 → JWT + browser_token 병합."""
    raise NotImplementedError


@router.post("/logout")
def logout() -> dict:
    raise NotImplementedError


@router.get("/me")
def me() -> dict:
    raise NotImplementedError
