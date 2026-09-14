"""P3 — 후보 안전 조건·설명서 검증·근거 연결. Real PostgreSQL only (no `rag` schema).

develop `da79839` / P3-D3 alignment: the PostgreSQL `rag` schema is gone
(`0011_drop_rag_schema.sql`). These tests drive the real synthetic stroller manual
through `MaterialRepo` (assets.product_material/material_revision/
material_applicability, evidence.source/evidence.evidence — all real, unmerged
develop tables) and a real, working `LocalFileSearchProvider` (file-backed, external
to PostgreSQL — see src/rag/provider.py), not a mock. Every test builds a genuine
domain/plan/revision/run/candidate through the real repositories, never a synthetic
run id string. Acceptance case ids (VE01-VE08) refer to
docs/agent-tasks/baby/P3_verification_rag.md; D3-01 is what this file proves — D3-02
(a real third-party search backend) has no product/connection available in this
environment and stays explicitly blocked (see reports/P3.md).
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from src.dto import ExplanationWithRefs
from src.engine.stage3c_verify import verify_baby_candidate
from src.engine.stage5_explain import explain_baby_candidate
from src.rag.ingestion import digest, ingest_manual, read_manual
from src.rag.provider import ProviderError, get_search_provider
from src.rag.service import RagService
from src.repo.engine_repo import EngineRepo, persist_candidate_check
from src.repo.material_repo import MaterialRepo
from src.repo.plan_repo import PlanRepo
from src.repo.rag_repo import resolve_public_evidence

DSN = os.getenv("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated database"
)

BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"
CATALOG = ROOT / "data/baby/catalog_demo_v1.json"

PASS_CONDITIONS = {"age_stage": {"months": 8, "exact": True}, "weight_kg": 8.5, "independent_sitting": True}


class FailingProvider:
    """A real Protocol implementation that always fails the call — proves VE07's
    'search error' axis is distinct from 'no_evidence', not a canned mock answer."""

    name = "failing-test-provider"

    def publish(self, document):
        raise NotImplementedError

    def search(self, **kwargs):
        raise ProviderError("search_backend_unavailable")

    def resolve(self, external_hit_id):
        raise NotImplementedError

    def revoke(self, external_document_id):
        raise NotImplementedError


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("BABY_SEARCH_PROVIDER", "local-file")
    monkeypatch.setenv("BABY_SEARCH_STORAGE_ROOT", str(tmp_path / "search-index"))
    conn = psycopg.connect(DSN, prepare_threshold=None)
    try:
        from seed_baby_catalog import load_input, seed_catalog

        manifest, records = load_input(CATALOG)
        seed_report = seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")

        material_repo = MaterialRepo(conn)
        provider = get_search_provider()
        assert provider is not None, "BABY_SEARCH_PROVIDER=local-file must resolve to a real provider"
        doc = read_manual(BUNDLE)
        ingest_manual(BUNDLE, material_repo, provider, reviewed=True)
        service = RagService(material_repo, provider)

        yield conn, material_repo, provider, service, seed_report, doc
    finally:
        conn.rollback()
        conn.close()


def _make_run(conn):
    """Real domain_version/plan/revision/run rows — never a dummy id."""
    plan_repo, engine_repo = PlanRepo(conn), EngineRepo(conn)
    conversation = plan_repo._one(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        (f"test-baby-verification-{uuid4()}",),
    )["id"]
    plan_id = plan_repo.create_plan(conversation, "P3 test", None)
    domain_version = plan_repo.published_domain_version("baby")
    revision_id = plan_repo.new_revision(plan_id, domain_version["id"], "P3 test")
    plan_repo.set_current_revision(plan_id, revision_id)
    revision = plan_repo.get_revision(revision_id)
    run_id = engine_repo.start_run(
        revision_id, revision["domain_version_id"], input_snapshot={}, input_hash="p3-test",
        draft_lock_version=revision["lock_version"], engine_versions={"pipeline": "baby-p3-test"},
    )
    return plan_repo, engine_repo, revision, run_id


def _candidate(plan_repo, engine_repo, revision, run_id, variant_id, *, slot_key, product_key,
               variant_key, market="KR_DEMO", corpus="synthetic", facts=None):
    node_id = plan_repo.ensure_node(revision["id"], slot_key, slot_key)
    req_id = plan_repo.ensure_requirement(revision["id"], node_id, {})
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
    conn, material_repo, provider, service, seed, doc = env
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
        (5, 8.5, True, "fail"),
        (8, 30.0, True, "fail"),
        (8, 8.5, False, "fail"),
        (8, 8.5, None, "unknown"),
    ],
)
def test_ve02_independent_axes_fail_or_unknown(env, age_months, weight_kg, sitting, expected):
    conn, material_repo, provider, service, seed, doc = env
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
    conn, material_repo, provider, service, seed, doc = env
    from src.rag.ingestion import publish_manual
    from src.repo.product_repo import ProductRepo

    unreviewed_doc = replace(doc, manual_id="SYN-UNREVIEWED-MANUAL", product_key="SYN-STROLLER-UNREVIEWED",
                             variant_key="SYN-STROLLER-UNREVIEWED-V1")
    unreviewed_doc = replace(unreviewed_doc, sha256=digest(unreviewed_doc.text.encode()))
    prodrepo = ProductRepo(conn)
    category_id = prodrepo.resolve_category_id("stroller")
    product_id = prodrepo.upsert_synthetic_product(
        product_key="SYN-STROLLER-UNREVIEWED", name="테스트 미검토 유모차", brand="테스트",
        category_id=category_id, product_type="stroller", attributes={"corpus": "synthetic"},
    )
    prodrepo.upsert_synthetic_variant(product_id, "SYN-STROLLER-UNREVIEWED-V1", attributes={})
    publish_manual(unreviewed_doc, material_repo, provider, reviewed=False)
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
    conn, material_repo, provider, service, seed, doc = env
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
    conn, material_repo, provider, service, seed, doc = env
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
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    # A different, really-seeded stroller variant with similar text but no published manual.
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-002-NAVY"],
        slot_key="stroller", product_key="SYN-STROLLER-002", variant_key="SYN-STROLLER-002-NAVY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "none"
    assert check.explanation_evidence == []


# ── P3 review R3 ────────────────────────────────────────────────────────────
def test_r3_hit_claiming_a_different_product_is_rejected(env):
    """A provider is external/untrusted: a hit with the right material_revision_id
    and file_sha256 but a WRONG product_id/corpus must still be rejected — matching
    the revision id alone is not enough (P3 review R3)."""
    from dataclasses import replace as dc_replace

    conn, material_repo, provider, service, seed, doc = env
    from src.rag.contracts import SearchRequest

    class TamperingProvider:
        name = "tampering-test-provider"

        def __init__(self, inner):
            self.inner = inner

        def publish(self, document):
            return self.inner.publish(document)

        def search(self, **kwargs):
            hits = self.inner.search(**kwargs)
            return [dc_replace(h, product_id="00000000-0000-0000-0000-000000000000") for h in hits]

        def resolve(self, external_hit_id):
            return self.inner.resolve(external_hit_id)

        def revoke(self, external_document_id):
            return self.inner.revoke(external_document_id)

    tampering_service = RagService(material_repo, TamperingProvider(provider))
    request = SearchRequest(
        domain="baby", query="유모차 조립", product_key="SYN-STROLLER-001",
        variant_key="SYN-STROLLER-001-GREY", market="KR_DEMO", corpus="synthetic",
    )
    result = tampering_service.search(request)
    assert result.status == "no_evidence", "tampered product_id hits must all be rejected, not cited"


# ── VE05 ──────────────────────────────────────────────────────────────────
def test_ve05_verification_and_explanation_refs_can_differ(env):
    conn, material_repo, provider, service, seed, doc = env
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
    conn, material_repo, provider, service, seed, doc = env
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

    revision_id = conn.execute(
        "SELECT facts->>'material_revision_id' FROM evidence.evidence WHERE id=%s", (refs[0]["evidence_id"],)
    ).fetchone()[0]
    material_repo.revoke_revision(UUID(revision_id))

    after = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(run_id)})
    assert all(pe["available"] is False for pe in after)
    assert all(pe["text"] is None for pe in after)
    assert all(pe["evidence_id"] == r["evidence_id"] for pe, r in zip(after, refs)), "trace retained"
    assert all(pe["redacted_reason"] for pe in after)


def test_r2_file_changed_since_citation_is_redacted(env):
    """P3 review R2: publish status alone is not enough — if the underlying file's
    hash no longer matches what was cited, the text must be redacted even though the
    revision is still 'published'."""
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    run_context = _run_context(run_id)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, run_context)
    refs = [{"evidence_id": h["evidence_id"], "locator": h["locator"]} for h in check.explanation_evidence]
    before = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(run_id)})
    assert all(pe["available"] for pe in before)

    conn.execute(
        "UPDATE assets.file_object SET sha256=repeat('0', 64) "
        "WHERE id=(SELECT file_object_id FROM assets.material_revision WHERE id=(SELECT "
        "facts->>'material_revision_id' FROM evidence.evidence WHERE id=%s)::uuid)",
        (refs[0]["evidence_id"],),
    )
    after = resolve_public_evidence(conn, refs, {"recommendation_run_id": str(run_id)})
    assert all(pe["available"] is False for pe in after)
    assert all(pe["redacted_reason"] == "file_changed_since_citation" for pe in after)


def test_ve06_out_of_scope_run_cannot_read_evidence(env):
    conn, material_repo, provider, service, seed, doc = env
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
def test_ve07_provider_failure_is_error_not_no_evidence(env):
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    failing_service = RagService(material_repo, FailingProvider())
    check = verify_baby_candidate(failing_service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "error"
    assert check.error_code == "search_backend_unavailable"


def test_ve07_unconfigured_provider_is_error_not_no_evidence(env):
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    unconfigured_service = RagService(material_repo, None)
    check = verify_baby_candidate(unconfigured_service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "error"
    assert check.error_code == "search_provider_unavailable"


def test_ve07_sql_failure_is_error_not_no_evidence(env, monkeypatch):
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )

    def fail(*args, **kwargs):
        conn.execute("SELECT 1/0")

    monkeypatch.setattr(material_repo, "find_applicable_revision", fail)
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    assert check.eligibility == "unknown"
    assert check.coverage == "error"
    assert check.error_code == "retrieval_database_error"


# ── VE08 ──────────────────────────────────────────────────────────────────
def test_ve08_orphan_evidence_ref_rejected_before_persistence(env):
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    check.issues[0]["evidence_ids"] = [str(uuid4())]  # nonexistent evidence id
    with pytest.raises(ValueError, match="orphan_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))
    assert engine_repo.get_validations(run_id) == [], "nothing persisted for the rejected candidate"


def test_ve08_cross_run_evidence_ref_rejected(env):
    conn, material_repo, provider, service, seed, doc = env
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
    with pytest.raises(ValueError, match="cross_run_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))
    assert engine_repo.get_validations(run_id) == []


def test_ve08_revoked_evidence_ref_rejected(env):
    conn, material_repo, provider, service, seed, doc = env
    plan_repo, engine_repo, revision, run_id = _make_run(conn)
    candidate = _candidate(
        plan_repo, engine_repo, revision, run_id, seed.variant_ids["SYN-STROLLER-001-GREY"],
        slot_key="stroller", product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
    )
    check = verify_baby_candidate(service, candidate, PASS_CONDITIONS, _run_context(run_id))
    evidence_id = check.explanation_evidence[0]["evidence_id"]
    revision_id = conn.execute(
        "SELECT facts->>'material_revision_id' FROM evidence.evidence WHERE id=%s", (evidence_id,)
    ).fetchone()[0]
    material_repo.revoke_revision(UUID(revision_id))
    check.issues[0]["evidence_ids"] = [evidence_id]
    with pytest.raises(ValueError, match="revoked_evidence_ref"):
        persist_candidate_check(conn, run_id, candidate["candidate_id"], check,
                                ExplanationWithRefs(candidate_id=candidate["candidate_id"], status="pending"))


def test_ve08_valid_check_persists_and_is_readable(env):
    conn, material_repo, provider, service, seed, doc = env
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
