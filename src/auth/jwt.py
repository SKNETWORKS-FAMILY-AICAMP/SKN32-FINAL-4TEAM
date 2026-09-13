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


def issue(user_id: UUID, email: str) -> str:
    """서명된 HS256 JWT 문자열."""
    now = int(time.time())
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps({"sub": str(user_id), "email": email, "iat": now, "exp": now + JWT_TTL_DAYS * 86_400}, separators=(",", ":")).encode())
    signature = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify(token: str) -> dict:
    """검증 후 클레임 dict. 실패 시 Unauthorized."""
    try:
        header, payload, signature = token.split(".")
        expected = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        decoded_header = json.loads(_b64decode(header))
        claims = json.loads(_b64decode(payload))
        if decoded_header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims.get("exp"), int):
            raise ValueError("claims")
        UUID(claims["sub"])
        if claims["exp"] <= int(time.time()):
            raise ValueError("expired")
        return claims
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.") from None
