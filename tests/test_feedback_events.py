"""P8 FB01/FB02/FB03 — engine.feedback_event 는 내부 append-only 헬퍼다.

FB01/FB02는 `feedback_service`를 직접 불러 실 DB 트랜잭션으로 검증한다(HTTP 불필요) —
중복 idempotency 키가 행 하나만 남기는 것, 허용되지 않은 payload 키/중첩값 거부, 기존
행이 서비스를 통해 수정되지 않는 것, 자동 재학습 잡이 없는 것.

FB03("추천/편집/확정에서 정확히 한 번씩")은 컴퓨터 카테고리의 실 HTTP 플로우로 검증한다
(추천 202+폴링 → 후보 교체 → 항목 제외 → 확정) — `src/services/recommendation_service.py`/
`list_service.py`가 이 세션 도중 유아 파이프라인 복원 작업으로 활발히 동시 수정되던 것이
이제 안정화됐으므로, `patch_item`/`swap_item`/`list_service.confirm()`에
emit_removed/emit_replaced/emit_confirmed를 배선하고 실제로 검증한다. GET/poll이나 실패한
시도가 이벤트를 만들지 않는 것도 같이 확인한다.
"""
from __future__ import annotations

import inspect
import os
from uuid import uuid4

import psycopg
import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set DATABASE_URL to a disposable migrated database",
)

if DSN:
    os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local-test")
    from fastapi.testclient import TestClient

    from src.api import app
    from src.services import feedback_service, recommendation_service  # noqa: E402

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

    @pytest.fixture()
    def plan_revision(raw_conn):
        """실제 plan/revision 한 쌍 — feedback_event가 요구하는 FK를 만족시킨다."""
        row = raw_conn.execute(
            "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
            (f"fb-test-{uuid4()}",),
        ).fetchone()
        conversation_id = row[0]
        row = raw_conn.execute(
            "INSERT INTO planning.plan(conversation_id,name) VALUES (%s,%s) RETURNING id",
            (conversation_id, "fb test plan"),
        ).fetchone()
        plan_id = row[0]
        domain_version_id = raw_conn.execute(
            "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE d.code='baby' ORDER BY dv.version_no DESC LIMIT 1"
        ).fetchone()[0]
        row = raw_conn.execute(
            "INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot) "
            "VALUES (%s,1,%s,%s) RETURNING id",
            (plan_id, domain_version_id, "fb test revision"),
        ).fetchone()
        return {"plan_id": str(plan_id), "revision_id": str(row[0]), "domain_version_id": str(domain_version_id)}

    def _make_run(raw_conn, plan_revision) -> str:
        """A real engine.recommendation_run row — 'recommendation_shown' events have a
        DB CHECK requiring a non-null, FK-valid recommendation_run_id."""
        from src.repo.engine_repo import EngineRepo

        run_id = EngineRepo(raw_conn).start_run(
            plan_revision["revision_id"], plan_revision["domain_version_id"],
            input_snapshot={}, input_hash=uuid4().hex, draft_lock_version=0, engine_versions={},
        )
        return str(run_id)


# ── FB01 ──────────────────────────────────────────────────────────────────
def test_fb01_duplicate_idempotency_key_writes_exactly_one_event(raw_conn, plan_revision):
    kwargs = dict(plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
                 run_id=None, item_id=str(uuid4()), version=1, action="removed")
    first = feedback_service.emit(raw_conn, **kwargs)
    second = feedback_service.emit(raw_conn, **kwargs)
    assert first is True and second is False
    count = raw_conn.execute(
        "SELECT count(*) FROM engine.feedback_event WHERE revision_id=%s", (plan_revision["revision_id"],)
    ).fetchone()[0]
    assert count == 1


@pytest.mark.parametrize("bad_payload", [
    {"email": "user@example.com"},
    {"note": "손으로 적은 비고"},
    {"token": "secret-token"},
    {"candidate_id": {"nested": "dict, not a scalar id"}},
])
def test_fb01_arbitrary_or_nested_payload_is_rejected(raw_conn, plan_revision, bad_payload):
    with pytest.raises(ValueError):
        feedback_service.emit(
            raw_conn, plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
            run_id=None, item_id=None, version=1, action="shown", payload=bad_payload,
        )
    assert raw_conn.execute(
        "SELECT count(*) FROM engine.feedback_event WHERE revision_id=%s", (plan_revision["revision_id"],)
    ).fetchone()[0] == 0, "a rejected payload must not leave a partial row"


