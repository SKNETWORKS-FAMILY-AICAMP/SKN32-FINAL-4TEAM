"""비밀번호 해시/검증 (argon2id, argon2-cffi). 평문은 어디에도 저장하지 않는다."""
from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_hasher = PasswordHasher()

# 8~128자, 영문·숫자 각 1자 이상 (docs/frontend_외부수정요청.md §A-3).
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def is_strong(password: str) -> bool:
    return bool(_PASSWORD_RE.match(password))
