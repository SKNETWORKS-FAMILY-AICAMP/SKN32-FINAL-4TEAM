"""FastAPI 인증 의존성."""
from __future__ import annotations
from uuid import UUID
from fastapi import Cookie, Depends, Header
from src.auth import jwt
from src.db import get_conn
from src.errors import Unauthorized

AUTH_COOKIE_NAME = "truefit_session"


class Principal:
    def __init__(self, user_id: UUID | None, browser_token: str | None):
        self.user_id = user_id
        self.browser_token = browser_token


def _authenticate(token: str) -> UUID:
    """서명·만료를 검증한 뒤 DB 로 계정 활성 상태와 auth_version 세대를 대조한다.

    서명/만료만 보던 이전 검증은 같은 초 안에 비밀번호를 바꿔도 이전 토큰이 그대로
    유효한 허점이 있었다(P6 RULES #4). 여기서 매 인증 요청마다 최신 상태를 조회해
    suspended/deleted 계정과 세대가 지난 토큰을 즉시 거부한다."""
    claims = jwt.verify(token)
    user_id = UUID(claims["sub"])
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, auth_version FROM identity.app_user WHERE id=%s", (user_id,)
        ).fetchone()
    if row is None:
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.")
    status, auth_version = row
    if status != "active" or auth_version != claims["auth_version"]:
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.")
    return user_id


def optional_principal(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    browser_token_header: str | None = Header(default=None, alias="X-Browser-Token"),
    browser_token_cookie: str | None = Cookie(default=None, alias="truefit_guest"),
) -> Principal:
    user_id = None
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("Authorization 헤더 형식이 올바르지 않습니다.")
        user_id = _authenticate(token)
    elif session_cookie is not None:
        user_id = _authenticate(session_cookie)
    browser_token = browser_token_header or browser_token_cookie
    if browser_token is not None and not browser_token.strip():
        raise Unauthorized("browser token이 비어 있습니다.")
    return Principal(user_id, browser_token)


def current_user(principal: Principal = Depends(optional_principal)) -> UUID:
    if principal.user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    return principal.user_id
