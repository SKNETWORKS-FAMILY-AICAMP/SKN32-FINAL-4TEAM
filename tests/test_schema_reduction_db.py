"""P0 대체 인수조건 SR01–SR08 의 실 DB 행동 테스트.

tests/test_schema_reduction.py 는 마이그레이션 파일의 문자열만 본다. 작업지시서가
"source-string assertions alone are insufficient" 라고 못박은 게이트들을 여기서
실제 PostgreSQL 에 대고 검증한다. 각 테스트는 자기 행을 롤백하며, SR03 리허설만
자기가 만든 이름의 DB 를 만들고 지운다(다른 DB 는 건드리지 않는다).

    RAG_TEST_DATABASE_URL=<마이그레이션 적용된 일회용 DB> uv run python -m pytest -q tests/test_schema_reduction_db.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import importlib.util

import psycopg
import pytest
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts.rag_manual import create_test_run
from src.categories import available_categories
from src.rag.contracts import SearchRequest
from src.rag.embedding import LocalHashEmbedder
from src.rag.ingestion import ingest_manual, read_manual
from src.rag.service import RagService
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.repo.rag_repo import RagRepo

ROOT = Path(__file__).resolve().parents[1]


def _seed_module():
    """db/ 는 패키지가 아니므로 파일 경로로 직접 적재한다."""
    spec = importlib.util.spec_from_file_location("p0_seed", ROOT / "db/seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"
DSN = os.getenv("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated pgvector database"
)

# SR01 목표: 도메인 테이블 35개 (+ 러너 기록용 _migrations.schema_migrations 1개).
EXPECTED_DOMAIN_TABLES = 35
REMOVED = [
    "config.domain_version", "config.schema_reduction_mapping", "identity.user_preference",
    "catalog.product_category_membership", "planning.plan_node", "planning.owned_item",
    "planning.purchase_line", "planning.fulfillment_allocation", "assets.material_revision",
    "assets.material_applicability", "evidence.source", "engine.candidate_evidence",
    "engine.validation_target", "engine.validation_evidence", "community.review_revision",
    "community.pc_build", "community.pc_build_version", "community.pc_build_component",
]
REMOVED_SCHEMAS = ["notification", "dataset", "shared"]


@pytest.fixture
def conn():
    c = psycopg.connect(DSN, prepare_threshold=None, row_factory=dict_row)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _revision(conn, code: str = "computer") -> dict:
    """도메인/대화/계획/리비전/요구 1세트. 트랜잭션 롤백으로 정리된다."""
    repo = PlanRepo(conn)
    conversation = conn.execute(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        ("sr-test-" + uuid.uuid4().hex,),
    ).fetchone()["id"]
    plan = repo.create_plan(conversation, "SR 테스트", None)
    domain = repo.published_domain(code)
    revision = repo.new_revision(plan, domain["id"], "SR 테스트")
    repo.set_current_revision(plan, revision)
    requirement = repo.ensure_requirement(revision, "CPU", {"slot": "CPU"}, position=0)
    return {"plan": plan, "revision": revision, "requirement": requirement, "domain": domain}


def _run(conn, revision_id) -> str:
    return EngineRepo(conn).start_run(
        revision_id, PlanRepo(conn).get_revision(revision_id)["domain_id"],
        input_snapshot={"sr": "test"}, input_hash="0" * 64,
        draft_lock_version=0, engine_versions={"sr": "test"},
    )


def _variant(conn):
    return conn.execute("SELECT id FROM catalog.product_variant LIMIT 1").fetchone()["id"]


# ══════════════════════ SR01 — 실제 스키마 모양 ══════════════════════
def test_sr01_reduced_schema_has_target_table_set(conn):
    rows = conn.execute(
        """SELECT table_schema || '.' || table_name AS name FROM information_schema.tables
           WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
             AND table_type = 'BASE TABLE' ORDER BY 1"""
    ).fetchall()
    names = [r["name"] for r in rows]
    domain_tables = [n for n in names if not n.startswith("_migrations.")]
    assert len(domain_tables) == EXPECTED_DOMAIN_TABLES, domain_tables
    assert set(REMOVED).isdisjoint(names)
    schemas = {r["nspname"] for r in conn.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%%'").fetchall()}
    assert schemas.isdisjoint(REMOVED_SCHEMAS)
    # shared.set_updated_at 을 지웠으므로 남은 트리거는 전부 app 네임스페이스를 봐야 한다.
    assert conn.execute(
        """SELECT count(*) AS n FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
           JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE t.tgname = 'set_updated_at' AND n.nspname <> 'app'"""
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname='set_updated_at' AND NOT tgisinternal"
    ).fetchone()["n"] > 0


def test_sr01_no_pending_migration(conn):
    applied = {r["version"] for r in conn.execute(
        "SELECT version FROM _migrations.schema_migrations").fetchall()}
    on_disk = {p.stem for p in (ROOT / "db/migrations").glob("*.sql")}
    assert on_disk - applied == set(), "미적용 마이그레이션이 남아 있음"


# ══════════════════════ SR02 — 재실행 멱등 ══════════════════════
def test_sr02_reseeding_creates_no_duplicate_identity(conn):
    upsert_domain = _seed_module().upsert_domain

    before = conn.execute(
        "SELECT code, content_hash, current_version_no FROM config.domain ORDER BY code").fetchall()
    with conn.cursor(row_factory=dict_row) as cur:
        for code in available_categories():
            definition = yaml.safe_load(
                (ROOT / f"config/categories/{code}.yaml").read_text(encoding="utf-8"))
            assert upsert_domain(cur, code, f"{code}", "active", definition) == "unchanged"
    after = conn.execute(
        "SELECT code, content_hash, current_version_no FROM config.domain ORDER BY code").fetchall()
    assert before == after
    assert conn.execute(
        "SELECT count(*) AS n FROM (SELECT code FROM config.domain GROUP BY code HAVING count(*) > 1) d"
    ).fetchone()["n"] == 0
    conn.rollback()


def test_sr02_seed_cannot_demote_a_published_domain(conn):
    """미게시 정의가 게시본을 밀어내지 못한다 (SR08 의 seed 측 게이트)."""
    seed = _seed_module()
    PublishedDomainDemotion, upsert_domain = seed.PublishedDomainDemotion, seed.upsert_domain

    definition = yaml.safe_load(
        (ROOT / "config/categories/computer.yaml").read_text(encoding="utf-8"))
    with conn.cursor(row_factory=dict_row) as cur:
        with pytest.raises(PublishedDomainDemotion):
            upsert_domain(cur, "computer", "컴퓨터", "draft", definition)
        with pytest.raises(PublishedDomainDemotion):
            upsert_domain(cur, "computer", "컴퓨터", "active", {})
    assert conn.execute(
        "SELECT status FROM config.domain WHERE code='computer'").fetchone()["status"] == "active"
    conn.rollback()


def test_sr02_published_domain_must_carry_a_real_definition(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO config.domain(code,name,status,current_version_no,definition,
                 attribute_schema,content_hash) VALUES ('sr-empty','x','active',1,'{}','{}',%s)""",
            ("0" * 64,))
    conn.rollback()


