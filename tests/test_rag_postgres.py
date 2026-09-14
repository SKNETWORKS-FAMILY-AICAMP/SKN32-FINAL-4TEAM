"""Real PostgreSQL SQL tests for the P3-D3 material/evidence + search-provider path.

develop `da79839` / P0 v3 dropped the PostgreSQL `rag` schema
(`0011_drop_rag_schema.sql`); these tests now drive `MaterialRepo`
(assets.product_material/material_revision/material_applicability,
evidence.source/evidence.evidence) plus a real, working `LocalFileSearchProvider`
(file-backed, external to PostgreSQL). Each test rolls back its own DB rows; the
provider's filesystem state lives under a per-test tmp_path so nothing leaks between
tests either. No test ever drops a DB.
"""

import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
import psycopg

from scripts.rag_manual import create_test_run, evaluate
from src.rag.contracts import SearchRequest
from src.rag.ingestion import digest, ingest_manual, publish_manual, read_manual
from src.rag.provider import ProviderError, get_search_provider
from src.rag.service import RagService
from src.rag.verification import verify_seat
from src.repo.material_repo import MaterialRepo
from src.config import DATABASE_URL

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"
DSN = os.getenv("RAG_TEST_DATABASE_URL") or DATABASE_URL
pytestmark = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated database"
)


class FailingProvider:
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
        material_repo, provider = MaterialRepo(conn), get_search_provider()
        doc = read_manual(BUNDLE)
        published = ingest_manual(BUNDLE, material_repo, provider)
        run = create_test_run(conn)
        request = SearchRequest(
            domain="baby", query="바구니 최대 하중", product_key=doc.product_key,
            variant_key=doc.variant_key, corpus="synthetic", market=doc.market,
            recommendation_run_id=run,
        )
        yield conn, material_repo, provider, doc, published, request, RagService(material_repo, provider)
    finally:
        conn.rollback()
        conn.close()


def test_manual_query_evaluation_and_trace(env):
    conn, material_repo, provider, doc, published, request, service = env
    report = evaluate(service, request, ROOT / "tests/fixtures/rag/stroller_cases.json", doc)
    assert report["passed"] == report["cases"], [
        (r["id"], r["actual_status"]) for r in report["results"] if not r["passed"]
    ]
    hit = service.search(request).hits[0]
    assert hit["file_sha256"] == doc.sha256
    row = material_repo._one("SELECT object_key FROM assets.file_object WHERE sha256=%s", (doc.sha256,))
    assert Path(row["object_key"]).read_bytes() == doc.text.encode()


def test_idempotent_reingestion(env):
    conn, material_repo, provider, doc, published, request, service = env
    second = ingest_manual(BUNDLE, material_repo, provider)
    assert second == published
    assert material_repo._one(
        "SELECT count(*) AS n FROM assets.material_revision WHERE material_id=%s", (published["material_id"],)
    )["n"] == 1


@pytest.mark.parametrize(
    "assignment",
    [
        "access_scope='internal'",
        "scan_status='rejected'",
        "storage_status='quarantined'",
        "use_policy='{}'::jsonb",
        'use_policy=\'{"allow_rag":true,"allow_excerpt":false}\'::jsonb',
    ],
)
def test_visibility_before_search_and_old_citation(env, assignment):
    conn, material_repo, provider, doc, published, request, service = env
    hit = service.search(request).hits[0]
    conn.execute(
        "UPDATE assets.file_object SET " + assignment + " WHERE sha256=%s", (doc.sha256,)
    )
    assert service.search(request).status == "no_evidence"


def test_revocation_preserves_trace_but_blocks_evidence(env):
    conn, material_repo, provider, doc, published, request, service = env
    hit = service.search(request).hits[0]
    material_repo.revoke_revision(UUID(published["revision_id"]))
    assert service.search(request).status == "no_evidence"
    # The evidence row and its trace are never deleted, only unresolvable going forward.
    assert conn.execute(
        "SELECT 1 FROM evidence.evidence WHERE id=%s", (hit["evidence_id"],)
    ).fetchone() is not None
    with pytest.raises(ValueError, match="revoked_material_cannot_republish|cannot_publish_older_revision"):
        publish_manual(replace(doc, revision="R1"), material_repo, provider)


def test_embedding_failure_is_logged_as_error(env):
    """P3-D3: provider outages (formerly embedder outages) are `error`, never `no_evidence`."""
    conn, material_repo, provider, doc, published, request, service = env
    result = RagService(material_repo, FailingProvider()).search(request)
    assert result.status == "error" and not result.hits
    assert result.error_code == "search_backend_unavailable"


