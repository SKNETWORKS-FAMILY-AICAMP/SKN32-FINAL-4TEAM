"""P1 D1 — develop DB(`da79839` 정렬, domain_version_id) 아래에서 세션/조건 수용 사례 실측.

[ACTIVE DB CONTRACT](../docs/agent-tasks/baby/P1_sessions_conditions.md) D1:
"같은 브라우저 두 목록 접근, baby<->computer 전환 시 목록/버전 분리, exact=false 보존,
조건 수정 후 재조회, 게스트 교차 접근 거부를 develop DB fixture에서 확인한다.
PC 사양 업로드와 baby accepts_spec_file=false도 보존한다."

`tests/test_baby_session_http.py`(SS01-SS06)는 이미 domain_version_id 모델 위에서 통과하므로
그 사례를 반복하지 않는다. 이 파일은 D1이 명시한, 그 파일이 직접 다루지 않는 나머지 항목만
추가로 실측한다: domain_version_id 실제 분리(DB 행 대조), exact=false 칩 보존, PC 사양 파일
업로드, baby accepts_spec_file=false.

`DATABASE_URL`이 가리키는, develop 마이그레이션 체인(0000-0013)이 이미 적용된 일회용 DB가
필요하다 (docstring 실행 예시는 reports/P1.md 참조).
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.repo.plan_repo import PlanRepo

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set DATABASE_URL to a disposable migrated database (develop 0000-0013 chain)",
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


def _fields(state: dict) -> dict:
    return {f["key"]: f for f in state["fields"]}


def _domain_version_row(raw_conn, list_id: str) -> dict:
    row = raw_conn.execute(
        """SELECT dv.id AS domain_version_id, dv.version_no, dv.content_hash, d.code, d.status
           FROM planning.plan p
           JOIN planning.plan_revision r ON r.id = p.current_revision_id
           JOIN config.domain_version dv ON dv.id = r.domain_version_id
           JOIN config.domain d ON d.id = dv.domain_id
           WHERE p.id = %s""",
        (list_id,),
    ).fetchone()
    return {"domain_version_id": row[0], "version_no": row[1], "content_hash": row[2], "code": row[3], "status": row[4]}


# ── D1: baby<->computer 전환 시 목록/버전 분리 (실제 domain_version_id 행 대조) ──
def test_d1_category_switch_pins_distinct_domain_version_rows(client: TestClient, raw_conn):
    r = client.post("/session")
    list_id = r.json()["list_id"]

    # baby는 더 이상 스텁이 아니다 — db/seed.py가 status='active'로 심고
    # PlanRepo.published_domain_version이 실제로 active 버전만 선택한다(P1 review R1).
    resp = client.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "born"})
    assert resp.status_code == 200, resp.text
    baby_row = _domain_version_row(raw_conn, list_id)
    assert baby_row["code"] == "baby"
    assert baby_row["status"] == "active"
    assert baby_row["content_hash"], "실제 config.domain_version.content_hash 가 비어 있으면 안 된다"

    # 같은 목록에서 카테고리를 computer 로 바꾸면 실제 다른 domain_version 행으로 재결합된다.
    resp = client.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "build"})
    assert resp.status_code == 200, resp.text
    pc_row = _domain_version_row(raw_conn, list_id)
    assert pc_row["code"] == "computer"
    assert pc_row["status"] == "active"
    assert pc_row["domain_version_id"] != baby_row["domain_version_id"]


# ── D1: draft/disabled 도메인은 실행 규칙으로 선택되지 않는다 (P1 review R1) ──
def test_d1_published_domain_version_excludes_non_active_domains(raw_conn):
    code = f"p1_r1_probe_{uuid4().hex[:8]}"
    domain_id = raw_conn.execute(
        "INSERT INTO config.domain (code, name, status) VALUES (%s, %s, 'draft') RETURNING id",
        (code, "R1 probe"),
    ).fetchone()[0]
    raw_conn.execute(
        "INSERT INTO config.domain_version (domain_id, version_no, definition, attribute_schema, content_hash) "
        "VALUES (%s, 1, '{}'::jsonb, '{}'::jsonb, 'deadbeef')",
        (domain_id,),
    )
    try:
        repo = PlanRepo(raw_conn)
        assert repo.published_domain_version(code) is None, "draft 도메인은 실행 버전으로 선택되면 안 된다"
        raw_conn.execute("UPDATE config.domain SET status='disabled' WHERE id=%s", (domain_id,))
        assert repo.published_domain_version(code) is None, "disabled 도메인도 마찬가지다"
        raw_conn.execute("UPDATE config.domain SET status='active' WHERE id=%s", (domain_id,))
        assert repo.published_domain_version(code) is not None, "active로 바뀌면 선택 가능해야 한다"
    finally:
        raw_conn.execute("DELETE FROM config.domain_version WHERE domain_id=%s", (domain_id,))
        raw_conn.execute("DELETE FROM config.domain WHERE id=%s", (domain_id,))


# ── D1: 이미 고정된 draft revision은 같은 카테고리 재선택 시 최신 version으로 옮겨가지 않는다 (P1 review R1) ──
def test_d1_repeat_category_choice_keeps_pinned_domain_version(client: TestClient, raw_conn):
    list_id = client.post("/session").json()["list_id"]
    resp = client.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "born"})
    assert resp.status_code == 200, resp.text
    first = _domain_version_row(raw_conn, list_id)

    newer_id = raw_conn.execute(
        "INSERT INTO config.domain_version (domain_id, version_no, definition, attribute_schema, content_hash) "
        "SELECT domain_id, version_no+1, definition, attribute_schema, content_hash || '-newer-for-test' "
        "FROM config.domain_version WHERE id=%s RETURNING id",
        (first["domain_version_id"],),
    ).fetchone()[0]
    try:
        # Re-choosing the SAME category (e.g. a mode switch) must keep the version this
        # draft already pinned, not silently jump to the newest version_no that now exists.
        resp = client.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "prenatal"})
        assert resp.status_code == 200, resp.text
        second = _domain_version_row(raw_conn, list_id)
        assert second["domain_version_id"] == first["domain_version_id"]
    finally:
        raw_conn.execute("DELETE FROM config.domain_version WHERE id=%s", (newer_id,))


# ── D1: 같은 브라우저 두 목록(baby 하나, computer 하나) 동시 접근 ──
def test_d1_same_guest_two_lists_different_categories_both_reachable(client: TestClient, raw_conn):
    list_baby = client.post("/session").json()["list_id"]
    client.post(f"/session/{list_baby}/category", json={"category": "baby", "mode": "born"})

    list_pc = client.post("/session").json()["list_id"]
    client.post(f"/session/{list_pc}/category", json={"category": "computer", "mode": "build"})

    assert list_baby != list_pc
    assert client.get(f"/session/{list_baby}").status_code == 200
    assert client.get(f"/session/{list_pc}").status_code == 200

    baby_row = _domain_version_row(raw_conn, list_baby)
    pc_row = _domain_version_row(raw_conn, list_pc)
    assert baby_row["code"] == "baby"
    assert pc_row["code"] == "computer"
    assert baby_row["domain_version_id"] != pc_row["domain_version_id"]


# ── D1: exact=false 보존 (칩으로 고른 대표 개월수는 "assumed", 재조회 후에도 유지) ──
def test_d1_chip_selected_age_exact_false_survives_reload(client: TestClient):
    list_id = client.post("/session").json()["list_id"]
    client.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "born"})

    state = client.post(
        f"/session/{list_id}/answer",
        json={"question_id": "q_age", "selected": [5]},  # "4~6개월" 대표값
    ).json()
    field = _fields(state)["age_stage"]
    assert field["value"]["exact"] is False
    assert field["status"] == "assumed"

    reloaded = client.get(f"/session/{list_id}").json()
    field2 = _fields(reloaded)["age_stage"]
    assert field2["value"]["months"] == 5
    assert field2["value"]["exact"] is False
    assert field2["status"] == "assumed"


# ── D1: 조건 수정 후 재조회가 최신 값을 반영 ──
def test_d1_condition_edit_then_reload_reflects_latest(client: TestClient):
    list_id = client.post("/session").json()["list_id"]
    client.post(f"/session/{list_id}/category", json={"category": "baby", "mode": "born"})
    client.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": 200000})

    reloaded = client.get(f"/session/{list_id}").json()
    assert _fields(reloaded)["budget_max"]["value"] == 200000

    client.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": 250000})
    reloaded2 = client.get(f"/session/{list_id}").json()
    assert _fields(reloaded2)["budget_max"]["value"] == 250000


# ── D1: 게스트 교차 접근 거부 (develop DB fixture 위에서 재확인) ──
def test_d1_cross_guest_access_denied(client: TestClient):
    list_id = client.post("/session").json()["list_id"]
    other = TestClient(app)
    other.post("/session")
    assert other.get(f"/session/{list_id}").status_code == 404
    assert other.patch(f"/session/{list_id}/slot", json={"field": "budget_max", "value": 1}).status_code == 404


# ── D1: PC 사양 파일 업로드 보존 + baby accepts_spec_file=false ──
def test_d1_pc_spec_file_upload_and_baby_accepts_spec_file_false(client: TestClient, raw_conn):
    list_id = client.post("/session").json()["list_id"]
    client.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "upgrade"})

    state = client.get(f"/session/{list_id}").json()
    assert state["accepts_spec_file"] is True, "computer/upgrade 모드는 사양 파일을 받아야 한다"

    resp = client.post(
        f"/session/{list_id}/spec-file",
        json={"file_name": "my-pc.txt", "content": "CPU: i5-13600K\nRAM: 32GB\nGPU: RTX 4070"},
    )
    assert resp.status_code == 200, resp.text
    # computer.yaml 의 fields: 목록에는 current_specs 가 없어(자유 텍스트 저장용) ConditionState
    # 출력에 안 뜬다 — 실제 영속은 원시 조건 행으로 직접 확인한다.
    row = raw_conn.execute(
        """SELECT pc.value FROM planning.plan_condition pc
           JOIN planning.plan p ON p.current_revision_id = pc.revision_id
           WHERE p.id = %s AND pc.condition_key = 'current_specs' AND pc.status = 'active'""",
        (list_id,),
    ).fetchone()
    assert row is not None, "current_specs 조건 행이 저장되어야 한다"
    specs = row[0]["value"]
    assert specs["CPU"] == "i5-13600K"
    assert specs["GPU"] == "RTX 4070"

    # oversized (byte-wise, via multi-byte chars) file -> 413 file_too_large from the service's own
    # byte-length check, not a NameError/500. (SpecFileIn.content has its own char-count max_length,
    # so this uses multi-byte characters to exceed 1MB in bytes while staying under that char cap.)
    huge = "가" * 400_000  # 3 bytes/char in UTF-8 -> ~1.2MB, well under the 1,000,000-char field limit
    resp2 = client.post(f"/session/{list_id}/spec-file", json={"file_name": "huge.txt", "content": huge})
    assert resp2.status_code == 413
    assert resp2.json()["error"]["code"] == "file_too_large"

    # unsupported extension -> 422, not silently accepted
    resp3 = client.post(f"/session/{list_id}/spec-file", json={"file_name": "virus.exe", "content": "x"})
    assert resp3.status_code == 422

    # baby: accepts_spec_file must stay false, and the route must reject uploads for it too if attempted
    baby_list = client.post("/session").json()["list_id"]
    client.post(f"/session/{baby_list}/category", json={"category": "baby", "mode": "born"})
    baby_state = client.get(f"/session/{baby_list}").json()
    assert baby_state["accepts_spec_file"] is False

    # P1 review R3: the server must actually enforce this, not just display false —
    # a direct POST against a baby (or computer/build, non-upgrade) revision is rejected.
    baby_resp = client.post(
        f"/session/{baby_list}/spec-file", json={"file_name": "spec.txt", "content": "CPU: i5"},
    )
    assert baby_resp.status_code == 422, baby_resp.text
    assert raw_conn.execute(
        """SELECT count(*) FROM planning.plan_condition pc
           JOIN planning.plan p ON p.current_revision_id = pc.revision_id
           WHERE p.id = %s AND pc.condition_key IN ('current_specs', 'spec_file_name') AND pc.status = 'active'""",
        (baby_list,),
    ).fetchone()[0] == 0, "거절된 업로드는 조건 행을 남기면 안 된다"

    build_list = client.post("/session").json()["list_id"]
    client.post(f"/session/{build_list}/category", json={"category": "computer", "mode": "build"})
    build_resp = client.post(
        f"/session/{build_list}/spec-file", json={"file_name": "spec.txt", "content": "CPU: i5"},
    )
    assert build_resp.status_code == 422, build_resp.text

    # computer/build (non-upgrade) also does not advertise spec-file acceptance
    build_list = client.post("/session").json()["list_id"]
    client.post(f"/session/{build_list}/category", json={"category": "computer", "mode": "build"})
    build_state = client.get(f"/session/{build_list}").json()
    assert build_state["accepts_spec_file"] is False
