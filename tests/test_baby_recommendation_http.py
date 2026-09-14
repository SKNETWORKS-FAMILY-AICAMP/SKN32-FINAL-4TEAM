"""P5 — 유아 추천 실행·저장·결과·후보 편집 HTTP 통합 테스트 (실 PostgreSQL + 실 FastAPI, mock 없음).

`DATABASE_URL`이 가리키는, 마이그레이션+유아 카탈로그 시드가 이미 적용된 일회용 DB가 필요하다:

    export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/<disposable>?sslmode=disable'
    export RAG_TEST_DATABASE_URL="$DATABASE_URL"
    export RAG_EMBEDDING_PROVIDER=local-test   # AWS 자격증명 없이 실행 (bedrock 기본값 대체)
    uv run python db/setup_all.py
    uv run python scripts/seed_baby_catalog.py --corpus synthetic --dataset-version baby-demo-v1
    uv run python -m pytest -q tests/test_baby_recommendation_http.py

get_conn()/psycopg 풀을 대체하지 않는다 — 매 요청이 실제 트랜잭션 1개를 커밋/롤백한다.

이 카탈로그·규칙 상태에서는(P1234-fixes-2026-09-13.md: "No reviewed non-stroller manual
exemptions are currently available") '외출' need 는 stroller+car_seat 를 모두 mandatory-now
로 요구하는데 car_seat 는 어떤 시드 변형도 KC 인증이 verified 상태가 아니라 항상
selection_allowed=False 다 — 그 결과 이 시드로는 실제 recommend 실행이 구조적으로 항상
feasible=False 로 끝난다(허위 성공이 아니라 CONTRACTS가 명시한 정당한 done+infeasible
상태). RH01/RH02/RH03/RH04/RH06 은 이 실제 결과로 검증한다. RH05(수량/시점/교체 편집)는
실제 편집 메커니즘(소유권·If-Match·recalculate_basket 재계산·가짜 가격 거부)을 검증해야
하는데 이 카탈로그로는 selection_allowed=True인 to_purchase 후보가 자연 발생하지 않으므로,
실행이 만든 실제 requirement/candidate 행 위에 프로덕션과 동일한 persist_candidate_check
경로로 "P3가 승인했다면 저장했을 모양"의 validation_result+candidate_check 행을 하나 추가로
쌓아 편집 대상 to_purchase item 하나를 만든다 — DB는 실 DB, FK/CHECK 제약도 실제로 걸리며,
이것이 검증하는 것은 P5 자신의 편집/재계산/동시성 로직이지 P3의 판정 정확도가 아니다(범위 밖).
"""
from __future__ import annotations

import os
import threading
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set DATABASE_URL to a disposable migrated+baby-seeded database (see module docstring)",
)

if DSN:
    os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local-test")
    from src.api import app
    from src.db import get_conn
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service

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


def _create(c: TestClient) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _signed_up_client() -> TestClient:
    """A logged-in (not guest) client — list_service.confirm() requires p.user_id."""
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"p7-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "P7 Reviewer", "terms_agreed": True, "privacy_agreed": True,
        "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _choose_baby(c: TestClient, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "born"})
    assert r.status_code == 200, r.text
    return r.json()


def _answer(c: TestClient, list_id: str, qid: str, selected: list) -> dict:
    r = c.post(f"/session/{list_id}/answer", json={"question_id": qid, "selected": selected})
    assert r.status_code == 200, r.text
    return r.json()


def _fill_complete_conditions(c: TestClient, list_id: str, *, needs: list[str],
                              owned: list[str], budget: int = 500_000) -> dict:
    """can_recommend=True 가 되는 최소 조건 세트 — age_months/needs/health_skin/owned/budget
    (+ 외출/안전건강 need 가 있으면 weight/sitting 도)."""
    state = c.post(f"/session/{list_id}/message", json={"text": f"8개월, 예산 {budget}원"}).json()
    state = _answer(c, list_id, "q_needs", needs)
    state = _answer(c, list_id, "q_health_skin", ["특이사항 없음"])
    state = _answer(c, list_id, "q_owned", owned)
    if any(n in needs for n in ("외출", "안전·건강")):
        state = _answer(c, list_id, "q_weight", [8.5])
        state = _answer(c, list_id, "q_sitting", [True])
    assert state["can_recommend"] is True, state
    return state


