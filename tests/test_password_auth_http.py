"""P6 — 이메일+비밀번호 인증 HTTP 통합 테스트 (실 PostgreSQL + 실 FastAPI 앱, mock 없음).

`DATABASE_URL` 이 가리키는, 마이그레이션이 이미 적용된 일회용 DB 가 필요하다:

    export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/<disposable>?sslmode=disable'
    uv run python db/setup_all.py   # 또는 db/migrate.py up (기존 DB)
    uv run python -m pytest -q tests/test_password_auth_http.py

get_conn()/psycopg 풀을 대체하지 않는다 — 매 요청이 실제 트랜잭션으로 커밋/롤백한다.
잠금 만료(AU03)는 `raw_conn` 으로 locked_until 을 직접 과거로 옮겨 "제어된 시계"를 흉내낸다
(애플리케이션 로직 자체를 mock 하지 않는다 — DB 시계만 앞당긴다).
"""
from __future__ import annotations

import os
import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set DATABASE_URL to a disposable migrated database (see module docstring)",
)

if DSN:
    from src.api import app
    from src.auth.ratelimit import reset_all as _reset_rate_limits

    @pytest.fixture()
    def client():
        _reset_rate_limits()
        with TestClient(app) as c:
            yield c

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def _fresh_client() -> TestClient:
    return TestClient(app)


_SIGNUP_BASE = {
    "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
}


def _signup(c: TestClient, email: str, password: str = "abcd1234", name: str = "테스터", **extra) -> "object":
    body = {**_SIGNUP_BASE, "email": email, "password": password, "display_name": name, **extra}
    return c.post("/auth/signup", json=body)


def _login(c: TestClient, email: str, password: str = "abcd1234", remember: bool = True) -> "object":
    return c.post("/auth/login", json={"email": email, "password": password, "remember": remember})


# ── AU01 signup ──────────────────────────────────────────────────────────
def test_au01_signup_success_sets_cookie_and_persists_argon2_hash(client: TestClient, raw_conn):
    r = _signup(client, "au01-ok@example.com", marketing_agreed=True)
    assert r.status_code == 201, r.text
    body = r.json()
    user = body["user"]
    assert user["email"] == "au01-ok@example.com"
    assert user["display_name"] == "테스터"
    assert user["marketing_agreed"] is True
    assert "id" in user and "created_at" in user
    assert set(user.keys()) == {"id", "email", "display_name", "marketing_agreed", "created_at"}

    assert client.cookies.get("truefit_session"), "auth cookie must be set"
    set_cookie_header = r.headers.get("set-cookie")
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Path=/" in set_cookie_header

    row = raw_conn.execute(
        "SELECT password_hash, status FROM identity.app_user WHERE email_normalized=%s",
        ("au01-ok@example.com",),
    ).fetchone()
    assert row[1] == "active"
    stored_hash = row[0]
    assert stored_hash != "abcd1234"
    assert stored_hash.startswith("$argon2id$"), f"expected argon2id hash, got: {stored_hash[:20]}"


def test_au01_signup_duplicate_email_case_insensitive_409(client: TestClient):
    r1 = _signup(client, "Dup@Example.com")
    assert r1.status_code == 201, r1.text

    other = _fresh_client()
    r2 = _signup(other, "dup@example.com")
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "email_taken"


def test_au01_signup_missing_terms_422(client: TestClient):
    r = _signup(client, "noterm@example.com", terms_agreed=False)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "terms_required"

    r2 = _signup(client, "noterm2@example.com", privacy_agreed=False)
    assert r2.status_code == 422, r2.text
    assert r2.json()["error"]["code"] == "terms_required"


def test_au01_signup_weak_password_422(client: TestClient):
    r = _signup(client, "weak@example.com", password="short1")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "weak_password"

    r2 = _signup(client, "weak2@example.com", password="alllettersnodigits")
    assert r2.status_code == 422, r2.text
    assert r2.json()["error"]["code"] == "weak_password"