def test_fb01_allowlisted_scalar_payload_is_accepted(raw_conn, plan_revision):
    ok = feedback_service.emit(
        raw_conn, plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
        run_id=None, item_id=str(uuid4()), version=1, action="removed",
        payload={"reason_code": "user_deselected", "candidate_id": str(uuid4())},
    )
    assert ok is True


# ── FB02 ──────────────────────────────────────────────────────────────────
def test_fb02_service_exposes_no_update_or_delete_entry_point():
    assert not hasattr(feedback_service, "update")
    assert not hasattr(feedback_service, "delete")
    assert not hasattr(feedback_service, "modify")


def test_fb02_reemitting_same_key_with_a_different_payload_keeps_the_original(raw_conn, plan_revision):
    kwargs = dict(plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
                 run_id=None, item_id=str(uuid4()), version=7, action="removed")
    feedback_service.emit(raw_conn, **kwargs, payload={"reason_code": "first"})
    changed = feedback_service.emit(raw_conn, **kwargs, payload={"reason_code": "second"})
    assert changed is False, "an existing event_key must not be reported as newly written"
    row = raw_conn.execute(
        "SELECT payload FROM engine.feedback_event WHERE revision_id=%s AND event_type='item_removed'",
        (plan_revision["revision_id"],),
    ).fetchone()
    assert row[0]["reason_code"] == "first", "ON CONFLICT DO NOTHING must not let a re-emit overwrite the original row"


def test_fb02_no_automatic_retraining_job_exists():
    from src.engine.stage6_feedback import run_batch
    with pytest.raises(NotImplementedError):
        run_batch()


# ── FB03 ──────────────────────────────────────────────────────────────────
def _create(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _choose_computer(c, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "build"})
    assert r.status_code == 200, r.text
    return r.json()


def _answer(c, list_id: str, qid: str, selected: list) -> dict:
    r = c.post(f"/session/{list_id}/answer", json={"question_id": qid, "selected": selected})
    assert r.status_code == 200, r.text
    return r.json()


def _fill_computer_conditions(c, list_id: str, *, budget: int = 5_000_000) -> dict:
    state = _answer(c, list_id, "q_purpose", ["게임"])
    state = _answer(c, list_id, "q_budget_max", [budget])
    state = _answer(c, list_id, "q_priority", ["성능 우선"])
    assert state["can_recommend"] is True, state
    return state


