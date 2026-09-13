"""FastAPI 인증 의존성."""
from __future__ import annotations
from uuid import UUID
from fastapi import Cookie, Depends, Header
from src.auth import jwt
from src.errors import Unauthorized

class Principal:
    def __init__(self, user_id: UUID | None, browser_token: str | None):
        self.user_id = user_id
        self.browser_token = browser_token

def optional_principal(authorization: str | None = Header(default=None), browser_token_header: str | None = Header(default=None, alias="X-Browser-Token"), browser_token_cookie: str | None = Cookie(default=None, alias="truefit_guest")) -> Principal:
    user_id = None
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("Authorization 헤더 형식이 올바르지 않습니다.")
        user_id = UUID(jwt.verify(token)["sub"])
    browser_token = browser_token_header or browser_token_cookie
    if browser_token is not None and not browser_token.strip():
        raise Unauthorized("browser token이 비어 있습니다.")
    return Principal(user_id, browser_token)

def current_user(principal: Principal = Depends(optional_principal)) -> UUID:
    if principal.user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    return principal.user_id
