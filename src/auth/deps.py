"""FastAPI 인증 의존성.

- current_user       : JWT 필수 (없으면 401). /lists/*, /reviews/* 에 사용
- optional_user      : JWT 있으면 사용자, 없으면 None. /session/* 에 사용
- browser_token      : 비로그인 대화 소유 토큰 (쿠키/헤더). optional_user 와 함께 소유권 판정
"""
from __future__ import annotations

from uuid import UUID


class Principal:
    """요청 주체. user_id 또는 browser_token 중 하나 이상."""

    def __init__(self, user_id: UUID | None, browser_token: str | None):
        self.user_id = user_id
        self.browser_token = browser_token


def current_user() -> UUID:
    """JWT 필수. FastAPI Depends 로 사용."""
    raise NotImplementedError


def optional_principal() -> Principal:
    """JWT 있으면 user_id, 없으면 browser_token 만."""
    raise NotImplementedError
