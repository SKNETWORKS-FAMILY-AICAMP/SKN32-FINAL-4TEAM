"""비밀번호 해싱 — Argon2id (argon2-cffi, 명시적으로 고정된 의존성).

인코딩된 해시 문자열 자체에 알고리즘/버전/salt/파라미터가 모두 들어있다
(`$argon2id$v=19$m=...,t=...,p=...$salt$hash`) — 별도 컬럼으로 보관하지 않는다.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

_hasher = PasswordHasher()

# 계정이 존재하지 않을 때도 "더미 검증"에 걸리는 실측 시간이 실제 검증과 비슷하도록,
# 한 번 해시해 둔 값을 재사용한다(AU03: 미존재 이메일 오류가 오답 비밀번호 오류와 같아야 함).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-only-not-a-real-secret")


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(encoded_hash: str, raw: str) -> bool:
    try:
        return _hasher.verify(encoded_hash, raw)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    return _hasher.check_needs_rehash(encoded_hash)


def dummy_verify(raw: str) -> None:
    """존재하지 않는 계정에 대해서도 실제 Argon2 검증과 동일한 연산을 수행한다
    (계정 존재 여부가 응답 시간으로 새지 않도록; 결과는 버린다)."""
    try:
        _hasher.verify(_DUMMY_HASH, raw)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        pass