def _recommend_and_wait(c, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/recommend")
    assert r.status_code == 202, r.text
    r = c.get(f"/session/{list_id}/result")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done", data
    return data


def test_fb03_execute_recommendation_wires_emit_shown_after_complete_run():
    """구조적 회귀 가드: 배선한 지점(컴퓨터 경로, complete_run 직후)이 소스에 있는지 확인한다."""
    source = inspect.getsource(recommendation_service.execute_recommendation)
    complete_idx = source.index("erepo.complete_run(run_id)")
    emit_idx = source.index("feedback_service.emit_shown")
    assert complete_idx < emit_idx, "emit_shown must be called after complete_run, in the same transaction"


def _event_count(raw_conn, revision_id: str, event_type: str) -> int:
    return raw_conn.execute(
        "SELECT count(*) FROM engine.feedback_event WHERE revision_id=%s AND event_type=%s",
        (revision_id, event_type),
    ).fetchone()[0]


def test_fb03_shown_emitted_once_and_polling_get_does_not_duplicate_it(client, raw_conn):
    list_id = _create(client)
    _choose_computer(client, list_id)
    state = _fill_computer_conditions(client, list_id)
    revision_id = state["revision_id"]

    _recommend_and_wait(client, list_id)
    for _ in range(3):
        assert client.get(f"/session/{list_id}/result").status_code == 200
    assert _event_count(raw_conn, revision_id, "recommendation_shown") == 1


def test_fb03_swap_emits_item_replaced_once_and_not_found_swap_emits_none(client, raw_conn):
    list_id = _create(client)
    _choose_computer(client, list_id)
    state = _fill_computer_conditions(client, list_id)
    revision_id = state["revision_id"]
    data = _recommend_and_wait(client, list_id)
    item = next(it for it in data["items"] if it["alternatives_count"] > 0)

    r = client.get(f"/session/{list_id}/items/{item['item_id']}/alternatives")
    assert r.status_code == 200, r.text
    alt = r.json()["items"][0]

    r = client.post(f"/session/{list_id}/items/{item['item_id']}/swap",
                    json={"candidate_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404
    assert _event_count(raw_conn, revision_id, "item_replaced") == 0, "a rejected swap must not emit anything"

    r = client.post(f"/session/{list_id}/items/{item['item_id']}/swap",
                    json={"candidate_id": alt["candidate_id"]})
    assert r.status_code == 200, r.text
    assert _event_count(raw_conn, revision_id, "item_replaced") == 1


def test_fb03_deselect_emits_item_removed_once_and_reselecting_emits_none(client, raw_conn):
    list_id = _create(client)
    _choose_computer(client, list_id)
    state = _fill_computer_conditions(client, list_id)
    revision_id = state["revision_id"]
    data = _recommend_and_wait(client, list_id)
    item_id = data["items"][0]["item_id"]

    r = client.patch(f"/session/{list_id}/items/{item_id}", json={"selected": False})
    assert r.status_code == 200, r.text
    assert _event_count(raw_conn, revision_id, "item_removed") == 1

    # re-selecting, then deselecting again must not be silently skipped nor double-count —
    # each true→false transition is its own event, but the dedup key is version-scoped so a
    # same-version repeat of the exact same transition is still suppressed.
    client.patch(f"/session/{list_id}/items/{item_id}", json={"selected": True})
    r = client.patch(f"/session/{list_id}/items/{item_id}", json={"selected": False})
    assert r.status_code == 200, r.text
    assert _event_count(raw_conn, revision_id, "item_removed") == 1, \
        "same-version repeat of the same transition must not duplicate the event"


def test_fb03_confirm_emits_plan_confirmed_once_and_repeat_confirm_emits_none(raw_conn):
    # sign up first (not the guest-then-signup path) — list ownership is then
    # unambiguously the authenticated user's from the start, same pattern as the
    # baby P7 confirm tests use.
    signed_up = TestClient(app)
    r = signed_up.post("/auth/signup", json={
        "email": f"fb03-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "FB03", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text

    list_id = _create(signed_up)
    _choose_computer(signed_up, list_id)
    state = _fill_computer_conditions(signed_up, list_id)
    revision_id = state["revision_id"]
    _recommend_and_wait(signed_up, list_id)

    r = signed_up.post(f"/lists/{list_id}/confirm", json={"name": "FB03 확정 테스트"})
    assert r.status_code == 200, r.text
    assert _event_count(raw_conn, revision_id, "plan_confirmed") == 1

    r = signed_up.post(f"/lists/{list_id}/confirm", json={"name": "FB03 확정 테스트"})
    assert r.status_code == 409, r.text
    assert _event_count(raw_conn, revision_id, "plan_confirmed") == 1, \
        "a rejected repeat confirm must not emit a second plan_confirmed"


def test_fb03_shown_dedup_key_is_scoped_per_run_not_per_revision(raw_conn, plan_revision):
    """emit_shown의 event_key는 run_id를 포함한다 — 같은 revision에 대한 두 번째(재실행)
    run은 첫 run과 다른 이벤트로 기록돼야 하고, 같은 run을 두 번 부르면(재시도) 하나만
    남아야 한다. execute_recommendation이 실제로 이 함수를 부르는지는 위 테스트가, 부르는
    함수 자체의 dedup/payload 규칙은 FB01이 이미 실 DB로 증명했다 — 여기서는 그 두 사실을
    잇는 마지막 연결고리(run 스코프)만 확인한다."""
    run_a, run_b = _make_run(raw_conn, plan_revision), _make_run(raw_conn, plan_revision)
    first_run_first_call = feedback_service.emit_shown(
        raw_conn, plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
        run_id=run_a, version=1,
    )
    first_run_retry = feedback_service.emit_shown(
        raw_conn, plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
        run_id=run_a, version=1,
    )
    second_run_first_call = feedback_service.emit_shown(
        raw_conn, plan_id=plan_revision["plan_id"], revision_id=plan_revision["revision_id"],
        run_id=run_b, version=1,
    )
    assert (first_run_first_call, first_run_retry, second_run_first_call) == (True, False, True)
    count = raw_conn.execute(
        "SELECT count(*) FROM engine.feedback_event WHERE revision_id=%s AND event_type='recommendation_shown'",
        (plan_revision["revision_id"],),
    ).fetchone()[0]
    assert count == 2, "one row per distinct run_id, no duplicate for the retried run"