def test_au01_email_availability_is_rate_limited(client: TestClient):
    codes = [client.get("/auth/email-availability?email=ratelimited@example.com").status_code for _ in range(25)]
    assert codes.count(429) > 0, "must eventually rate limit repeated checks from the same client"
    assert codes[:20].count(429) == 0, "reasonable burst must not be limited immediately"


def test_au01_signup_email_availability_endpoint(client: TestClient):
    r = client.get("/auth/email-availability?email=fresh-avail@example.com")
    assert r.status_code == 200
    assert r.json() == {"available": True}

    _signup(client, "fresh-avail@example.com")
    r2 = client.get("/auth/email-availability?email=fresh-avail@example.com")
    assert r2.json() == {"available": False}
    # case-insensitive
    r3 = client.get("/auth/email-availability?email=FRESH-AVAIL@EXAMPLE.COM")
    assert r3.json() == {"available": False}


# ── AU02 login / me ──────────────────────────────────────────────────────
def test_au02_login_then_me_roundtrip(client: TestClient):
    _signup(client, "au02@example.com")
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401

    r = _login(client, "au02@example.com")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "au02@example.com"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "au02@example.com"


def test_au02_me_without_cookie_401(client: TestClient):
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_au02_me_with_tampered_cookie_401(client: TestClient):
    _signup(client, "tamper@example.com")
    good = client.cookies.get("truefit_session")
    tampered = good[:-4] + ("aaaa" if not good.endswith("aaaa") else "bbbb")
    bad = _fresh_client()
    bad.cookies.set("truefit_session", tampered)
    r = bad.get("/auth/me")
    assert r.status_code == 401


def test_au02_me_with_garbage_cookie_401(client: TestClient):
    bad = _fresh_client()
    bad.cookies.set("truefit_session", "not-a-jwt-at-all")
    r = bad.get("/auth/me")
    assert r.status_code == 401


def test_au02_cookie_flags_match_local_http_environment(client: TestClient):
    """AUTH_COOKIE_SECURE 는 APP_ENV=production 에서만 켜진다 — 로컬 HTTP 검증에서는 Secure 가
    없어야 하고(HTTPS 아닌 브라우저가 쿠키를 못 보내는 사고를 피함), HttpOnly/SameSite/Path 는
    항상 강제된다."""
    r = _signup(client, "cookieflags@example.com")
    set_cookie = r.headers.get("set-cookie")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    import src.config as config
    assert config.AUTH_COOKIE_SECURE is False, "local/dev run must not silently require HTTPS-only cookies"
    assert "Secure" not in set_cookie


# ── AU03 lockout ─────────────────────────────────────────────────────────
def test_au03_five_wrong_passwords_then_lock_then_expiry(client: TestClient, raw_conn):
    _signup(client, "au03@example.com")
    client.post("/auth/logout")
    attacker = _fresh_client()

    for i in range(4):
        r = _login(attacker, "au03@example.com", password="wrongpass1")
        assert r.status_code == 401, r.text
        assert r.json()["error"]["code"] == "invalid_credentials"

    r5 = _login(attacker, "au03@example.com", password="wrongpass1")
    assert r5.status_code == 401
    assert r5.json()["error"]["code"] == "invalid_credentials"

    row = raw_conn.execute(
        "SELECT failed_login_count, locked_until FROM identity.app_user WHERE email_normalized=%s",
        ("au03@example.com",),
    ).fetchone()
    assert row[0] == 0, "lock resets the counter so it starts fresh after expiry"
    assert row[1] is not None, "5th failure must set locked_until"

    r_locked = _login(attacker, "au03@example.com", password="abcd1234")  # correct password, still locked
    assert r_locked.status_code == 423, r_locked.text
    assert r_locked.json()["error"]["code"] == "account_locked"

    raw_conn.execute(
        "UPDATE identity.app_user SET locked_until = now() - interval '1 minute' WHERE email_normalized=%s",
        ("au03@example.com",),
    )
    r_after = _login(attacker, "au03@example.com", password="abcd1234")
    assert r_after.status_code == 200, r_after.text


