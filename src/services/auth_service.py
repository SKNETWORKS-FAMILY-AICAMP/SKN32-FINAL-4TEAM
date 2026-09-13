"""인증 서비스 — 이메일+비밀번호 가입/로그인/프로필/탈퇴 (docs/frontend_외부수정요청.md §A-3, §A-4).

`request-code`/`verify`(이메일 코드)는 이번 흐름에서 쓰지 않지만 삭제하지 않고 보류한다
(비밀번호 재설정·이메일 인증 재사용 예정, §G).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

from src.auth import codes, jwt, passwords
from src.auth.deps import Principal
from src.config import (
    JWT_TTL_DAYS,
    LOGIN_LOCK_MINUTES,
    LOGIN_MAX_FAILURES,
    SESSION_TTL_HOURS,
    TERMS_VERSION,
)
from src.errors import AccountLocked, Conflict, Unauthorized, ValidationFailed
from src.repo.user_repo import ConversationRepo, UserRepo

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 실제 검증과 비슷한 비용을 들이기 위한 가짜 해시 — 가입 여부를 응답 시간으로 드러내지 않는다.
_DUMMY_PASSWORD_HASH = passwords.hash_password("dummy-password-for-constant-time-check")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValidationFailed("이메일 형식이 올바르지 않습니다.", field="email")
    return normalized


def _check_password_strength(password: str) -> None:
    if not passwords.is_strong(password):
        raise ValidationFailed(
            "비밀번호는 영문·숫자를 포함해 8~128자여야 합니다.", field="password", code="weak_password"
        )


def _to_user_out(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "display_name": row["display_name"],
        "marketing_agreed": row["marketing_agreed"],
        "created_at": row["created_at"],
    }


def _merge_guest_data(conn, user_id: UUID, browser_token: str | None) -> None:
    if not browser_token:
        return
    ConversationRepo(conn).attach_user(_token_hash(browser_token), user_id)


def _require_active_session(user: dict, principal: Principal) -> None:
    """비밀번호 변경·탈퇴 이전에 발급된 토큰을 거부한다(§A-3 로그인 상태 확인)."""
    if user is None or user["status"] != "active":
        raise Unauthorized("로그인이 필요합니다.")
    if user["password_updated_at"] is not None:
        floor_epoch = int(user["password_updated_at"].timestamp())
        if principal.session_iat is None or principal.session_iat < floor_epoch:
            raise Unauthorized("세션이 만료되었습니다. 다시 로그인해주세요.")


def require_active_user(conn, principal: Principal) -> dict:
    """로그인이 필요한 다른 서비스(list_service 등)가 공용으로 쓰는 검사.

    JWT가 유효해도 계정이 그 사이 탈퇴·정지됐거나 비밀번호가 바뀌었으면 거부한다
    (session_iat만 보는 얕은 검사로는 못 잡는 부분 — §A-3).
    """
    if principal.user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    user = UserRepo(conn).get(principal.user_id)
    _require_active_session(user, principal)
    return user


def request_login_code(email: str) -> None:
    """보류 중인 코드 로그인 — request-code 라우터가 호출(§G 재사용 예정)."""
    codes.request_code(email)


def signup(conn, principal: Principal, *, email: str, password: str, display_name: str,
           terms_agreed: bool, privacy_agreed: bool, marketing_agreed: bool) -> tuple[dict, str]:
    normalized_email = _normalize_email(email)
    _check_password_strength(password)
    display_name = display_name.strip()
    if not (1 <= len(display_name) <= 20):
        raise ValidationFailed("표시 이름은 1~20자여야 합니다.", field="display_name")
    if not (terms_agreed and privacy_agreed):
        raise ValidationFailed(
            "이용약관과 개인정보 처리방침에 동의해야 합니다.", field="terms_agreed", code="terms_required"
        )

    repo = UserRepo(conn)
    if repo.is_email_taken(normalized_email):
        raise Conflict("이미 사용 중인 이메일입니다.", field="email", code="email_taken")

    now = datetime.now(timezone.utc)
    row = repo.create_local_user(
        email_normalized=normalized_email,
        password_hash=passwords.hash_password(password),
        display_name=display_name,
        terms_version=TERMS_VERSION,
        terms_agreed_at=now,
        privacy_agreed_at=now,
        marketing_agreed_at=now if marketing_agreed else None,
    )
    _merge_guest_data(conn, row["id"], principal.browser_token)
    token = jwt.issue(row["id"], row["email"], ttl_seconds=JWT_TTL_DAYS * 86_400)
    return _to_user_out(row), token


def login(conn, principal: Principal, *, email: str, password: str, remember: bool) -> tuple[dict, str]:
    normalized_email = _normalize_email(email)
    repo = UserRepo(conn)
    row = repo.get_for_login(normalized_email)
    if row is None or row["status"] != "active":
        passwords.verify_password(_DUMMY_PASSWORD_HASH, password)
        raise Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.", code="invalid_credentials")

    if row["locked_until"] is not None and row["locked_until"] > datetime.now(timezone.utc):
        raise AccountLocked("로그인 시도 초과로 잠시 잠겼습니다. 잠시 후 다시 시도해주세요.")

    if row["password_hash"] is None or not passwords.verify_password(row["password_hash"], password):
        repo.record_login_failure(row["id"], max_failures=LOGIN_MAX_FAILURES, lock_minutes=LOGIN_LOCK_MINUTES)
        raise Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.", code="invalid_credentials")

    if passwords.needs_rehash(row["password_hash"]):
        repo.update_password(row["id"], passwords.hash_password(password))
    repo.record_login_success(row["id"])
    _merge_guest_data(conn, row["id"], principal.browser_token)

    user = repo.get(row["id"])
    ttl_seconds = JWT_TTL_DAYS * 86_400 if remember else SESSION_TTL_HOURS * 3_600
    token = jwt.issue(user["id"], user["email"], ttl_seconds=ttl_seconds)
    return _to_user_out(user), token


def get_me(conn, principal: Principal) -> dict:
    return _to_user_out(require_active_user(conn, principal))


def update_profile(conn, principal: Principal, *, display_name: str | None, email: str | None,
                    marketing_agreed: bool | None) -> dict:
    user = require_active_user(conn, principal)
    repo = UserRepo(conn)

    if display_name is not None:
        display_name = display_name.strip()
        if not (1 <= len(display_name) <= 20):
            raise ValidationFailed("표시 이름은 1~20자여야 합니다.", field="display_name")

    normalized_email = None
    if email is not None:
        normalized_email = _normalize_email(email)
        if normalized_email != user["email"] and repo.is_email_taken(normalized_email):
            raise Conflict("이미 사용 중인 이메일입니다.", field="email", code="email_taken")

    row = repo.update_profile(
        principal.user_id,
        display_name=display_name,
        email_normalized=normalized_email,
        marketing_agreed=marketing_agreed,
    )
    return _to_user_out(row)


def change_password(conn, principal: Principal, *, current_password: str, new_password: str) -> str:
    user = require_active_user(conn, principal)
    repo = UserRepo(conn)

    login_row = repo.get_for_login(user["email"])
    if login_row is None or login_row["password_hash"] is None or not passwords.verify_password(
        login_row["password_hash"], current_password
    ):
        raise Unauthorized("현재 비밀번호가 올바르지 않습니다.", code="invalid_password")
    _check_password_strength(new_password)

    repo.update_password(principal.user_id, passwords.hash_password(new_password))
    return jwt.issue(principal.user_id, user["email"], ttl_seconds=JWT_TTL_DAYS * 86_400)


def withdraw(conn, principal: Principal, *, password: str) -> None:
    user = require_active_user(conn, principal)
    repo = UserRepo(conn)

    login_row = repo.get_for_login(user["email"])
    if login_row is None or login_row["password_hash"] is None or not passwords.verify_password(
        login_row["password_hash"], password
    ):
        raise Unauthorized("비밀번호가 올바르지 않습니다.", code="invalid_password")
    repo.withdraw(principal.user_id)


def check_email_availability(conn, email: str) -> bool:
    normalized_email = _normalize_email(email)
    return not UserRepo(conn).is_email_taken(normalized_email)
