"""이메일+비밀번호 인증 통합 테스트 (docs/frontend_외부수정요청.md §A).

실제 로컬 PostgreSQL(DATABASE_URL, db/setup_all.py로 준비)이 필요하다.
autocommit 연결을 쓴다 — `password_updated_at`/`locked_until` 판정에 쓰는 PostgreSQL `now()`는
트랜잭션 시작 시각으로 고정되므로(문서화된 동작), 한 트랜잭션에 여러 서비스 호출을 묶으면
가입→비밀번호 변경 사이에 실제로 시간이 흘러도 값이 그대로 남아 실제 요청 경계를 반영하지
못한다. 만든 계정은 id로 추적해 테스트가 끝나면 정확히 그 행만 지운다(탈퇴로 이메일이
`deleted+...`로 바뀐 뒤에도 이메일이 아니라 id로 찾는다).
"""
from __future__ import annotations

import base64
import json
import time
import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL, LOGIN_MAX_FAILURES
from src.errors import AccountLocked, Conflict, Unauthorized
from src.services import auth_service


class _Ctx:
    """테스트 1건의 DB 연결 + 이번 테스트가 만든 user id 목록(정리용)."""

    def __init__(self, connection):
        self.conn = connection
        self.created_ids: list[str] = []

    def signup(self, email: str, password: str = "abc12345"):
        user, token = auth_service.signup(
            self.conn, _guest(),
            email=email, password=password, display_name="테스트",
            terms_agreed=True, privacy_agreed=True, marketing_agreed=False,
        )
        self.created_ids.append(user["id"])
        return user, token


@pytest.fixture
def ctx():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    has_settings = connection.execute(
        """SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='identity' AND table_name='app_user'
              AND column_name='notification_settings'
        )"""
    ).fetchone()[0]
    if not has_settings:
        connection.close()
        pytest.skip("develop DB 스키마가 아닙니다 — db/setup_all.py로 준비하세요.")
    context = _Ctx(connection)
    try:
        yield context
    finally:
        if context.created_ids:
            connection.execute(
                "DELETE FROM identity.app_user WHERE id = ANY(%s::uuid[])",
                (context.created_ids,),
            )
        connection.close()


def _guest() -> Principal:
    return Principal(user_id=None, browser_token=None)


def _unique_email() -> str:
    return f"auth-test-{uuid.uuid4().hex}@example.com"


def _decode_iat(token: str) -> int:
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["iat"]


def test_signup_then_duplicate_email_is_rejected(ctx):
    email = _unique_email()
    user, token = ctx.signup(email)
    assert user["email"] == email
    assert token

    with pytest.raises(Conflict):
        ctx.signup(email)


def test_login_locks_after_max_failures(ctx):
    email = _unique_email()
    ctx.signup(email)

    for _ in range(LOGIN_MAX_FAILURES):
        with pytest.raises(Unauthorized):
            auth_service.login(ctx.conn, _guest(), email=email, password="wrong-pass1", remember=False)

    with pytest.raises(AccountLocked):
        auth_service.login(ctx.conn, _guest(), email=email, password="abc12345", remember=False)


def test_password_change_invalidates_old_token(ctx):
    email = _unique_email()
    user, old_token = ctx.signup(email)
    old_principal = Principal(
        user_id=uuid.UUID(user["id"]), browser_token=None, session_iat=_decode_iat(old_token)
    )

    auth_service.get_me(ctx.conn, old_principal)  # 변경 전에는 유효

    time.sleep(1)  # password_updated_at(초 단위) 차이를 만든다
    auth_service.change_password(ctx.conn, old_principal, current_password="abc12345", new_password="newpass123")

    with pytest.raises(Unauthorized):
        auth_service.get_me(ctx.conn, old_principal)


def test_withdraw_then_login_fails_and_resignup_allowed(ctx):
    email = _unique_email()
    user, token = ctx.signup(email)
    principal = Principal(user_id=uuid.UUID(user["id"]), browser_token=None, session_iat=_decode_iat(token))

    auth_service.withdraw(ctx.conn, principal, password="abc12345")

    with pytest.raises(Unauthorized):
        auth_service.login(ctx.conn, _guest(), email=email, password="abc12345", remember=False)

    new_user, _ = ctx.signup(email)  # 익명화로 같은 이메일 즉시 재가입 가능
    assert new_user["email"] == email