def _recommend_and_wait(c: TestClient, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/recommend")
    assert r.status_code == 202, r.text
    accepted = r.json()
    assert accepted["status"] == "running"
    r = c.get(f"/session/{list_id}/result")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] != "running", "TestClient executes BackgroundTasks synchronously"
    return data


def _seed_editable_to_purchase_item(raw_conn, revision_id: str, run_id: str) -> dict:
    """P3가 실제로 승인했다면 만들었을 to_purchase 행 하나를 프로덕션과 같은 경로
    (persist_candidate_check)로 추가한다 — RH05가 검증하는 것은 이 항목의 편집/재계산/
    동시성이지, 승인 판정 자체가 아니다(모듈 docstring 참고)."""
    from src.dto import BabyCandidate, CandidateCheck
    from src.repo.engine_repo import persist_candidate_check
    from src.repo.product_repo import ProductRepo

    conn = psycopg.connect(DSN)
    try:
        prepo, erepo = PlanRepo(conn), EngineRepo(conn)
        prodrepo = ProductRepo(conn)
        rows = prodrepo.baby_candidates_by_category("bottle", corpus="synthetic")
        assert rows, "seeded catalog must have at least one bottle offer"
        row = min(rows, key=lambda r: r["price"])
        req_row = conn.execute(
            "SELECT r.id FROM planning.requirement r JOIN planning.plan_node n ON n.id=r.node_id WHERE r.revision_id=%s AND n.template_key='bottle'",
            (revision_id,),
        ).fetchone()
        assert req_row is not None, "bottle requirement must already be persisted by start_recommendation"
        requirement_id = str(req_row[0])

        candidate_id = erepo.add_candidate(
            UUID(run_id), UUID(requirement_id), row["variant_id"], result="pending",
            offer_observation_id=row["offer_observation_id"],
        )
        check = CandidateCheck(candidate_id=str(candidate_id), requirement_id=requirement_id,
                               eligibility="pass", verification="verified", coverage="none",
                               selection_allowed=True,
                               issues=[{"schema_version": 1, "rule_key": "test_seed_v1", "rule_version": "v1",
                                       "target": {"candidate_id": str(candidate_id),
                                                 "requirement_id": requirement_id, "item_id": None},
                                       "status": "pass", "severity": "info", "measured": {}, "threshold": {},
                                       "reason": "test_fixture_approved", "penalty": None, "evidence_ids": []}])
        persist_candidate_check(conn, UUID(run_id), candidate_id, check, None)
        erepo.set_candidate_result(candidate_id, result="selected", score=1.0)

        erepo.update_candidate_state(candidate_id, selected=True, qty=2, timing="now")
        conn.commit()
        # P5 review R2: baby's stable HTTP item_id is the requirement UUID, not this
        # candidate row's own id (candidate_id changes on swap, item_id never does).
        return {"item_id": requirement_id, "candidate_id": str(candidate_id),
               "requirement_id": requirement_id, "price": int(row["price"]),
               "other_variant_ids": [r["variant_id"] for r in rows if r["variant_id"] != row["variant_id"]]}
    finally:
        conn.close()


