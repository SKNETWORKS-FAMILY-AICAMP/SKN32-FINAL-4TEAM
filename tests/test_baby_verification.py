"""P3 — 후보 안전 조건·설명서 검증·근거 연결. Real PostgreSQL/pgvector only.

Every test builds a genuine domain/plan/revision/run/candidate through the real
repositories (PlanRepo/EngineRepo), never a synthetic run id string, and drives the
real synthetic stroller manual through RagService — no scenario JSON, no mocked
persistence path. Acceptance case ids (VE01-VE08) refer to
docs/agent-tasks/baby/P3_verification_rag.md.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# P0 v3 (develop `da79839` alignment): the `rag` schema this suite drives end-to-end
# was dropped by `0011_drop_rag_schema.sql` — RAG moves to an external search provider
# whose boundary/adapter is P3-D3-01/D3-02, not yet implemented. Keep this file for the
# VE01-VE08 acceptance case shapes but do not let a stale import crash the whole suite.
try:
    from src.engine.stage3c_verify import verify_baby_candidate
    from src.engine.stage5_explain import explain_baby_candidate
    from src.rag.contracts import SearchRequest
    from src.rag.embedding import LocalHashEmbedder
    from src.rag.ingestion import ingest_manual, read_manual
    from src.rag.service import RagService
    from src.repo.engine_repo import EngineRepo, persist_candidate_check
    from src.repo.plan_repo import PlanRepo
    from src.repo.rag_repo import RagRepo, resolve_public_evidence
except ImportError as exc:
    pytest.skip(
        f"rag schema removed (P0 v3 develop alignment); P3 external search adapter pending: {exc}",
        allow_module_level=True,
    )

DSN = os.getenv("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated pgvector database"
)

BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"
CATALOG = ROOT / "data/baby/catalog_demo_v1.json"

PASS_CONDITIONS = {"age_stage": {"months": 8, "exact": True}, "weight_kg": 8.5, "independent_sitting": True}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_STORAGE_ROOT", str(tmp_path / "objects"))
    conn = psycopg.connect(DSN, prepare_threshold=None)
    try:
        from seed_baby_catalog import load_input, seed_catalog

        manifest, records = load_input(CATALOG)
        seed_report = seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")

        repo, model = RagRepo(conn), LocalHashEmbedder()
        doc = read_manual(BUNDLE)
        ingest_manual(BUNDLE, repo, model)
        repo.publish_manual(doc, model.embed([c.text for c in doc.chunks]), model, reviewed=True)
        service = RagService(repo, model)

        yield conn, repo, service, seed_report, doc
    finally:
        conn.rollback()
        conn.close()


def _make_run(conn):
    """Real domain/plan/revision/run rows — never a dummy id (CONTRACTS VERIFY note)."""
    plan_repo, engine_repo = PlanRepo(conn), EngineRepo(conn)
    conversation = plan_repo._one(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        (f"test-baby-verification-{uuid4()}",),
    )["id"]
    plan_id = plan_repo.create_plan(conversation, "P3 test", None)
    domain = plan_repo.published_domain("baby")
    revision_id = plan_repo.new_revision(plan_id, domain["id"], "P3 test")
    plan_repo.set_current_revision(plan_id, revision_id)
    revision = plan_repo.get_revision(revision_id)
    run_id = engine_repo.start_run(
        revision_id, revision["domain_id"], input_snapshot={}, input_hash="p3-test",
        draft_lock_version=revision["lock_version"], engine_versions={"pipeline": "baby-p3-test"},
    )
    return plan_repo, engine_repo, revision, run_id


def _candidate(plan_repo, engine_repo, revision, run_id, variant_id, *, slot_key, product_key,
               variant_key, market="KR_DEMO", corpus="synthetic", facts=None):
    req_id = plan_repo.ensure_requirement(revision["id"], slot_key, {})
    candidate_id = engine_repo.add_candidate(run_id, req_id, variant_id, result="pending")
    return {
        "candidate_id": str(candidate_id), "requirement_id": str(req_id),
        "product_key": product_key, "variant_key": variant_key, "slot_key": slot_key,
        "market": market, "language": "ko", "corpus": corpus, "facts": facts or {},
    }


def _run_context(run_id):
    return {"recommendation_run_id": str(run_id)}


# ── VE01 ──────────────────────────────────────────────────────────────────
def test_ve01_documented_seat_constraints_pass_with_partial_coverage_and_citation(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "pass"
    assert check.selection_allowed is True
    assert check.coverage == "partial"
    assert check.verification == "partial"
    assert check.explanation_evidence, "pass must still carry the manual citation it relied on"
    assert all(h["locator"].get("section_code") == "S01" for h in check.explanation_evidence)


# ── VE02 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "age_months,weight_kg,sitting,expected",
    [
        (5, 8.5, True, "fail"),       # age below threshold
        (8, 30.0, True, "fail"),      # weight beyond limit
        (8, 8.5, False, "fail"),      # sitting explicitly false
        (8, 8.5, None, "unknown"),    # missing sitting
    ],
)
def test_ve02_independent_axes_fail_or_unknown(env, age_months, weight_kg, sitting, expected):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    conditions = {"age_stage": {"months": age_months, "exact": True}, "weight_kg": weight_kg,
                  "independent_sitting": sitting}
    check = verify_baby_candidate(service, candidate, conditions, _run_context(run_id))
    assert check.eligibility == expected
    assert check.selection_allowed is False


def test_ve02_unreviewed_manual_is_unknown_not_pass(env):
    conn, repo, service, seed, doc = env
    # A second, never-reviewed variant of the same product: publish_manual(reviewed=False)
    # is exactly what ingest_manual already did before the fixture's reviewed republish,
    # so re-ingesting fresh (no reviewed flag) on an unrelated product proves the axis.
    unreviewed_doc = replace(doc, manual_id="SYN-UNREVIEWED-MANUAL", product_key="SYN-STROLLER-UNREVIEWED",
                             variant_key="SYN-STROLLER-UNREVIEWED-V1")
    from src.rag.ingestion import digest
    unreviewed_doc = replace(unreviewed_doc, sha256=digest(unreviewed_doc.text.encode()))
    model = LocalHashEmbedder()
    repo.publish_manual(unreviewed_doc, model.embed([c.text for c in unreviewed_doc.chunks]), model, reviewed=False)
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = {
        "candidate_id": str(uuid4()), "requirement_id": str(uuid4()),
        "product_key": "SYN-STROLLER-UNREVIEWED", "variant_key": "SYN-STROLLER-UNREVIEWED-V1",
        "slot_key": "stroller", "market": "KR_DEMO", "language": "ko", "corpus": "synthetic", "facts": {},
    }
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "none"
    assert check.explanation_evidence == []


# ── VE03 ──────────────────────────────────────────────────────────────────
def test_ve03_active_recall_excluded_regardless_of_price(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    variant_id = seed.variant_ids["SYN-BOTTLE-RECALL-001-240ML"]
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, variant_id, slot_key="bottle",
        product_key="SYN-BOTTLE-RECALL-001", variant_key="SYN-BOTTLE-RECALL-001-240ML",
        facts={"recall_status": {"value": "active_synthetic_recall", "unit": None, "verification_status": "verified"}},
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "fail"
    assert check.selection_allowed is False
    assert any(i["rule_key"] == "baby_recall_v1" and i["status"] == "fail" for i in check.issues)


def test_ve03_missing_certificate_is_unknown_never_auto_selected(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    variant_id = seed.variant_ids["SYN-CARSEAT-CERT-001-DEFAULT"]
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, variant_id, slot_key="car_seat",
        product_key="SYN-CARSEAT-CERT-001", variant_key="SYN-CARSEAT-CERT-001-DEFAULT",
        facts={"kc_certification_number": {"value": None, "unit": None, "verification_status": "unknown"}},
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.selection_allowed is False
    assert any(i["rule_key"] == "baby_certification_v1" and i["status"] == "unknown" for i in check.issues)


# ── VE04 ──────────────────────────────────────────────────────────────────
def test_ve04_wrong_variant_cannot_produce_evidence(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    # SYN-STROLLER-002-NAVY is a *different* real seeded variant with similar-looking
    # text-search terms (also a stroller); it has no manual published for it at all.
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-002-NAVY"],
        slot_key="stroller", product_key="SYN-STROLLER-002", variant_key="SYN-STROLLER-002-NAVY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "none"
    assert check.explanation_evidence == []


# ── VE05 ──────────────────────────────────────────────────────────────────
def test_ve05_verification_and_explanation_refs_can_differ(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    run_context = _run_context(run_id)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, run_context)
    explanation = explain_baby_candidate(service, candidate, check, run_context)
    assert explanation.status == "ready"
    verification_ids = {h["evidence_id"] for h in check.explanation_evidence}
    explanation_ids = {r["evidence_id"] for r in explanation.refs}
    assert verification_ids, "verification must cite at least one evidence id"
    assert explanation_ids, "explanation must cite at least one evidence id"
    assert verification_ids != explanation_ids
    verification_sections = {h["locator"].get("section_code") for h in check.explanation_evidence}
    explanation_sections = {r["locator"].get("section_code") for r in explanation.refs}
    assert verification_sections == {"S01"}
    assert explanation_sections != verification_sections


# ── VE06 ──────────────────────────────────────────────────────────────────
def test_ve06_revocation_hides_text_but_keeps_trace(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    run_context = _run_context(run_id)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, run_context)
    explanation = explain_baby_candidate(service, candidate, check, run_context)
    persist_candidate_check(conn, run_id, candidate["candidate_id"], check, explanation)

    refs = [{"evidence_id": h["evidence_id"], "locator": h["locator"]} for h in check.explanation_evidence]
    before = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(run_id)})
    assert all(pe["available"] for pe in before)
    assert any(pe["text"] for pe in before)

    material_id = repo._one(
        "SELECT material_id FROM rag.ingestion_job ij JOIN rag.document_chunk dc ON dc.ingestion_id=ij.id "
        "JOIN rag.retrieval_hit rh ON rh.chunk_id=dc.id JOIN evidence.evidence ev ON ev.retrieval_hit_id=rh.id "
        "WHERE ev.id=%s", (refs[0]["evidence_id"],),
    )["material_id"]
    repo.revoke_material(material_id)

    after = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(run_id)})
    assert all(pe["available"] is False for pe in after)
    assert all(pe["text"] is None for pe in after)
    assert all(pe["evidence_id"] == r["evidence_id"] for pe, r in zip(after, refs)), "trace retained"
    assert all(pe["redacted_reason"] for pe in after)


def test_ve06_out_of_scope_run_cannot_read_evidence(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    other_plan_repo, other_engine_repo, other_revision, other_run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    refs = [{"evidence_id": h["evidence_id"], "locator": h["locator"]} for h in check.explanation_evidence]
    resolved = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(other_run_id)})
    assert all(pe["available"] is False and pe["redacted_reason"] == "out_of_scope" for pe in resolved)


# ── VE07 ──────────────────────────────────────────────────────────────────
def test_ve07_embedder_failure_is_error_not_no_evidence(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )

    class Failing(LocalHashEmbedder):
        def embed(self, texts):
            from src.rag.contracts import EmbeddingError
            raise EmbeddingError("embedding_unavailable")

    failing_service = RagService(repo, Failing())
    check = verify_baby_candidate(failing_service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "error"
    assert check.error_code == "embedding_unavailable"


def test_ve07_sql_failure_is_error_not_no_evidence(env, monkeypatch):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )

    def fail(*args, **kwargs):
        conn.execute("SELECT 1/0")

    monkeypatch.setattr(repo, "search", fail)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "error"
    assert check.error_code == "retrieval_database_error"


# ── VE08 ──────────────────────────────────────────────────────────────────
def test_ve08_orphan_evidence_ref_rejected_before_persistence(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    check.issues[0]["evidence_ids"] = [str(uuid4())]  # nonexistent evidence id
    from src.dto import ExplanationWithRefs
    with pytest.raises(ValueError, match="orphan_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))
    assert engine_repo.get_validations(run_id) == [], "nothing persisted for the rejected candidate"


def test_ve08_cross_run_evidence_ref_rejected(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    other_plan_repo, other_engine_repo, other_revision, other_run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    other_candidate = _candidate(
        other_plan_repo, other_engine_repo, other_revision, other_run_id,
        seed.variant_ids["SYN-STROLLER-001-GREY"], slot_key="stroller",
        product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    other_check = verify_baby_candidate(service, other_candidate, PASS_CONDITIONS, _run_context(other_run_id))
    foreign_evidence_id = other_check.explanation_evidence[0]["evidence_id"]

    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    check.issues[0]["evidence_ids"] = [foreign_evidence_id]
    from src.dto import ExplanationWithRefs
    with pytest.raises(ValueError, match="cross_run_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))
    assert engine_repo.get_validations(run_id) == []


def test_ve08_revoked_evidence_ref_rejected(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    evidence_id = check.explanation_evidence[0]["evidence_id"]
    material_id = repo._one(
        "SELECT material_id FROM rag.ingestion_job ij JOIN rag.document_chunk dc ON dc.ingestion_id=ij.id "
        "JOIN rag.retrieval_hit rh ON rh.chunk_id=dc.id JOIN evidence.evidence ev ON ev.retrieval_hit_id=rh.id "
        "WHERE ev.id=%s", (evidence_id,),
    )["material_id"]
    repo.revoke_material(material_id)
    check.issues[0]["evidence_ids"] = [evidence_id]
    from src.dto import ExplanationWithRefs
    with pytest.raises(ValueError, match="revoked_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))


def test_ve08_valid_check_persists_and_is_readable(env):
    conn, repo, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    run_context = _run_context(run_id)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, run_context)
    explanation = explain_baby_candidate(service, candidate, check, run_context)
    persist_candidate_check(conn, run_id, candidate["candidate_id"], check, explanation)

    validations = engine_repo.get_validations(run_id)
    assert validations, "at least one validation_result row persisted"
    assert any(v["rule_key"] == "baby_seat_v1" and v["status"] == "pass" for v in validations)
    evidence = engine_repo.get_candidate_evidence(candidate["candidate_id"])
    assert evidence, "explanation evidence linked to the candidate"