# ══════════════════════ SR03 — 신규 설치 전제조건 ══════════════════════
def _admin_dsn(dbname: str) -> str:
    base, _, _ = DSN.rpartition("/")
    tail = DSN.rsplit("/", 1)[1]
    query = "?" + tail.split("?", 1)[1] if "?" in tail else ""
    return f"{base}/{dbname}{query}"


def test_sr03_destructive_migration_rejects_a_populated_legacy_target(tmp_path):
    """0012 는 0010 백필을 건너뛴 대상에 파괴적 DDL 을 적용하지 않는다.

    이 테스트만 DB 를 만든다 — 이름에 uuid 가 들어간 자기 소유 DB 하나뿐이고,
    끝나면 그것만 지운다. RAG_TEST_DATABASE_URL 과 같은 서버(이미 일회용으로 선언된 곳).
    """
    name = "p0_sr03_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(_admin_dsn("postgres"), autocommit=True)
    migrations = ROOT / "db/migrations"
    # 0011 이후 전부를 잠시 치워 0000–0011 상태를 만든다(0013 은 0012 가 만든 컬럼에 의존).
    after_0011 = sorted(p for p in migrations.glob("*.sql") if p.stem > "0011_")
    destructive = migrations / "0012_schema_reduction_destructive.sql"
    assert destructive in after_0011
    parked = {f: tmp_path / f.name for f in after_0011}

    def table_count(c):
        return c.execute(
            """SELECT count(*) FROM information_schema.tables WHERE table_schema
               NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE'"""
        ).fetchone()[0]

    try:
        admin.execute(f'CREATE DATABASE "{name}"')
        env = {**os.environ, "DATABASE_URL": _admin_dsn(name)}

        for src, dst in parked.items():
            src.rename(dst)
        first = subprocess.run([sys.executable, "db/migrate.py", "up"], cwd=ROOT, env=env,
                               capture_output=True, text=True)
        assert first.returncode == 0, first.stdout + first.stderr

        # 0010 백필을 타지 않은 레거시 행을 심는다.
        with psycopg.connect(_admin_dsn(name)) as c:
            c.execute("INSERT INTO config.domain(code,name,status) VALUES "
                      "('legacy-unmigrated','백필 누락 행','active')")
            c.commit()
            before = table_count(c)

        # 0012 만 되돌리고 적용 시도 — 실패하고 스키마는 그대로여야 한다.
        parked.pop(destructive).rename(destructive)
        result = subprocess.run([sys.executable, "db/migrate.py", "up"], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert "fresh_install_precondition_failed" in (result.stdout + result.stderr)

        with psycopg.connect(_admin_dsn(name)) as c:
            after = table_count(c)
            applied = {r[0] for r in c.execute(
                "SELECT version FROM _migrations.schema_migrations").fetchall()}
        assert after == before, "거부된 마이그레이션이 테이블을 건드렸다"
        assert "0012_schema_reduction_destructive" not in applied
    finally:
        for src, dst in parked.items():
            if dst.exists():
                dst.rename(src)
        if not destructive.exists() and (tmp_path / destructive.name).exists():
            (tmp_path / destructive.name).rename(destructive)
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


# ══════════════════════ SR07 — 실제 신규 행의 도메인 스냅샷 ══════════════════════
@pytest.mark.parametrize("code", ["baby", "computer"])
def test_sr07_revision_snapshots_the_chosen_category_rules(conn, code):
    """카테고리를 고르면 그 카테고리의 게시 규칙이 리비전에 얼어붙는다."""
    from src.auth.deps import Principal
    from src.services import session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    list_id = uuid.UUID(created["list_id"])
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    session_service.choose_category(conn, list_id, code, None, principal)

    row = conn.execute(
        """SELECT d.code, r.domain_snapshot AS snap, d.content_hash, d.definition
           FROM planning.plan_revision r JOIN config.domain d ON d.id = r.domain_id
           JOIN planning.plan p ON p.current_revision_id = r.id WHERE p.id = %s""",
        (list_id,)).fetchone()
    assert row["code"] == code
    assert row["snap"]["content_hash"] == row["content_hash"]
    assert row["snap"]["definition"] == row["definition"]
    assert row["snap"]["definition"] != {}
    assert row["snap"]["definition"]["category"] == code
    conn.rollback()


def test_sr07_run_snapshot_matches_the_revision_category(conn):
    fix = _revision(conn, "computer")
    run_id = _run(conn, fix["revision"])
    snap = conn.execute(
        "SELECT domain_snapshot AS s FROM engine.recommendation_run WHERE id=%s",
        (run_id,)).fetchone()["s"]
    assert snap["content_hash"] == fix["domain"]["content_hash"]
    assert snap["definition"]["category"] == "computer"
    conn.rollback()


def test_sr07_runtime_never_binds_a_non_category_domain(conn):
    """RAG 평가용 도메인처럼 런타임 카테고리가 아닌 행은 세션이 고를 수 없다."""
    from src.auth.deps import Principal
    from src.services import session_service

    create_test_run(conn)  # rag-evaluation-baby 도메인을 만든다
    assert conn.execute(
        "SELECT status FROM config.domain WHERE code='rag-evaluation-baby'"
    ).fetchone()["status"] == "disabled"
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    code = conn.execute(
        """SELECT d.code FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id
           JOIN config.domain d ON d.id=r.domain_id WHERE p.id=%s""",
        (uuid.UUID(created["list_id"]),)).fetchone()["code"]
    assert code in available_categories()
    conn.rollback()


def test_sr07_requirement_carries_slot_key_and_position(conn):
    fix = _revision(conn, "computer")
    row = conn.execute(
        "SELECT slot_key, position, revision_id FROM planning.requirement WHERE id=%s",
        (fix["requirement"],)).fetchone()
    assert row["slot_key"] == "CPU" and row["revision_id"] == fix["revision"]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE planning.requirement SET slot_key='   ' WHERE id=%s",
                     (fix["requirement"],))
    conn.rollback()