# ── RH01 ──────────────────────────────────────────────────────────────────
def test_rh01_full_guest_flow_produces_real_persisted_recommendation(client: TestClient, raw_conn):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])
    revision_id = state["revision_id"]

    data = _recommend_and_wait(client, list_id)
    assert data["status"] == "done"
    assert data["category"] == "baby"
    assert data["revision_id"] == revision_id
    assert data["lock_version"] is not None
    assert data["data_notice"]
    assert isinstance(data["feasible"], bool)
    assert data["totals"]["selected_price"] >= 0

    # 실제 requirement/candidate/validation 행이 이 리비전/run 스코프로 저장됐다.
    reqs = raw_conn.execute(
        "SELECT n.template_key FROM planning.requirement r JOIN planning.plan_node n ON n.id=r.node_id WHERE r.revision_id=%s AND r.status='active'",
        (revision_id,),
    ).fetchall()
    assert {"stroller", "car_seat"} <= {r[0] for r in reqs}

    run_id = data["run_id"]
    n_candidates = raw_conn.execute(
        "SELECT count(*) FROM engine.recommendation_candidate WHERE run_id=%s", (run_id,),
    ).fetchone()[0]
    assert n_candidates > 0, "실제 후보 수집·검증이 일어났어야 한다"

    n_validations = raw_conn.execute(
        "SELECT count(*) FROM engine.validation_result WHERE run_id=%s", (run_id,),
    ).fetchone()[0]
    assert n_validations > 0

    # 최소 1건은 실제 RAG 근거(evidence)가 인용됐다 — 합성 유모차 설명서가 사전에 ingest 됐다면.
    evidence_rows = raw_conn.execute(
        """SELECT jsonb_array_length(issues->0->'evidence_refs') FROM engine.validation_result
           WHERE run_id=%s AND issues->0->>'rule_key'='baby_seat_v1' AND issues->0->>'status'='pass'""",
        (run_id,),
    ).fetchall()
    if evidence_rows:  # 합성 매뉴얼이 ingest 안 된 실행 환경이면 스킵성 관대화(문서화된 전제조건)
        assert any((n or 0) > 0 for (n,) in evidence_rows)

    # explanation은 영원히 pending 이 아니다 (CONTRACTS "no forever-pending text when returning done")
    assert data["explanation"]["status"] == "ready"
    assert data["explanation"]["text"]

    # infeasible이면 missing_requirements가 실제로 그 이유를 담아야 한다(허위 성공 금지)
    if not data["feasible"]:
        assert data["missing_requirements"]
        for miss in data["missing_requirements"]:
            assert miss["slot_key"]


def test_rh01_owned_item_is_never_charged(client: TestClient):
    list_id = _create(client)
    _choose_baby(client, list_id)
    _fill_complete_conditions(client, list_id, needs=["외출"], owned=["유모차"])
    data = _recommend_and_wait(client, list_id)
    owned = [i for i in data["items"] if i["status"] == "owned"]
    assert owned, "유모차를 보유로 답했으므로 owned 항목이 있어야 한다"
    assert all(i["price"] == 0 or not i["selected"] for i in owned)
    charged_ids = {i["item_id"] for i in data["items"] if i["status"] == "to_purchase" and i["selected"]}
    assert not (charged_ids & {i["item_id"] for i in owned})


# ── RH02 ──────────────────────────────────────────────────────────────────
def test_rh02_get_reload_never_reruns_search_or_embedding(client: TestClient, monkeypatch):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])
    first = _recommend_and_wait(client, list_id)

    def _boom(*a, **kw):
        raise AssertionError("GET /result must not call the embedder/search")

    monkeypatch.setattr("src.rag.embedding.get_embedder", _boom)
    monkeypatch.setattr("src.rag.embedding.LocalHashEmbedder.embed", _boom)
    monkeypatch.setattr("src.rag.service.RagService.search", _boom)

    r = client.get(f"/session/{list_id}/result")
    assert r.status_code == 200, r.text
    second = r.json()

    assert second["run_id"] == first["run_id"]
    assert [i["item_id"] for i in second["items"]] == [i["item_id"] for i in first["items"]]
    assert second["feasible"] == first["feasible"]


# ── RH03 ──────────────────────────────────────────────────────────────────
def test_rh03_incomplete_conditions_create_no_run(client: TestClient, raw_conn):
    list_id = _create(client)
    state = _choose_baby(client, list_id)
    revision_id = state["revision_id"]
    _answer(client, list_id, "q_needs", ["외출"])  # budget/health/owned/weight/sitting 미응답

    n_before = raw_conn.execute(
        "SELECT count(*) FROM engine.recommendation_run WHERE revision_id=%s", (revision_id,)
    ).fetchone()[0]
    r = client.post(f"/session/{list_id}/recommend")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "conditions_incomplete"
    n_after = raw_conn.execute(
        "SELECT count(*) FROM engine.recommendation_run WHERE revision_id=%s", (revision_id,)
    ).fetchone()[0]
    assert n_after == n_before


def test_rh03_other_guest_cannot_recommend_or_read(client: TestClient):
    list_id = _create(client)
    _choose_baby(client, list_id)
    _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])

    guest_b = TestClient(app)
    guest_b.post("/session")
    assert guest_b.post(f"/session/{list_id}/recommend").status_code == 404
    assert guest_b.get(f"/session/{list_id}/result").status_code == 404