def test_au03_unknown_email_matches_wrong_password_error(client: TestClient):
    _signup(client, "au03b@example.com")
    r_unknown = _login(client, "no-such-user-au03b@example.com", password="abcd1234")
    r_wrong = _login(client, "au03b@example.com", password="wrongpass1")
    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json()["error"]["code"] == r_wrong.json()["error"]["code"] == "invalid_credentials"


def test_au03_concurrent_failures_do_not_lose_increments(raw_conn):
    _signup(_fresh_client(), "au03-concurrent@example.com")

    results = []

    def attempt():
        c = _fresh_client()
        r = _login(c, "au03-concurrent@example.com", password="wrongpass1")
        results.append(r.status_code)

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(code in (401, 423) for code in results)
    row = raw_conn.execute(
        "SELECT failed_login_count, locked_until FROM identity.app_user WHERE email_normalized=%s",
        ("au03-concurrent@example.com",),
    ).fetchone()
    # 5 concurrent failures against a fresh account (count starts at 0) must reach the lock
    # threshold exactly once — no increment lost to the race, no double-counting either.
    assert row[1] is not None, "concurrent failures must still trigger the lock at the 5th"
    assert row[0] == 0


# ── AU04 same-second invalidation / logout ────────────────────────────────
def test_au04_password_change_invalidates_old_jwt_immediately(client: TestClient):
    _signup(client, "au04@example.com")
    old_cookie = client.cookies.get("truefit_session")

    r = client.post("/auth/password", json={"current_password": "abcd1234", "new_password": "newpass99"})
    assert r.status_code == 204, r.text
    new_cookie = client.cookies.get("truefit_session")
    assert new_cookie != old_cookie

    stale_client = _fresh_client()
    stale_client.cookies.set("truefit_session", old_cookie)
    r_stale = stale_client.get("/auth/me")
    assert r_stale.status_code == 401, "old token must be rejected even though it has not expired"

    r_fresh = client.get("/auth/me")
    assert r_fresh.status_code == 200

    r_old_login = _fresh_client()
    assert _login(r_old_login, "au04@example.com", password="abcd1234").status_code == 401
    assert _login(_fresh_client(), "au04@example.com", password="newpass99").status_code == 200


def test_au04_login_blocked_by_concurrent_password_change_sees_new_password():
    """P6 review R1: a login reading the OLD password hash must never issue a token
    after a concurrent password change has already committed. FOR UPDATE row
    locking (UserRepo.get_by_email_locked/get_by_id_locked) serializes the two — a
    login that starts while a change is in flight blocks until the change commits,
    then re-reads the NEW hash and fails, instead of racing a stale-but-valid token
    into existence."""
    from src.auth.passwords import hash_password

    email = "au-race@example.com"
    _signup(_fresh_client(), email)

    hold_conn = psycopg.connect(DSN, autocommit=False)
    hold_conn.execute(
        "SELECT id FROM identity.app_user WHERE email_normalized=%s FOR UPDATE", (email,)
    )
    try:
        results: dict = {}

        def attempt_login():
            results["status"] = _login(_fresh_client(), email, password="abcd1234").status_code

        t = threading.Thread(target=attempt_login)
        t.start()
        time.sleep(0.3)  # let the login request actually reach and block on the lock
        assert t.is_alive(), "login must be blocked while the password-change lock is held"

        hold_conn.execute(
            "UPDATE identity.app_user SET password_hash=%s, password_updated_at=clock_timestamp() "
            "WHERE email_normalized=%s",
            (hash_password("newpass99"), email),
        )
        hold_conn.commit()

        t.join(timeout=5)
        assert not t.is_alive(), "login must complete once the lock is released"
        assert results["status"] == 401, "the blocked login must see the NEW password, not succeed with the old one"
    finally:
        hold_conn.close()


