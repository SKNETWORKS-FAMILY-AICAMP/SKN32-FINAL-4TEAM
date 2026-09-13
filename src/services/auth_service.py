"""인증 서비스 — 이메일+비밀번호 가입·로그인·세션·프로필·탈퇴·게스트 병합.

`docs/agent-tasks/baby/CONTRACTS.md`, `docs/agent-tasks/baby/P6_authentication.md` 계약:
데모 계정 없음, 서버 쿠키만 사용(localStorage 토큰 없음), P1 게스트 흐름 보존.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg

from src.auth import codes, jwt
from src.auth.passwords import dummy_verify, hash_password, needs_rehash, verify_password
from src.config import JWT_SESSION_TTL_HOURS, JWT_TTL_DAYS
from src.db import get_conn
from src.errors import AccountLocked, Conflict, Unauthorized, ValidationFailed
from src.repo.user_repo import ConversationRepo, UserRepo

TERMS_VERSION = "v1"
_LOCK_THRESHOLD = 5
_LOCK_MINUTES = 15
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized or not _EMAIL_RE.match(normalized) or len(normalized) > 254:
        raise ValidationFailed("올바른 이메일 형식이 아닙니다.", field="email")
    return normalized


def _validate_password(password: str) -> None:
    if (
        not isinstance(password, str)
        or not (8 <= len(password) <= 128)
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
    ):
        raise ValidationFailed(
            "비밀번호는 영문과 숫자를 포함해 8자 이상 128자 이하여야 합니다.",
            field="password", code="weak_password",
        )


def _validate_display_name(name: str) -> str:
    trimmed = (name or "").strip()
    if not (1 <= len(trimmed) <= 20):
        raise ValidationFailed("표시 이름은 1자 이상 20자 이하여야 합니다.", field="display_name")
    return trimmed


def _require_terms(terms_agreed: bool, privacy_agreed: bool) -> None:
    if not terms_agreed or not privacy_agreed:
        raise ValidationFailed(
            "필수 약관에 동의해야 합니다.", field="terms_agreed", code="terms_required",
        )


def serialize_user(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email_normalized"],
        "display_name": row["display_name"],
        "marketing_agreed": row["marketing_agreed_at"] is not None,
        "created_at": row["created_at"].isoformat(),
    }


def _issue_cookie_token(user_id: UUID, email: str, auth_version: int, *, remember: bool) -> tuple[str, int | None]:
    """(token, cookie_max_age_seconds). max_age=None → 브라우저 세션 쿠키(remember=false)."""
    if remember:
        ttl = JWT_TTL_DAYS * 86_400
        token = jwt.issue(user_id, email, auth_version=auth_version, ttl_seconds=ttl)
        return token, ttl
    ttl = JWT_SESSION_TTL_HOURS * 3600
    token = jwt.issue(user_id, email, auth_version=auth_version, ttl_seconds=ttl)
    return token, None


def _merge_guest(conn, user_id: UUID, guest_token: str | None) -> None:
    """유효한(=실존하는) truefit_guest 만 병합한다. 위조/미지 토큰은 조용히 무시한다
    (CONTRACTS: "현재 검증된 truefit_guest 만 허용")."""
    if not guest_token or not guest_token.strip():
        return
    guest_hash = _token_hash(guest_token)
    if not ConversationRepo(conn).guest_identity_known(guest_hash):
        return
    ConversationRepo(conn).merge_guest_into_user(guest_hash, user_id)


def request_login_code(email: str) -> None:
    """보류 중인 이메일 코드 발급(§G 비밀번호 재설정·이메일 인증 재사용 예정).

    현재 비밀번호 로그인 흐름의 일부가 아니다 — `src/auth/codes.py` 저장소가 여전히
    미구현이므로 호출 시 NotImplementedError 로 이어진다(고정 성공 응답으로 숨기지 않는다)."""
    codes.request_code(email)


def signup(conn, *, email: str, password: str, display_name: str, terms_agreed: bool,
           privacy_agreed: bool, marketing_agreed: bool, guest_token: str | None,
           remember: bool = True) -> dict:
    normalized_email = _validate_email(email)
    _validate_password(password)
    name = _validate_display_name(display_name)
    _require_terms(terms_agreed, privacy_agreed)

    user_id = uuid.uuid4()
    password_hash = hash_password(password)
    try:
        with conn.transaction():
            row = UserRepo(conn).create(
                user_id=user_id, email_normalized=normalized_email, display_name=name,
                password_hash=password_hash, terms_version=TERMS_VERSION,
                marketing_agreed=marketing_agreed,
            )
            _merge_guest(conn, user_id, guest_token)
    except psycopg.errors.UniqueViolation:
        raise Conflict("이미 가입된 이메일입니다.", field="email", code="email_taken") from None

    token, max_age = _issue_cookie_token(row["id"], row["email_normalized"], row["auth_version"], remember=remember)
    return {"user": serialize_user(row), "token": token, "max_age": max_age}


def login(conn, *, email: str, password: str, remember: bool, guest_token: str | None) -> dict:
    normalized_email = normalize_email(email)
    repo = UserRepo(conn)
    row = repo.get_by_email(normalized_email)

    if row is None:
        dummy_verify(password)
        raise Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.", code="invalid_credentials")

    if row["locked_until"] is not None and row["locked_until"] > datetime.now(timezone.utc):
        raise AccountLocked("로그인 시도가 여러 번 실패해 잠시 잠겼습니다. 15분 후 다시 시도해 주세요.")

    if row["status"] != "active" or row["password_hash"] is None or not verify_password(row["password_hash"], password):
        if row["status"] == "active" and row["password_hash"] is not None:
            # 실패 기록은 이 요청이 결국 401 로 끝나 바깥 get_conn() 트랜잭션이
            # 롤백되더라도 반드시 남아야 한다(AU03 잠금 카운트). 같은 커넥션이면
            # 예외로 트랜잭션 전체가 롤백될 때 이 UPDATE 도 함께 사라지므로,
            # 별도 커넥션에서 즉시 커밋되는 짧은 트랜잭션으로 분리한다.
            with get_conn() as bookkeeping_conn:
                bk_repo = UserRepo(bookkeeping_conn)
                new_count = bk_repo.increment_failed_login(row["id"])
                if new_count >= _LOCK_THRESHOLD:
                    bk_repo.lock_and_reset_count(row["id"], locked_until=datetime.now(timezone.utc) + timedelta(minutes=_LOCK_MINUTES))
        else:
            dummy_verify(password)
        raise Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.", code="invalid_credentials")

    rehashed = hash_password(password) if needs_rehash(row["password_hash"]) else None
    repo.record_login_success(row["id"], rehashed_password=rehashed)
    _merge_guest(conn, row["id"], guest_token)

    fresh = repo.get_by_id(row["id"])
    token, max_age = _issue_cookie_token(fresh["id"], fresh["email_normalized"], fresh["auth_version"], remember=remember)
    return {"user": serialize_user(fresh), "token": token, "max_age": max_age}


def get_current_user(conn, user_id: UUID) -> dict:
    row = UserRepo(conn).get_by_id(user_id)
    if row is None or row["status"] != "active":
        raise Unauthorized("로그인이 필요합니다.")
    return {"user": serialize_user(row)}


def check_email_availability(conn, email: str) -> bool:
    normalized = _validate_email(email)
    return not UserRepo(conn).email_taken(normalized)


def update_profile(conn, user_id: UUID, *, display_name: str | None, email: str | None,
                    marketing_agreed: bool | None) -> dict:
    repo = UserRepo(conn)
    current = repo.get_by_id(user_id)
    if current is None or current["status"] != "active":
        raise Unauthorized("로그인이 필요합니다.")

    normalized_email = None
    if email is not None:
        normalized_email = _validate_email(email)
        if normalized_email != current["email_normalized"] and repo.email_taken(normalized_email, exclude_user_id=user_id):
            raise Conflict("이미 사용 중인 이메일입니다.", field="email", code="email_taken")
    name = _validate_display_name(display_name) if display_name is not None else None

    try:
        with conn.transaction():
            row = repo.update_profile(user_id, display_name=name, email_normalized=normalized_email, marketing_agreed=marketing_agreed)
    except psycopg.errors.UniqueViolation:
        raise Conflict("이미 사용 중인 이메일입니다.", field="email", code="email_taken") from None
    return {"user": serialize_user(row)}


def change_password(conn, user_id: UUID, *, current_password: str, new_password: str) -> dict:
    repo = UserRepo(conn)
    row = repo.get_by_id(user_id)
    if row is None or row["status"] != "active":
        raise Unauthorized("로그인이 필요합니다.")
    if row["password_hash"] is None or not verify_password(row["password_hash"], current_password):
        raise Unauthorized("현재 비밀번호가 올바르지 않습니다.", code="invalid_password")
    _validate_password(new_password)

    new_auth_version = repo.update_password(user_id, hash_password(new_password))
    token, max_age = _issue_cookie_token(user_id, row["email_normalized"], new_auth_version, remember=True)
    return {"token": token, "max_age": max_age}


def withdraw(conn, user_id: UUID, *, password: str) -> None:
    repo = UserRepo(conn)
    row = repo.get_by_id(user_id)
    if row is None or row["status"] != "active":
        raise Unauthorized("로그인이 필요합니다.")
    if row["password_hash"] is None or not verify_password(row["password_hash"], password):
        raise Unauthorized("현재 비밀번호가 올바르지 않습니다.", code="invalid_password")

    anonymized_email = f"deleted-{user_id}@withdrawn.truefit.local"
    anonymized_name = "탈퇴한 사용자"
    with conn.transaction():
        repo.withdraw(user_id, anonymized_email=anonymized_email, anonymized_name=anonymized_name)