# ══════════════════════ SR08 — JSON 계약·스코프·불변 ══════════════════════
def _insert_candidate(conn, run_id, requirement_id, refs=None):
    return conn.execute(
        """INSERT INTO engine.recommendation_candidate(run_id, requirement_id, variant_id, result,
             evidence_refs) VALUES (%s,%s,%s,'passed',COALESCE(%s, '{"schema_version":1,"refs":[]}'::jsonb))
           RETURNING id""",
        (run_id, requirement_id, _variant(conn), refs)).fetchone()["id"]


FULL_REF = {
    "evidence_id": str(uuid.uuid4()), "claim_key": "manual_applicability",
    "material_id": str(uuid.uuid4()), "material_version": "v1",
    "file_sha256": "a" * 64, "locator": {"section_code": "S07"},
}


@pytest.mark.parametrize("refs", [
    [{"junk": 1}],                                             # 필수 키 전무
    [{k: v for k, v in FULL_REF.items() if k != "file_sha256"}],  # 키 누락
    [{**FULL_REF, "material_version": ""}],                    # 빈 값
    [{**FULL_REF, "locator": "S07"}],                          # locator 타입 오류
    [FULL_REF, FULL_REF],                                      # (evidence_id, claim_key) 중복
])
def test_sr08_malformed_or_duplicated_evidence_refs_are_rejected(conn, refs):
    fix = _revision(conn)
    run_id = _run(conn, fix["revision"])
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_candidate(conn, run_id, fix["requirement"],
                          Jsonb({"schema_version": 1, "refs": refs}))
    conn.rollback()


