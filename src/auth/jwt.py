"""JWT 발급·검증."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from src.config import JWT_SECRET, JWT_TTL_DAYS
from src.errors import Unauthorized


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(user_id: UUID, email: str, *, auth_version: int = 0, ttl_seconds: int | None = None) -> str:
    """서명된 HS256 JWT 문자열.

    `auth_version` 은 identity.app_user.auth_version 의 발급 시점 스냅샷이다 — 비밀번호
    변경/탈퇴가 이 값을 올리면, 그 이전에 발급된 토큰은 서명·만료가 유효해도
    `verify()`+DB 대조 단계에서 세대 불일치로 거부된다(같은 초 재발급 경쟁 방지, P6 RULES #4).
    """
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else JWT_TTL_DAYS * 86_400
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps(
        {"sub": str(user_id), "email": email, "auth_version": auth_version, "iat": now, "exp": now + ttl},
        separators=(",", ":"),
    ).encode())
    signature = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify(token: str) -> dict:
    """서명·만료·클레임 형태 검증 후 클레임 dict. 실패 시 Unauthorized.

    계정 상태(active)·auth_version 세대 대조는 DB 조회가 필요해 이 함수 밖
    (`src.auth.deps`)에서 이어서 한다 — 이 함수는 순수 서명 검증만 담당한다.
    """
    try:
        header, payload, signature = token.split(".")
        expected = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        decoded_header = json.loads(_b64decode(header))
        claims = json.loads(_b64decode(payload))
        if decoded_header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims.get("exp"), int):
            raise ValueError("claims")
        if not isinstance(claims.get("auth_version"), int):
            raise ValueError("claims")
        UUID(claims["sub"])
        if claims["exp"] <= int(time.time()):
            raise ValueError("expired")
        return claims
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.") from None