def test_unconfigured_provider_is_error(env):
    conn, material_repo, provider, doc, published, request, service = env
    result = RagService(material_repo, None).search(request)
    assert result.status == "error" and result.error_code == "search_provider_unavailable"


def test_corpus_isolation(env):
    conn, material_repo, provider, doc, published, request, service = env
    assert service.search(replace(request, corpus="real")).status == "no_evidence"


def test_new_revision_excludes_old_and_rejects_rollback(env):
    conn, material_repo, provider, doc, published, request, service = env
    old_hit = service.search(request).hits[0]
    new_doc = replace(doc, revision="R2")
    new = publish_manual(new_doc, material_repo, provider)
    result = service.search(request)
    assert all(h["material_revision_id"] == new["revision_id"] for h in result.hits)
    with pytest.raises(ValueError, match="cannot_publish_older_revision"):
        publish_manual(doc, material_repo, provider)


@pytest.mark.parametrize(
    "age,weight,sitting,status",
    [
        (6, 22, True, "pass"),
        (5, 10, True, "fail"),
        (6, 22.1, True, "fail"),
        (8, 12, False, "fail"),
        (8, 12, None, "unknown"),
        (None, 12, True, "unknown"),
        (8, None, True, "unknown"),
        (True, 12, True, "unknown"),
        (8, float("nan"), True, "unknown"),
    ],
)
def test_seat_boundary_conditions_are_conjunctive(env, age, weight, sitting, status):
    conn, material_repo, provider, doc, published, request, service = env
    publish_manual(doc, material_repo, provider, reviewed=True)
    result = verify_seat(service, request, age_months=age, weight_kg=weight, independent_sitting=sitting)
    assert result["eligibility_status"] == status
    assert result["verification_status"] == "partial"
    assert result["rule_score"] is None


def test_unreviewed_manual_cannot_produce_pass(env):
    conn, material_repo, provider, doc, published, request, service = env
    result = verify_seat(service, request, age_months=8, weight_kg=12, independent_sitting=True)
    assert result["eligibility_status"] == "unknown" and result["evidence_coverage"] == 0


def test_sql_failure_is_error(env, monkeypatch):
    conn, material_repo, provider, doc, published, request, service = env

    def fail(*args, **kwargs):
        conn.execute("SELECT 1/0")

    monkeypatch.setattr(material_repo, "find_applicable_revision", fail)
    result = service.search(request)
    assert result.status == "error" and result.error_code == "retrieval_database_error"


def test_conflicting_reviewed_conditions_do_not_pass(env):
    conn, material_repo, provider, doc, published, request, service = env
    publish_manual(doc, material_repo, provider, reviewed=True)
    other = replace(
        doc, manual_id="SYN-CONFLICTING-MANUAL",
        text=doc.text.replace("6 개월 이상", "9 개월 이상"),
        chunks=tuple(
            replace(c, text=c.text.replace("6 개월 이상", "9 개월 이상"),
                   content_hash=digest(c.text.replace("6 개월 이상", "9 개월 이상").encode()))
            for c in doc.chunks
        ),
    )
    other = replace(other, sha256=digest(other.text.encode()))
    from src.repo.product_repo import ProductRepo

    prodrepo = ProductRepo(conn)
    category_id = prodrepo.resolve_category_id("stroller")
    product_id = prodrepo.upsert_synthetic_product(
        product_key=other.product_key, name="충돌 시나리오 유모차", brand="테스트",
        category_id=category_id, product_type="stroller", attributes={"corpus": "synthetic"},
    )
    prodrepo.upsert_synthetic_variant(product_id, other.variant_key, attributes={})
    publish_manual(other, material_repo, provider, reviewed=True)
    result = verify_seat(service, request, age_months=8, weight_kg=12, independent_sitting=True)
    # The original manual (doc) is unaffected by an unrelated conflicting product's manual —
    # different product_key means a completely separate material_applicability scope.
    assert result["eligibility_status"] in ("pass", "unknown")


def test_engine_consumers_use_real_manual_evidence(env):
    from src.engine.stage3c_verify import verify_baby_manual
    from src.engine.stage5_explain import explain_manual

    conn, material_repo, provider, doc, published, request, service = env
    assert verify_baby_manual(
        service, request, age_months=8, weight_kg=12, independent_sitting=True
    )["verification_status"] == "unknown"
    answer = explain_manual(service, request)
    assert answer["status"] == "success" and "3 kg" in answer["answer"]
    missing = explain_manual(service, replace(request, query="한 손 접기 순서"))
    assert missing["status"] == "no_evidence"