@pytest.mark.parametrize("issues", [
    [{"schema_version": 2}],
    [{"schema_version": 1, "rule_key": "", "rule_version": "v1", "target": {}, "status": "pass"}],
    [{"schema_version": 1, "rule_key": "r", "rule_version": "v1", "target": {}, "status": "maybe"}],
    [{"schema_version": 1, "rule_key": "r", "rule_version": "v1", "target": "candidate", "status": "pass"}],
    [{"schema_version": 1, "rule_key": "r", "rule_version": "v1", "target": {}, "status": "pass",
      "evidence_refs": [{"evidence_id": "e"}]}],
])
def test_sr08_malformed_validation_issues_are_rejected(conn, issues):
    fix = _revision(conn)
    run_id = _run(conn, fix["revision"])
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO engine.validation_result(run_id,rule_key,rule_version,executor_version,
                 status,severity,measured_values,threshold,message,checked_at,issues)
               VALUES (%s,'r','v1','x','pass','critical','{}','{}','m',now(),%s)""",
            (run_id, Jsonb(issues)))
    conn.rollback()


def test_sr08_candidate_cannot_reference_another_revisions_requirement(conn):
    mine, other = _revision(conn, "computer"), _revision(conn, "computer")
    run_id = _run(conn, mine["revision"])
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_candidate(conn, run_id, other["requirement"])
    conn.rollback()


def test_sr08_candidate_revision_is_derived_from_its_run(conn):
    fix = _revision(conn, "computer")
    run_id = _run(conn, fix["revision"])
    candidate = _insert_candidate(conn, run_id, fix["requirement"])
    assert conn.execute(
        "SELECT revision_id FROM engine.recommendation_candidate WHERE id=%s",
        (candidate,)).fetchone()["revision_id"] == fix["revision"]
    # 애플리케이션이 직접 다른 리비전으로 바꿔치기할 수 없다.
    other = _revision(conn, "computer")
    conn.execute("UPDATE engine.recommendation_candidate SET revision_id=%s WHERE id=%s",
                 (other["revision"], candidate))
    assert conn.execute(
        "SELECT revision_id FROM engine.recommendation_candidate WHERE id=%s",
        (candidate,)).fetchone()["revision_id"] == fix["revision"]
    conn.rollback()


def test_sr08_domain_snapshot_survives_a_later_rule_change(conn):
    fix = _revision(conn, "computer")
    run_id = _run(conn, fix["revision"])
    before = conn.execute("SELECT domain_snapshot AS s FROM planning.plan_revision WHERE id=%s",
                          (fix["revision"],)).fetchone()["s"]
    conn.execute(
        """UPDATE config.domain SET definition = definition || '{"sr_changed": true}'::jsonb,
             content_hash = %s WHERE id = %s""",
        (hashlib.sha256(b"changed").hexdigest(), fix["domain"]["id"]))
    after = conn.execute("SELECT domain_snapshot AS s FROM planning.plan_revision WHERE id=%s",
                         (fix["revision"],)).fetchone()["s"]
    run_after = conn.execute("SELECT domain_snapshot AS s FROM engine.recommendation_run WHERE id=%s",
                             (run_id,)).fetchone()["s"]
    assert after == before and "sr_changed" not in after["definition"]
    assert "sr_changed" not in run_after["definition"]
    # 직접 덮어쓰기도 트리거가 막는다.
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE planning.plan_revision SET domain_snapshot='{}' WHERE id=%s",
                     (fix["revision"],))
    conn.rollback()


def test_sr08_empty_domain_snapshot_cannot_be_written(conn):
    fix = _revision(conn, "computer")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO planning.plan_revision(plan_id,revision_no,domain_id,domain_snapshot,
                 name_snapshot) VALUES (%s,9,%s,'{}','빈 스냅샷')""",
            (fix["plan"], fix["domain"]["id"]))
    conn.rollback()