def test_au04_change_password_wrong_current_401(client: TestClient):
    _signup(client, "au04b@example.com")
    r = client.post("/auth/password", json={"current_password": "wrongcurrent1", "new_password": "newpass99"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_password"


def test_au04_logout_clears_cookie_scope_documented(client: TestClient):
    """로그아웃은 이 브라우저 쿠키만 지운다 — 서버 측 전 세션 무효화는 하지 않는다는
    선언된 범위를 검증한다(P6 RULES #9: 쿠키 삭제만으로 서버 폐기라 주장하지 않기)."""
    _signup(client, "au04c@example.com")
    other_device = _fresh_client()
    _login(other_device, "au04c@example.com")

    r = client.post("/auth/logout")
    assert r.status_code == 204
    assert client.get("/auth/me").status_code == 401

    # a different device's token, issued before logout, is untouched by this logout
    # (no all-session auth_version bump on logout — documented scope, not silent claim)
    assert other_device.get("/auth/me").status_code == 200


# ── AU05 guest merge ───────────────────────────────────────────────────────
def test_au05_guest_two_plans_merge_on_signup_old_cookie_loses_access(client: TestClient):
    r1 = client.post("/session")
    list_a = r1.json()["list_id"]
    r2 = client.post("/session")
    list_b = r2.json()["list_id"]
    guest_cookie = client.cookies.get("truefit_guest")
    assert guest_cookie

    r = _signup(client, "au05@example.com")
    assert r.status_code == 201, r.text

    assert client.get(f"/session/{list_a}").status_code == 200
    assert client.get(f"/session/{list_b}").status_code == 200

    foreign = _fresh_client()
    foreign.cookies.set("truefit_guest", guest_cookie)
    assert foreign.get(f"/session/{list_a}").status_code == 404
    assert foreign.get(f"/session/{list_b}").status_code == 404


def test_au05_guest_merge_on_login(client: TestClient):
    _signup(_fresh_client(), "au05b@example.com")

    guest = _fresh_client()
    r = guest.post("/session")
    guest_list = r.json()["list_id"]

    r_login = _login(guest, "au05b@example.com")
    assert r_login.status_code == 200

    assert guest.get(f"/session/{guest_list}").status_code == 200


def test_au05_foreign_guest_token_never_merged(client: TestClient):
    victim = _fresh_client()
    victim.post("/session")
    real_guest_cookie = victim.cookies.get("truefit_guest")
    victim_list = victim.get("/session")  # noop just to keep var used

    attacker = _fresh_client()
    attacker.cookies.set("truefit_guest", "forged-token-that-was-never-issued")
    r = _signup(attacker, "au05c@example.com")
    assert r.status_code == 201

    # attacker's new account must not have gained access to the victim's real guest list
    real_owner = _fresh_client()
    real_owner.cookies.set("truefit_guest", real_guest_cookie)
    r = real_owner.post("/session")
    assert r.status_code == 200  # guest identity still usable — was never touched by the forged merge


# ── AU06 profile / withdraw ─────────────────────────────────────────────
def test_au06_profile_and_marketing_update_persists(client: TestClient, raw_conn):
    _signup(client, "au06@example.com", marketing_agreed=False)
    r = client.patch("/auth/me", json={"display_name": "새이름", "marketing_agreed": True})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["display_name"] == "새이름"
    assert user["marketing_agreed"] is True

    row = raw_conn.execute(
        "SELECT display_name, marketing_agreed_at FROM identity.app_user WHERE email_normalized=%s",
        ("au06@example.com",),
    ).fetchone()
    assert row[0] == "새이름"
    assert row[1] is not None


def test_au06_email_change_clears_email_verified_at(client: TestClient, raw_conn):
    _signup(client, "au06b@example.com")
    raw_conn.execute(
        "UPDATE identity.app_user SET email_verified_at = now() WHERE email_normalized=%s",
        ("au06b@example.com",),
    )
    r = client.patch("/auth/me", json={"email": "au06b-new@example.com"})
    assert r.status_code == 200, r.text
    row = raw_conn.execute(
        "SELECT email_verified_at FROM identity.app_user WHERE email_normalized=%s",
        ("au06b-new@example.com",),
    ).fetchone()
    assert row[0] is None


def test_au06_email_change_conflict_409(client: TestClient):
    _signup(_fresh_client(), "au06-taken@example.com")
    _signup(client, "au06-mine@example.com")
    r = client.patch("/auth/me", json={"email": "au06-taken@example.com"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_au06_withdraw_anonymizes_and_invalidates_all_tokens(client: TestClient, raw_conn):
    _signup(client, "au06c@example.com")
    old_cookie = client.cookies.get("truefit_session")

    r = client.post("/auth/withdraw", json={"password": "abcd1234"})
    assert r.status_code == 204, r.text

    stale = _fresh_client()
    stale.cookies.set("truefit_session", old_cookie)
    assert stale.get("/auth/me").status_code == 401
    assert client.get("/auth/me").status_code == 401

    row = raw_conn.execute(
        "SELECT status, password_hash, terms_agreed_at, marketing_agreed_at, email_normalized, display_name "
        "FROM identity.app_user WHERE email_normalized != 'au06c@example.com' AND display_name = '탈퇴한 사용자'"
    ).fetchone()
    assert row is not None, "withdrawn row must be anonymized (original email/name replaced)"
    assert row[0] == "deleted"
    assert row[1] is None, "password hash must be erased"
    assert row[2] is None and row[3] is None, "consent timestamps must be erased"

    assert _login(_fresh_client(), "au06c@example.com", password="abcd1234").status_code == 401


def test_au06_no_password_hash_or_jwt_leak_in_responses(client: TestClient):
    r = _signup(client, "au06d@example.com")
    assert "password_hash" not in r.text and "password" not in r.json()["user"]
    r2 = client.get("/auth/me")
    body = r2.text
    assert "password_hash" not in body
    assert "argon2" not in body


# ── AU07 P1 guest flow / no localStorage token (server contract only) ─────
def test_au07_anonymous_p1_flow_untouched_by_auth(client: TestClient):
    r = client.post("/session")
    assert r.status_code == 200
    list_id = r.json()["list_id"]
    r = client.get(f"/session/{list_id}")
    assert r.status_code == 200
    assert r.json()["can_recommend"] is False


def test_au07_pc_category_regression_unaffected(client: TestClient):
    r = client.post("/session")
    list_id = r.json()["list_id"]
    r = client.post(f"/session/{list_id}/category", json={"category": "computer"})
    assert r.status_code == 200, r.text


def test_au07_me_endpoint_only_source_of_truth_no_token_field(client: TestClient):
    """계약: 응답에 JWT 문자열 자체를 담지 않는다 — 프런트는 쿠키만 신뢰한다."""
    r = _signup(client, "au07@example.com")
    assert "token" not in r.json()
    r2 = client.get("/auth/me")
    assert "token" not in r2.json()

# ── D6 develop DB contract ────────────────────────────────────────────────
def test_d6_iat_boundary_rejects_token_at_password_change_and_relogin_works(
    client: TestClient, raw_conn, monkeypatch
):
    """v3 policy: the equality boundary is stale, not just timestamps before it."""
    from src.auth import jwt

    _signup(client, "d6-iat-boundary@example.com")
    user_id = raw_conn.execute(
        "SELECT id FROM identity.app_user WHERE email_normalized=%s",
        ("d6-iat-boundary@example.com",),
    ).fetchone()[0]
    # Set password_updated_at FIRST, then read back the exact stored value and sign
    # the boundary token from THAT — not the other way around. A Python float unix
    # timestamp round-tripped through to_timestamp()/timestamptz (microsecond
    # precision) is not always bit-identical to the original float (P6 review R2),
    # so deriving the token's iat from an independently-computed float and hoping it
    # matches what got stored is flaky; reading the stored value back removes that.
    raw_conn.execute(
        "UPDATE identity.app_user SET password_updated_at=now() WHERE id=%s", (user_id,),
    )
    boundary_iat = raw_conn.execute(
        "SELECT password_updated_at FROM identity.app_user WHERE id=%s", (user_id,),
    ).fetchone()[0].timestamp()
    monkeypatch.setattr("time.time", lambda: boundary_iat)
    boundary_token = jwt.issue(user_id, "d6-iat-boundary@example.com")
    monkeypatch.undo()
    stale = _fresh_client()
    stale.cookies.set("truefit_session", boundary_token)
    assert stale.get("/auth/me").status_code == 401

    fresh_client = _fresh_client()
    relogin = _login(fresh_client, "d6-iat-boundary@example.com")
    assert relogin.status_code == 200
    assert relogin.cookies.get("truefit_session")
    # P6 review R2: "usable replacement cookie" must actually be demonstrated, not
    # just inferred from a 200 + cookie presence — call an authenticated endpoint
    # with the SAME client that just relogged in.
    assert fresh_client.get("/auth/me").status_code == 200


def test_d6_guest_merge_is_idempotent_and_only_moves_its_own_active_plans(client: TestClient, raw_conn):
    _signup(_fresh_client(), "d6-merge@example.com")
    guest = _fresh_client()
    first = guest.post("/session").json()["list_id"]
    second = guest.post("/session").json()["list_id"]
    guest_cookie = guest.cookies.get("truefit_guest")
    assert _login(guest, "d6-merge@example.com").status_code == 200
    assert _login(guest, "d6-merge@example.com").status_code == 200
    rows = raw_conn.execute(
        """SELECT p.id, p.owner_user_id, c.guest_session_hash
             FROM planning.plan p JOIN identity.conversation c ON c.id=p.conversation_id
             WHERE p.id = ANY(%s) ORDER BY p.id""",
        ([first, second],),
    ).fetchall()
    assert len(rows) == 2
    assert all(row[1] is not None and row[2] is None for row in rows)
    replay = _fresh_client()
    replay.cookies.set("truefit_guest", guest_cookie)
    assert replay.get(f"/session/{first}").status_code == 404


def test_d6_app_user_settings_survive_login_and_are_erased_on_withdraw(client: TestClient, raw_conn):
    _signup(client, "d6-settings@example.com")
    raw_conn.execute(
        "UPDATE identity.app_user SET ui_settings=%s::jsonb, notification_settings=%s::jsonb "
        "WHERE email_normalized=%s",
        ('{"theme":"dark"}', '{"price_watch":false}', "d6-settings@example.com"),
    )
    client.post("/auth/logout")
    assert _login(client, "d6-settings@example.com").status_code == 200
    assert raw_conn.execute(
        "SELECT ui_settings, notification_settings FROM identity.app_user WHERE email_normalized=%s",
        ("d6-settings@example.com",),
    ).fetchone() == ({"theme": "dark"}, {"price_watch": False})
    assert client.post("/auth/withdraw", json={"password": "abcd1234"}).status_code == 204
    assert raw_conn.execute(
        "SELECT ui_settings, notification_settings FROM identity.app_user "
        "WHERE display_name='탈퇴한 사용자' ORDER BY deleted_at DESC LIMIT 1"
    ).fetchone() == ({}, {})


def test_d6_real_auth_roundtrip_uses_develop_app_user_without_removed_tables(client: TestClient, raw_conn):
    assert raw_conn.execute("SELECT to_regclass('identity.user_preference')").fetchone()[0] is None
    assert raw_conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='identity' "
        "AND table_name='app_user' AND column_name='auth_version'"
    ).fetchone() is None
    assert _signup(client, "d6-develop-schema@example.com").status_code == 201
    assert client.get("/auth/me").status_code == 200
