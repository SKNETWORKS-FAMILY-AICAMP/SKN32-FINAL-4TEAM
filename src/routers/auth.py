"""/auth/* — 이메일+비밀번호 가입·로그인·프로필·탈퇴 (서버 쿠키만 사용, localStorage 토큰 없음).

계약: docs/agent-tasks/baby/P6_authentication.md, docs/frontend_외부수정요청.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from src import schemas
from src.auth.deps import AUTH_COOKIE_NAME, Principal, current_user, optional_principal
from src.auth.ratelimit import allow as rate_limit_allow
from src.config import AUTH_COOKIE_SECURE
from src.db import get_conn
from src.errors import RateLimited
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, max_age: int | None) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME, token, httponly=True, samesite="lax", path="/",
        secure=AUTH_COOKIE_SECURE, max_age=max_age,
    )


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/request-code")
def request_code(body: schemas.RequestCodeIn) -> dict:
    auth_service.request_login_code(body.email)
    return {"ok": True}


@router.post("/verify", response_model=schemas.TokenOut, include_in_schema=False)
def verify(body: schemas.VerifyCodeIn) -> schemas.TokenOut:
    """코드 검증 → JWT + browser_token 병합."""
    raise NotImplementedError


@router.post("/signup", response_model=schemas.UserEnvelopeOut, status_code=201)
def signup(body: schemas.SignupIn, response: Response, principal: Principal = Depends(optional_principal)) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        result = auth_service.signup(
            conn, email=body.email, password=body.password, display_name=body.display_name,
            terms_agreed=body.terms_agreed, privacy_agreed=body.privacy_agreed,
            marketing_agreed=body.marketing_agreed, guest_token=principal.browser_token,
        )
    _set_session_cookie(response, result["token"], result["max_age"])
    return schemas.UserEnvelopeOut(user=result["user"])


@router.post("/login", response_model=schemas.UserEnvelopeOut)
def login(body: schemas.LoginIn, response: Response, principal: Principal = Depends(optional_principal)) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        result = auth_service.login(
            conn, email=body.email, password=body.password, remember=body.remember,
            guest_token=principal.browser_token,
        )
    _set_session_cookie(response, result["token"], result["max_age"])
    return schemas.UserEnvelopeOut(user=result["user"])


@router.get("/me", response_model=schemas.UserEnvelopeOut)
def me(user_id=Depends(current_user)) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        result = auth_service.get_current_user(conn, user_id)
    return schemas.UserEnvelopeOut(user=result["user"])


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    """이 브라우저의 인증 쿠키만 지운다. 서버 쪽 전 세션 무효화는 하지 않는다 —
    비밀번호 변경/탈퇴만 password_updated_at/status 갱신으로 다른 토큰을 무효화한다(P6 RULES #9).
    다른 기기에 남은 쿠키는 자연 만료(remember 여부에 따라 최대 JWT_TTL_DAYS 또는
    12시간) 전까지는 서명·계정 상태 검증을 통과하는 한 계속 유효하다 — 이 로그아웃이
    그것까지 막는다고 주장하지 않는다."""
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")


@router.patch("/me", response_model=schemas.UserEnvelopeOut)
def patch_me(body: schemas.PatchMeIn, user_id=Depends(current_user)) -> schemas.UserEnvelopeOut:
    with get_conn() as conn:
        result = auth_service.update_profile(
            conn, user_id, display_name=body.display_name, email=body.email,
            marketing_agreed=body.marketing_agreed,
        )
    return schemas.UserEnvelopeOut(user=result["user"])


@router.post("/password", status_code=204)
def change_password(body: schemas.PasswordChangeIn, response: Response, user_id=Depends(current_user)) -> None:
    with get_conn() as conn:
        result = auth_service.change_password(
            conn, user_id, current_password=body.current_password, new_password=body.new_password,
        )
    _set_session_cookie(response, result["token"], result["max_age"])


@router.post("/withdraw", status_code=204)
def withdraw(body: schemas.WithdrawIn, response: Response, user_id=Depends(current_user)) -> None:
    with get_conn() as conn:
        auth_service.withdraw(conn, user_id, password=body.password)
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")


@router.get("/email-availability", response_model=schemas.EmailAvailabilityOut)
def email_availability(request: Request, email: str = Query(...)) -> schemas.EmailAvailabilityOut:
    if not rate_limit_allow(f"email-availability:{_client_key(request)}", limit=20, window_seconds=60):
        raise RateLimited("요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    with get_conn() as conn:
        available = auth_service.check_email_availability(conn, email)
    return schemas.EmailAvailabilityOut(available=available)


# ── 보류: 비밀번호 재설정·이메일 인증(§G, 2026-10-26 예정)에 재사용할 이메일 코드 엔드포인트.
# docs/frontend_외부수정요청.md §A-4 각주: "삭제하지 말고 보류". 현재 비밀번호 로그인 흐름과는
# 별개이며 프런트는 호출하지 않는다. src/auth/codes.py 저장소가 없어 여전히 미구현이다.
@router.post("/request-code", include_in_schema=False)
def request_code(body: schemas.RequestCodeIn) -> dict:
    auth_service.request_login_code(body.email)
    return {"ok": True}


@router.post("/verify", response_model=schemas.TokenOut, include_in_schema=False)
def verify(body: schemas.VerifyCodeIn) -> schemas.TokenOut:
    raise NotImplementedError("이메일 코드 인증은 비밀번호 재설정용으로 보류 중입니다.")
