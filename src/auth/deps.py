"""FastAPI 인증 의존성."""
from __future__ import annotations
from uuid import UUID
from fastapi import Cookie, Depends, Header
from src.auth import jwt
from src.config import COOKIE_NAME
from src.errors import Unauthorized

class Principal:
    def __init__(self, user_id: UUID | None, browser_token: str | None, session_iat: int | None = None):
        self.user_id = user_id
        self.browser_token = browser_token
        self.session_iat = session_iat  # 로그인 토큰 발급 시각(초) — 비밀번호 변경 이전 토큰 무효화용

def optional_principal(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    browser_token_header: str | None = Header(default=None, alias="X-Browser-Token"),
    browser_token_cookie: str | None = Cookie(default=None, alias="truefit_guest"),
) -> Principal:
    token = None
    if authorization is not None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise Unauthorized("Authorization 헤더 형식이 올바르지 않습니다.")
        token = value
    elif session_cookie:
        token = session_cookie

    user_id = None
    session_iat = None
    if token is not None:
        claims = jwt.verify(token)
        user_id = UUID(claims["sub"])
        session_iat = claims["iat"]

    browser_token = browser_token_header or browser_token_cookie
    if browser_token is not None and not browser_token.strip():
        raise Unauthorized("browser token이 비어 있습니다.")
    return Principal(user_id, browser_token, session_iat)

def current_user(principal: Principal = Depends(optional_principal)) -> UUID:
    if principal.user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    return principal.user_id
