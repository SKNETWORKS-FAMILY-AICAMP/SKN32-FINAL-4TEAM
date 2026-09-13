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


def issue(user_id: UUID, email: str, *, ttl_seconds: int | None = None) -> str:
    """서명된 HS256 JWT 문자열.

    P0 v3 develop 정렬: 별도 `auth_version` 세대 카운터 컬럼 없이 `iat`(발급 시각)만 쓴다.
    비밀번호 변경/탈퇴는 `identity.app_user.password_updated_at`/`status`를 갱신하고,
    `src.auth.deps`가 `claims["iat"] < password_updated_at.timestamp()` 또는
    `status != 'active'`이면 거부한다(develop 원안의 iat 기반 무효화,
    DEVELOP_DB_TRANSITION.md). `iat`은 정수 초가 아니라 부동소수 유닉스 시각으로
    저장한다 — 정수 초로 반올림하면 "비밀번호 변경 직후 같은 초 안에 발급된 이전
    토큰"을 구분하지 못해 즉시 무효화가 실패한다(실측: AU04 재현).
    """
    now = time.time()
    ttl = ttl_seconds if ttl_seconds is not None else JWT_TTL_DAYS * 86_400
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps(
        {"sub": str(user_id), "email": email, "iat": now, "exp": now + ttl},
        separators=(",", ":"),
    ).encode())
    signature = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify(token: str) -> dict:
    """서명·만료·클레임 형태 검증 후 클레임 dict. 실패 시 Unauthorized.

    계정 상태(active)·발급 시각 대 비밀번호 변경 시각 대조는 DB 조회가 필요해 이 함수 밖
    (`src.auth.deps`)에서 이어서 한다 — 이 함수는 순수 서명 검증만 담당한다.
    """
    try:
        header, payload, signature = token.split(".")
        expected = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        decoded_header = json.loads(_b64decode(header))
        claims = json.loads(_b64decode(payload))
        if decoded_header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims.get("exp"), (int, float)):
            raise ValueError("claims")
        if not isinstance(claims.get("iat"), (int, float)):
            raise ValueError("claims")
        UUID(claims["sub"])
        if claims["exp"] <= time.time():
            raise ValueError("expired")
        return claims
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.") from None
