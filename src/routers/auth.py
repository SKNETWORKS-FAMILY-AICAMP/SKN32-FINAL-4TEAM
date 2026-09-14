"""/auth/* — 이메일+비밀번호 로그인 (docs/frontend_외부수정요청.md §A-4).

`request-code`/`verify`(이메일 코드)는 이번 흐름에서 쓰지 않는다. 삭제하지 않고 보류한다
(비밀번호 재설정·이메일 인증 재사용 예정, §G).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from src import schemas
from src.auth.deps import Principal, optional_principal
from src.config import COOKIE_NAME, COOKIE_SECURE, JWT_TTL_DAYS
from src.db import get_conn
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, *, remember: bool) -> None:
    max_age = JWT_TTL_DAYS * 86_400 if remember else None
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/", max_age=max_age,
    )


@router.post("/request-code")
def request_code(body: schemas.RequestCodeIn) -> dict:
    """코드 발송. 이메일 존재 여부와 무관하게 항상 200."""
    auth_service.request_login_code(body.email)
    return {"ok": True}


@router.post("/verify", response_model=schemas.TokenOut)
def verify(body: schemas.VerifyCodeIn) -> schemas.TokenOut:
    """코드 검증 → JWT + browser_token 병합."""
    raise NotImplementedError


@router.post("/signup", response_model=schemas.UserEnvelopeOut, status_code=201)
def signup(
    body: schemas.SignupIn, response: Response, principal: Principal = Depends(optional_principal)
) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        user, token = auth_service.signup(
            conn, principal,
            email=body.email, password=body.password, display_name=body.display_name,
            terms_agreed=body.terms_agreed, privacy_agreed=body.privacy_agreed,
            marketing_agreed=body.marketing_agreed,
        )
    _set_session_cookie(response, token, remember=True)
    return schemas.UserEnvelopeOut(user=schemas.UserOut(**user))


@router.post("/login", response_model=schemas.UserEnvelopeOut)
def login(
    body: schemas.LoginIn, response: Response, principal: Principal = Depends(optional_principal)
) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        user, token = auth_service.login(
            conn, principal, email=body.email, password=body.password, remember=body.remember
        )
    _set_session_cookie(response, token, remember=body.remember)
    return schemas.UserEnvelopeOut(user=schemas.UserOut(**user))


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=schemas.UserEnvelopeOut)
def me(principal: Principal = Depends(optional_principal)) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        user = auth_service.get_me(conn, principal)
    return schemas.UserEnvelopeOut(user=schemas.UserOut(**user))


@router.patch("/me", response_model=schemas.UserEnvelopeOut)
def update_profile(
    body: schemas.ProfilePatchIn, principal: Principal = Depends(optional_principal)
) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        user = auth_service.update_profile(
            conn, principal,
            display_name=body.display_name, email=body.email, marketing_agreed=body.marketing_agreed,
        )
    return schemas.UserEnvelopeOut(user=schemas.UserOut(**user))


@router.post("/password", status_code=204)
def change_password(
    body: schemas.PasswordChangeIn, response: Response, principal: Principal = Depends(optional_principal)
) -> None:
    with get_conn() as conn:
        token = auth_service.change_password(
            conn, principal, current_password=body.current_password, new_password=body.new_password
        )
    _set_session_cookie(response, token, remember=True)


@router.post("/withdraw", status_code=204)
def withdraw(
    body: schemas.WithdrawIn, response: Response, principal: Principal = Depends(optional_principal)
) -> None:
    with get_conn() as conn:
        auth_service.withdraw(conn, principal, password=body.password)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/email-availability", response_model=schemas.EmailAvailabilityOut)
def email_availability(email: str) -> schemas.EmailAvailabilityOut:
    # TODO(§A-4): IP당 rate limit(분당 30회) — 데모 범위에서는 보류.
    with get_conn() as conn:
        available = auth_service.check_email_availability(conn, email)
    return schemas.EmailAvailabilityOut(available=available)