# ── 실제 근거 연결: 메타데이터 채움 · 중복 제거 · 실행 스코프 ──
@pytest.fixture
def evidence_env(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_STORAGE_ROOT", str(tmp_path / "objects"))
    repo, model = RagRepo(conn), LocalHashEmbedder()
    doc = read_manual(BUNDLE)
    ingest_manual(BUNDLE, repo, model)
    run_id = create_test_run(conn)
    request = SearchRequest(
        domain="baby", query="바구니 최대 하중", product_key=doc.product_key,
        variant_key=doc.variant_key, corpus="synthetic", market=doc.market,
        recommendation_run_id=run_id,
    )
    from src.engine.stage5_explain import explain_manual
    answer = explain_manual(RagService(repo, model), request)
    assert answer["hits"], "합성 코퍼스에서 근거가 나오지 않음"
    yield conn, run_id, answer["hits"][0]["evidence_id"], request


def test_sr08_linked_evidence_carries_full_metadata_and_dedupes(evidence_env):
    conn, run_id, evidence_id, _ = evidence_env
    revision_id = conn.execute(
        "SELECT revision_id FROM engine.recommendation_run WHERE id=%s", (run_id,)).fetchone()["revision_id"]
    requirement = PlanRepo(conn).ensure_requirement(revision_id, "STROLLER", {"slot": "STROLLER"})
    candidate = _insert_candidate(conn, run_id, requirement)

    erepo = EngineRepo(conn)
    erepo.link_candidate_evidence(candidate, evidence_id, "manual_excerpt")
    erepo.link_candidate_evidence(candidate, evidence_id, "manual_excerpt")  # 같은 주장 재연결

    refs = conn.execute("SELECT evidence_refs AS r FROM engine.recommendation_candidate WHERE id=%s",
                        (candidate,)).fetchone()["r"]
    assert refs["schema_version"] == 1
    assert len(refs["refs"]) == 1, "중복 인용이 쌓였다"
    ref = refs["refs"][0]
    assert ref["evidence_id"] == str(evidence_id) and ref["claim_key"] == "manual_excerpt"
    assert len(ref["file_sha256"]) == 64 and ref["material_id"] and ref["material_version"]
    assert isinstance(ref["locator"], dict) and ref["locator"]
    conn.rollback()


def test_sr08_validation_evidence_uses_the_same_contract(evidence_env):
    import datetime as dt

    conn, run_id, evidence_id, _ = evidence_env
    erepo = EngineRepo(conn)
    validation = erepo.add_validation(
        run_id, rule_key="baby_manual_applicability", rule_version="v1", executor_version="rag-v1",
        status="unknown", severity="critical", measured_values={}, threshold={},
        message="sr test", checked_at=dt.datetime.now(dt.timezone.utc))
    erepo.link_validation_target(validation, requirement_id=None)
    erepo.link_validation_evidence(validation, evidence_id)
    erepo.link_validation_evidence(validation, evidence_id)
    issues = conn.execute("SELECT issues AS i FROM engine.validation_result WHERE id=%s",
                          (validation,)).fetchone()["i"]
    assert len(issues[0]["evidence_refs"]) == 1
    assert issues[0]["evidence_refs"][0]["file_sha256"]
    assert issues[0]["target"] is not None
    conn.rollback()


def test_sr08_evidence_from_another_run_is_out_of_scope(evidence_env):
    conn, run_id, evidence_id, _ = evidence_env
    foreign_run = create_test_run(conn)
    revision_id = conn.execute(
        "SELECT revision_id FROM engine.recommendation_run WHERE id=%s",
        (foreign_run,)).fetchone()["revision_id"]
    requirement = PlanRepo(conn).ensure_requirement(revision_id, "STROLLER", {"slot": "STROLLER"})
    candidate = _insert_candidate(conn, foreign_run, requirement)
    with pytest.raises(psycopg.errors.RaiseException, match="evidence_scope_violation"):
        EngineRepo(conn).link_candidate_evidence(candidate, evidence_id, "manual_excerpt")
    conn.rollback()


def test_sr08_unknown_evidence_id_is_rejected(conn):
    fix = _revision(conn, "computer")
    run_id = _run(conn, fix["revision"])
    candidate = _insert_candidate(conn, run_id, fix["requirement"])
    ghost = json.dumps({"schema_version": 1, "refs": [FULL_REF]})
    with pytest.raises(psycopg.errors.RaiseException, match="evidence_scope_violation"):
        conn.execute("UPDATE engine.recommendation_candidate SET evidence_refs=%s WHERE id=%s",
                     (ghost, candidate))
    conn.rollback()