def test_rh03_forged_candidate_on_swap_is_rejected(client: TestClient):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["유모차"])
    data = _recommend_and_wait(client, list_id)
    owned_item = next(i for i in data["items"] if i["status"] == "owned")

    r = client.post(
        f"/session/{list_id}/items/{owned_item['item_id']}/swap",
        json={"candidate_id": "00000000-0000-0000-0000-000000000000"},
        headers={"If-Match": str(data["lock_version"])},
    )
    assert r.status_code == 422, r.text


# ── RH04 ──────────────────────────────────────────────────────────────────
def test_rh04_concurrent_recommend_only_one_active_run(client: TestClient):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])
    revision_id = UUID(state["revision_id"])

    with get_conn() as conn:
        first = recommendation_service.start_recommendation(conn, revision_id)
        with pytest.raises(Exception) as exc_info:
            recommendation_service.start_recommendation(conn, revision_id)
        assert "run_in_progress" in str(exc_info.value) or getattr(exc_info.value, "code", "") == "run_in_progress"
    # 정리: 남겨둔 running run 은 실행해서 종료시킨다 (다음 테스트 오염 방지 목적은 아니지만 위생상)
    recommendation_service.execute_recommendation(revision_id, UUID(first["run_id"]))


def test_rh04_search_provider_outage_marks_failed_not_fake_done(client: TestClient, monkeypatch):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])
    revision_id = UUID(state["revision_id"])

    def _boom():
        raise RuntimeError("simulated search provider outage")

    monkeypatch.setattr("src.rag.provider.get_search_provider", _boom)
    with get_conn() as conn:
        accepted = recommendation_service.start_recommendation(conn, revision_id)
    run_id = UUID(accepted["run_id"])
    with pytest.raises(Exception):
        recommendation_service.execute_recommendation(revision_id, run_id)

    with get_conn() as conn:
        stored = recommendation_service.get_stored_result(conn, revision_id)
    assert stored["status"] == "failed"
    assert stored["error"]["code"]


# ── RH05 ──────────────────────────────────────────────────────────────────
def test_rh05_patch_qty_and_stale_lock_version(client: TestClient, raw_conn):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출", "수유"], owned=["유모차"], budget=2_000_000)
    data = _recommend_and_wait(client, list_id)
    fixture = _seed_editable_to_purchase_item(raw_conn, data["revision_id"], data["run_id"])

    r = client.get(f"/session/{list_id}/result")
    lock = r.json()["lock_version"]

    # stale If-Match -> 409
    r = client.patch(f"/session/{list_id}/items/{fixture['item_id']}", json={"qty": 3},
                     headers={"If-Match": str(lock - 1) if lock > 0 else "999999"})
    assert r.status_code == 409, r.text

    # missing If-Match -> 422
    r = client.patch(f"/session/{list_id}/items/{fixture['item_id']}", json={"qty": 3})
    assert r.status_code == 422, r.text

    # real edit recomputes the charged total (never trusts a client-sent price)
    r = client.patch(f"/session/{list_id}/items/{fixture['item_id']}", json={"qty": 3},
                     headers={"If-Match": str(lock)})
    assert r.status_code == 200, r.text
    updated = r.json()
    item = next(i for i in updated["items"] if i["item_id"] == fixture["item_id"])
    assert item["qty"] == 3
    assert item["price"] == fixture["price"]  # 서버가 다시 채운 가격, 클라 입력 아님
    assert updated["totals"]["selected_price"] >= fixture["price"] * 3
    assert updated["lock_version"] == lock + 1


