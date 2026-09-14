"""P1 — 게스트 세션·조건 대화 HTTP 통합 테스트 (실 PostgreSQL + 실 FastAPI 앱, mock 없음).

`DATABASE_URL` 이 가리키는, 마이그레이션이 이미 적용된 일회용 DB 가 필요하다:

    export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/<disposable>?sslmode=disable'
    uv run python db/setup_all.py
    uv run python -m pytest -q tests/test_baby_session_http.py

get_conn()/psycopg 풀을 딱히 대체하지 않는다 — 매 요청이 실제 트랜잭션 1개를 커밋/롤백한다.
두 개의 독립된 `TestClient` (게스트 A/B) 로 소유권 경계를, 별도 psycopg 연결로 실제 조건/이력
행을 검증한다.
"""
from __future__ import annotations

import os
import threading

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

    @pytest.fixture()
    def client():
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


def _create(c: TestClient) -> tuple[str, str | None]:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"], r.cookies.get("truefit_guest")


def _choose_baby(c: TestClient, list_id: str, mode: str = "born") -> dict:
    r = c.post(f"/session/{list_id}/category", json={"category": "baby", "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()


def _fields(state: dict) -> dict:
    return {f["key"]: f for f in state["fields"]}


# ── SS01 ──────────────────────────────────────────────────────────────────
def test_ss01_no_cookie_creates_session_and_sets_cookie(client: TestClient):
    r = client.post("/session")
    assert r.status_code == 200
    list_id = r.json()["list_id"]
    assert client.cookies.get("truefit_guest"), "guest cookie must be set"

    state = client.get(f"/session/{list_id}").json()
    assert state["category"] is None
    assert state["can_recommend"] is False

    # fresh second request (new TestClient instance, same cookie jar contents) sees the same state
    guest_token = client.cookies.get("truefit_guest")
    other = _fresh_client()
    other.cookies.set("truefit_guest", guest_token)
    state2 = other.get(f"/session/{list_id}").json()
    assert state2["list_id"] == list_id
    assert state2["category"] is None


def test_ss01_returning_guest_creates_multiple_lists_without_losing_the_first(client: TestClient):
    list_a, token_a = _create(client)
    assert token_a is not None
    # second create with the SAME client (cookie jar carries the guest cookie) must reuse identity
    list_b, token_b = _create(client)
    assert list_b != list_a
    assert token_b == token_a, "returning guest must not rotate its cookie"

    # first list must still be reachable — this is the exact regression the sync audit reported
    r = client.get(f"/session/{list_a}")
    assert r.status_code == 200, r.text
    r = client.get(f"/session/{list_b}")
    assert r.status_code == 200, r.text


# ── SS02 ──────────────────────────────────────────────────────────────────
def test_ss02_message_extraction_and_can_recommend_roundtrip(client: TestClient, raw_conn):
    list_id, _ = _create(client)
    _choose_baby(client, list_id, mode="born")

    state = client.post(f"/session/{list_id}/message", json={"text": "8개월, 예산 30만원"}).json()
    fields = _fields(state)
    assert fields["age_stage"]["value"]["months"] == 8
    assert fields["age_stage"]["status"] == "confirmed"  # exact free-text digit, not a chip range
    assert fields["budget_max"]["value"] == 300000

    # fill the rest via chip answers to reach can_recommend
    def answer(qid, selected):
        nonlocal state
        state = client.post(f"/session/{list_id}/answer", json={"question_id": qid, "selected": selected}).json()

    answer("q_needs", ["수유", "외출"])
    answer("q_health_skin", ["특이사항 없음"])
    answer("q_owned", ["없음"])
    assert state["can_recommend"] is True

    before_condition_id = raw_conn.execute(
        "SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key='budget_max' AND status='active'",
        (state["revision_id"],),
    ).fetchone()[0]

    state = client.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": None}).json()
    assert state["can_recommend"] is False
    assert _fields(state)["budget_max"]["status"] == "missing"

    # old condition history is preserved (superseded, not deleted)
    row = raw_conn.execute(
        "SELECT status FROM planning.plan_condition WHERE id=%s", (before_condition_id,)
    ).fetchone()
    assert row[0] == "superseded"


def test_ss02_health_skin_none_is_answered_not_missing(client: TestClient):
    """빈 리스트([]) 로 저장된 '특이사항 없음' 은 응답한 상태 — 미응답(missing) 과 달라야 한다."""
    list_id, _ = _create(client)
    _choose_baby(client, list_id, mode="born")
    state = client.post(
        f"/session/{list_id}/answer",
        json={"question_id": "q_health_skin", "selected": ["특이사항 없음"]},
    ).json()
    field = _fields(state)["health_skin"]
    assert field["value"] == []
    assert field["status"] == "confirmed"


# ── SS03 ──────────────────────────────────────────────────────────────────
def test_ss03_invalid_inputs_are_rejected_or_left_missing(client: TestClient, raw_conn):
    list_id, _ = _create(client)
    state = _choose_baby(client, list_id, mode="born")
    revision_id = state["revision_id"]

    def condition_count():
        return raw_conn.execute(
            "SELECT count(*) FROM planning.plan_condition WHERE revision_id=%s", (revision_id,)
        ).fetchone()[0]

    n_before = condition_count()

    # "몰라요" — no extractable field, must not fabricate a condition
    r = client.post(f"/session/{list_id}/message", json={"text": "몰라요"})
    assert r.status_code == 200
    assert _fields(r.json()).get("age_stage", {}).get("status", "missing") == "missing"

    # negative budget
    r = client.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": -1000})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "budget_max"

    # fractional months
    r = client.patch(f"/session/{list_id}/slot", json={"field": "age_months", "value": 8.5})
    assert r.status_code == 422

    # unknown field
    r = client.patch(f"/session/{list_id}/slot", json={"field": "does_not_exist", "value": 1})
    assert r.status_code == 422
    assert r.json()["error"]["field"] == "field"

    # none + other selected together
    r = client.post(
        f"/session/{list_id}/answer",
        json={"question_id": "q_health_skin", "selected": ["특이사항 없음", "아토피"]},
    )
    assert r.status_code == 422

    # none of the above rejected calls should have inserted a persisted condition row
    assert condition_count() == n_before

    # invalid date for prenatal due_date (need prenatal mode first — that switch itself is a
    # legitimate mutation, so re-baseline after it before checking the rejected date)
    _choose_baby(client, list_id, mode="prenatal")
    n_after_mode_switch = condition_count()
    r = client.post(
        f"/session/{list_id}/answer",
        json={"question_id": "q_due_date", "selected": ["2026-13-40"]},
    )
    assert r.status_code == 422
    assert condition_count() == n_after_mode_switch


# ── SS04 ──────────────────────────────────────────────────────────────────
def test_ss04_other_guest_cannot_access_or_mutate(client: TestClient):
    list_a, _ = _create(client)
    guest_b = _fresh_client()
    guest_b.post("/session")  # mint guest B's own identity/cookie

    assert guest_b.get(f"/session/{list_a}").status_code == 404
    assert guest_b.patch(f"/session/{list_a}/slot", json={"field": "budget_max", "value": 1000}).status_code == 404
    assert guest_b.post(f"/session/{list_a}/reset").status_code == 404


def test_ss04_missing_or_forged_cookie_has_no_access(client: TestClient):
    list_a, _ = _create(client)

    no_cookie = _fresh_client()
    assert no_cookie.get(f"/session/{list_a}").status_code == 404

    forged = _fresh_client()
    forged.cookies.set("truefit_guest", "not-a-real-token-" + "x" * 20)
    assert forged.get(f"/session/{list_a}").status_code == 404


def test_ss04_malformed_uuid_is_a_controlled_validation_error(client: TestClient):
    r = client.get("/session/not-a-uuid")
    assert r.status_code == 422


# ── SS05 ──────────────────────────────────────────────────────────────────
def test_ss05_rejected_write_leaves_no_partial_state(client: TestClient, raw_conn):
    list_id, _ = _create(client)
    state = _choose_baby(client, list_id, mode="born")
    revision_id = state["revision_id"]

    lock_before = raw_conn.execute(
        "SELECT lock_version FROM planning.plan_revision WHERE id=%s", (revision_id,)
    ).fetchone()[0]
    msg_count_before = raw_conn.execute(
        "SELECT count(*) FROM identity.message m JOIN planning.plan p ON p.conversation_id=m.conversation_id WHERE p.id=%s",
        (list_id,),
    ).fetchone()[0]

    r = client.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": -1})
    assert r.status_code == 422

    lock_after = raw_conn.execute(
        "SELECT lock_version FROM planning.plan_revision WHERE id=%s", (revision_id,)
    ).fetchone()[0]
    msg_count_after = raw_conn.execute(
        "SELECT count(*) FROM identity.message m JOIN planning.plan p ON p.conversation_id=m.conversation_id WHERE p.id=%s",
        (list_id,),
    ).fetchone()[0]
    assert lock_after == lock_before, "rejected input must not bump lock_version"
    assert msg_count_after == msg_count_before


def test_ss05_concurrent_slot_writes_leave_one_active_row(client: TestClient, raw_conn):
    list_id, _ = _create(client)
    _choose_baby(client, list_id, mode="born")

    results = []

    def do_patch(value):
        c = _fresh_client()
        c.cookies.set("truefit_guest", client.cookies.get("truefit_guest"))
        results.append(c.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": value}).status_code)

    threads = [threading.Thread(target=do_patch, args=(100000 + i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(code == 200 for code in results)
    revision_id = raw_conn.execute(
        "SELECT current_revision_id FROM planning.plan WHERE id=%s", (list_id,)
    ).fetchone()[0]
    active_rows = raw_conn.execute(
        "SELECT count(*) FROM planning.plan_condition WHERE revision_id=%s AND condition_key='budget_max' AND status='active'",
        (revision_id,),
    ).fetchone()[0]
    assert active_rows == 1, "concurrent writers must never leave two active rows for the same key"


# ── SS06 ──────────────────────────────────────────────────────────────────
def test_ss06_prenatal_and_born_fields_roundtrip_independently(client: TestClient):
    list_id, _ = _create(client)
    _choose_baby(client, list_id, mode="born")

    state = client.post(f"/session/{list_id}/message", json={"text": "8개월이에요"}).json()
    assert _fields(state)["age_stage"]["value"]["months"] == 8

    # switch to prenatal — incompatible born-only fields must clear (and the yaml only
    # shows mode-relevant fields, so age_stage disappears from the list entirely here)
    state = _choose_baby(client, list_id, mode="prenatal")
    fields = _fields(state)
    assert "age_stage" not in fields
    assert fields["due_date"]["status"] == "missing"

    state = client.post(
        f"/session/{list_id}/answer",
        json={"question_id": "q_due_date", "selected": ["2026-12-01"]},
    ).json()
    assert _fields(state)["due_date"]["value"] == "2026-12-01"

    # switch back to born — due_date must clear, and the earlier age is NOT silently restored
    state = _choose_baby(client, list_id, mode="born")
    fields = _fields(state)
    assert fields["age_stage"]["status"] == "missing"
    assert "due_date" not in fields or fields.get("due_date", {}).get("status", "missing") != "confirmed"
