"""JWT 발급·검증.

클레임: sub(user_id), email, iat, exp. 데모 access 2주 단일 / 최종 access 1h + refresh 30d.
저장 방식(httpOnly 쿠키 vs Authorization 헤더)은 프론트와 확정 (기획서 §18-1 미결).
"""
from __future__ import annotations

from uuid import UUID


def issue(user_id: UUID, email: str) -> str:
    """서명된 JWT 문자열."""
    raise NotImplementedError


def verify(token: str) -> dict:
    """검증 후 클레임 dict. 실패 시 errors.Unauthorized."""
    raise NotImplementedError