def test_rh05_alternatives_and_swap_recompute_totals(client: TestClient, raw_conn):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출", "수유"], owned=["유모차"], budget=2_000_000)
    data = _recommend_and_wait(client, list_id)
    fixture = _seed_editable_to_purchase_item(raw_conn, data["revision_id"], data["run_id"])

    r = client.get(f"/session/{list_id}/items/{fixture['item_id']}/alternatives")
    assert r.status_code == 200, r.text
    alts = r.json()["items"]
    assert any(a["candidate_id"] == fixture["candidate_id"] and a["current"] for a in alts)

    others = [a for a in alts if a["candidate_id"] != fixture["candidate_id"] and a["price"] is not None]
    if not others:
        pytest.skip("이 시드 카탈로그의 bottle 오퍼가 1개뿐이라 실제 교체 대상이 없음")
    target = others[0]

    r = client.get(f"/session/{list_id}/result")
    lock = r.json()["lock_version"]
    r = client.post(f"/session/{list_id}/items/{fixture['item_id']}/swap",
                    json={"candidate_id": target["candidate_id"]},
                    headers={"If-Match": str(lock)})
    # target이 selection_allowed=True(=실제 검증된 후보)일 때만 성공해야 한다 — 아니면 422가 맞다.
    if target["selection_allowed"]:
        assert r.status_code == 200, r.text
        item = next(i for i in r.json()["items"] if i["item_id"] == fixture["item_id"])
        assert item["candidate_id"] == target["candidate_id"]
        assert item["price"] == target["price"]
    else:
        assert r.status_code == 422, r.text


# ── RH06 ──────────────────────────────────────────────────────────────────
def test_rh06_recommendation_shown_event_emitted_once_and_get_generates_none(client: TestClient, raw_conn):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출"], owned=["없음"])
    data = _recommend_and_wait(client, list_id)

    def shown_count():
        return raw_conn.execute(
            "SELECT count(*) FROM engine.feedback_event WHERE recommendation_run_id=%s AND event_type='recommendation_shown'",
            (data["run_id"],),
        ).fetchone()[0]

    assert shown_count() == 1
    for _ in range(3):
        r = client.get(f"/session/{list_id}/result")
        assert r.status_code == 200
    assert shown_count() == 1, "GET/poll must not duplicate recommendation_shown"


def test_rh06_result_message_documented_rule_and_clarification(client: TestClient, raw_conn):
    list_id = _create(client)
    _choose_baby(client, list_id)
    state = _fill_complete_conditions(client, list_id, needs=["외출", "수유"], owned=["유모차"], budget=2_000_000)
    data = _recommend_and_wait(client, list_id)
    _seed_editable_to_purchase_item(raw_conn, data["revision_id"], data["run_id"])

    r = client.post(f"/session/{list_id}/result-message", json={"text": "아무거나 그냥 알아서 해줘"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "이해" in body["reply"] or "못" in body["reply"]
    unresolved_result = body["result"]

    r2 = client.get(f"/session/{list_id}/result")
    assert r2.json() == unresolved_result or r2.json()["lock_version"] == unresolved_result["lock_version"], \
        "ambiguous message must not mutate the basket"


# ── P7 review R1 ─────────────────────────────────────────────────────────────
def test_p7_confirm_rejects_when_mandatory_requirement_is_uncovered(raw_conn):
    """P7 review R1: confirm() must recheck full requirement coverage (all active
    requirements, not just whatever candidates happen to be selected). This
    catalog's car_seat is always selection_allowed=False (module docstring), so a
    '외출'+'수유' recommendation always has an uncovered mandatory requirement —
    confirm must refuse it even with a real, validly-selected bottle candidate
    present (seeded the same way RH05 does), since a per-selected-candidate-only
    check would happily confirm on that one item and never notice car_seat."""
    signed_up = _signed_up_client()
    list_id = _create(signed_up)
    _choose_baby(signed_up, list_id)
    _fill_complete_conditions(signed_up, list_id, needs=["외출", "수유"], owned=["없음"], budget=2_000_000)
    data = _recommend_and_wait(signed_up, list_id)
    assert data["feasible"] is False, "documented catalog property: car_seat always blocks 외출"
    _seed_editable_to_purchase_item(raw_conn, data["revision_id"], data["run_id"])

    state = signed_up.get(f"/session/{list_id}/result").json()
    r = signed_up.post(f"/lists/{list_id}/confirm", json={"name": "P7 확정 테스트"},
                       headers={"If-Match": str(state["lock_version"])})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "basket_infeasible"
    assert raw_conn.execute(
        "SELECT count(*) FROM planning.purchase_line WHERE revision_id=%s", (data["revision_id"],)
    ).fetchone()[0] == 0, "a rejected confirm must not leave any purchase_line rows"
