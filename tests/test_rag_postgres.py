"""Real pgvector SQL tests. Requires an explicitly selected disposable test DB.

Run migrations first. Each test rolls back its own rows. No test ever drops a DB.
PGlite is supported with prepare_threshold=None (one multiplexed connection).
"""

import os
from dataclasses import replace
from pathlib import Path

import pytest
import psycopg
from psycopg.types.json import Jsonb

from scripts.rag_manual import create_test_run, evaluate
from src.rag.contracts import EmbeddingError, SearchRequest
from src.rag.embedding import LocalHashEmbedder
from src.rag.ingestion import digest, ingest_manual, read_manual
from src.rag.service import RagService
from src.rag.verification import verify_seat
from src.repo.rag_repo import RagRepo

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"
DSN = os.getenv("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set RAG_TEST_DATABASE_URL to a disposable migrated pgvector database",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_STORAGE_ROOT", str(tmp_path / "objects"))
    conn = psycopg.connect(DSN, prepare_threshold=None)
    try:
        # Everything including publication and evidence rows is rolled back after the test.
        conn.execute("SELECT 1")
        repo, model = RagRepo(conn), LocalHashEmbedder()
        doc = read_manual(BUNDLE)
        published = ingest_manual(BUNDLE, repo, model)
        run = create_test_run(conn)
        request = SearchRequest(
            domain="baby",
            query="바구니 최대 하중",
            product_key=doc.product_key,
            variant_key=doc.variant_key,
            corpus="synthetic",
            market=doc.market,
            recommendation_run_id=run,
        )
        yield conn, repo, model, doc, published, request, RagService(repo, model)
    finally:
        conn.rollback()
        conn.close()


def test_manual_query_evaluation_and_trace(env):
    conn, repo, model, doc, published, request, service = env
    report = evaluate(
        service, request, ROOT / "tests/fixtures/rag/stroller_cases.json", doc
    )
    assert report["passed"] == report["cases"], [
        (r["id"], r["actual_status"]) for r in report["results"] if not r["passed"]
    ]
    hit = service.search(request).hits[0]
    row = repo.resolve_evidence(hit["evidence_id"], request, published["profile_id"])
    assert row["file_sha256"] == doc.sha256
    assert (
        Path(
            repo._one(
                "SELECT object_key FROM assets.file_object WHERE id=%s",
                (row["file_id"],),
            )["object_key"]
        ).read_bytes()
        == doc.text.encode()
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM rag.retrieval_run WHERE recommendation_run_id=%s AND status='completed'",
            (request.recommendation_run_id,),
        ).fetchone()[0]
        == 22
    )


def test_idempotent_reingestion(env):
    conn, repo, model, doc, published, request, service = env
    second = ingest_manual(BUNDLE, repo, model)
    assert second == published
    assert (
        conn.execute(
            "SELECT count(*) FROM rag.document_chunk WHERE ingestion_id=%s",
            (published["ingestion_id"],),
        ).fetchone()[0]
        == 5
    )


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
    conn, repo, model, doc, published, request, service = env
    hit = service.search(request).hits[0]
    # SQL fragments are fixed test parameters, never input from a caller.
    conn.execute(
        "UPDATE assets.file_object SET " + assignment + " WHERE id=%s",
        (hit["file_id"],),
    )
    assert service.search(request).status == "no_evidence"
    assert (
        repo.resolve_evidence(hit["evidence_id"], request, published["profile_id"])
        is None
    )


def test_revocation_preserves_trace_but_blocks_evidence(env):
    conn, repo, model, doc, published, request, service = env
    hit = service.search(request).hits[0]
    repo.revoke_material(published["material_id"])
    assert service.search(request).status == "no_evidence"
    assert (
        repo.resolve_evidence(hit["evidence_id"], request, published["profile_id"])
        is None
    )
    assert (
        conn.execute(
            "SELECT status FROM evidence.evidence WHERE id=%s", (hit["evidence_id"],)
        ).fetchone()[0]
        == "revoked"
    )
    assert conn.execute(
        "SELECT embedding IS NULL FROM rag.chunk_embedding WHERE chunk_id=%s",
        (hit["chunk_id"],),
    ).fetchone()[0]
    with pytest.raises(ValueError, match="revoked"):
        ingest_manual(BUNDLE, repo, model)


def test_permission_rechecked_between_search_and_citation(env):
    conn, repo, model, doc, published, request, service = env
    profile = repo.active_profile()
    run = repo.start_run(
        request.recommendation_run_id,
        profile["id"],
        purpose="validation",
        query_text=request.query,
        scope_snapshot={},
        retrieval_config={},
    )
    hits = repo.search(request, model.embed([request.query])[0], profile["id"])
    assert hits
    conn.execute(
        "UPDATE assets.product_material SET status='retired' WHERE id=%s",
        (published["material_id"],),
    )
    assert repo.record_hits(run, profile["id"], request, hits) == []


def test_applicability_and_required_context(env):
    conn, repo, model, doc, published, request, service = env
    assert service.search(replace(request, variant_key=None)).status == "no_evidence"
    conn.execute(
        "UPDATE assets.material_applicability SET conditions=jsonb_set(conditions,'{required_context}',%s) WHERE revision_id=%s",
        (Jsonb({"mode": "seat"}), published["revision_id"]),
    )
    assert service.search(request).status == "no_evidence"
    assert (
        service.search(replace(request, context={"mode": "seat"})).status == "success"
    )


def test_embedding_failure_is_logged_as_error(env):
    conn, repo, model, doc, published, request, service = env

    class Failing(LocalHashEmbedder):
        def embed(self, texts):
            raise EmbeddingError("embedding_unavailable")

    result = RagService(repo, Failing()).search(request)
    assert result.status == "error" and not result.hits
    assert (
        conn.execute(
            "SELECT status FROM rag.retrieval_run WHERE id=%s", (result.run_id,)
        ).fetchone()[0]
        == "failed"
    )


def test_profile_mismatch_and_corpus_isolation(env):
    conn, repo, model, doc, published, request, service = env

    class Different(LocalHashEmbedder):
        profile_key = "a-different-model-with-same-dimensions"

    assert (
        RagService(repo, Different()).search(request).error_code
        == "query_document_profile_mismatch"
    )
    assert service.search(replace(request, corpus="real")).status == "error"
    profile = repo.active_profile()
    assert (
        repo.search(
            replace(request, corpus="real"),
            model.embed([request.query])[0],
            profile["id"],
        )
        == []
    )


def test_failed_embedding_does_not_change_publication(env):
    conn, repo, model, doc, published, request, service = env

    class Incomplete(LocalHashEmbedder):
        def embed(self, texts):
            return super().embed(texts)[:-1]

    with pytest.raises(ValueError, match="incomplete_embedding_batch"):
        ingest_manual(BUNDLE, repo, Incomplete())
    assert service.search(request).status == "success"
    assert (
        str(
            conn.execute(
                "SELECT active_ingestion_id FROM assets.material_revision WHERE id=%s",
                (published["revision_id"],),
            ).fetchone()[0]
        )
        == published["ingestion_id"]
    )


def test_new_revision_excludes_old_chunks_and_rejects_rollback(env):
    conn, repo, model, doc, published, request, service = env
    old_hit = service.search(request).hits[0]
    # Same text, new document revision. Both identities must remain traceable.
    new_doc = replace(doc, revision="R2")
    new = repo.publish_manual(
        new_doc, model.embed([c.text for c in new_doc.chunks]), model
    )
    result = service.search(request)
    assert all(h["revision_id"] == new["revision_id"] for h in result.hits)
    assert (
        conn.execute(
            "SELECT count(*) FROM rag.retrieval_hit WHERE id=%s",
            (old_hit["retrieval_hit_id"],),
        ).fetchone()[0]
        == 1
    )
    with pytest.raises(ValueError, match="older_revision"):
        repo.publish_manual(doc, model.embed([c.text for c in doc.chunks]), model)


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
    conn, repo, model, doc, published, request, service = env
    repo.publish_manual(
        doc, model.embed([c.text for c in doc.chunks]), model, reviewed=True
    )
    result = verify_seat(
        service, request, age_months=age, weight_kg=weight, independent_sitting=sitting
    )
    assert result["eligibility_status"] == status
    assert (
        result["verification_status"] == "partial"
    )  # partial manual never means globally verified safety
    assert result["rule_score"] is None


def test_unreviewed_manual_cannot_produce_pass(env):
    conn, repo, model, doc, published, request, service = env
    result = verify_seat(
        service, request, age_months=8, weight_kg=12, independent_sitting=True
    )
    assert (
        result["eligibility_status"] == "unknown" and result["evidence_coverage"] == 0
    )


def test_sql_failure_is_error_and_run_survives_savepoint(env, monkeypatch):
    conn, repo, model, doc, published, request, service = env

    def fail(*args, **kwargs):
        conn.execute("SELECT 1/0")

    monkeypatch.setattr(repo, "search", fail)
    result = service.search(request)
    assert result.status == "error" and result.error_code == "retrieval_database_error"
    assert (
        conn.execute(
            "SELECT status FROM rag.retrieval_run WHERE id=%s", (result.run_id,)
        ).fetchone()[0]
        == "failed"
    )


def test_conflicting_reviewed_conditions_do_not_pass(env):
    conn, repo, model, doc, published, request, service = env
    repo.publish_manual(
        doc, model.embed([c.text for c in doc.chunks]), model, reviewed=True
    )
    other = replace(
        doc,
        manual_id="SYN-CONFLICTING-MANUAL",
        text=doc.text.replace("6 개월 이상", "9 개월 이상"),
        chunks=tuple(
            replace(
                c,
                text=c.text.replace("6 개월 이상", "9 개월 이상"),
                content_hash=digest(
                    c.text.replace("6 개월 이상", "9 개월 이상").encode()
                ),
            )
            for c in doc.chunks
        ),
    )
    other = replace(other, sha256=digest(other.text.encode()))
    repo.publish_manual(
        other, model.embed([c.text for c in other.chunks]), model, reviewed=True
    )
    result = verify_seat(
        service, request, age_months=8, weight_kg=12, independent_sitting=True
    )
    assert result["eligibility_status"] == "unknown"
    assert result["reason"] == "missing_or_conflicting_conditions"


def test_engine_consumers_use_real_manual_evidence(env):
    from src.engine.stage3c_verify import verify_baby_manual
    from src.engine.stage5_explain import explain_manual

    conn, repo, model, doc, published, request, service = env
    assert (
        verify_baby_manual(
            service, request, age_months=8, weight_kg=12, independent_sitting=True
        )["verification_status"]
        == "unknown"
    )
    answer = explain_manual(service, request)
    assert answer["status"] == "success" and "3 kg" in answer["answer"]
    assert (
        conn.execute(
            "SELECT purpose FROM rag.retrieval_run WHERE id=%s", (answer["run_id"],)
        ).fetchone()[0]
        == "recommendation"
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM rag.retrieval_hit WHERE retrieval_run_id=%s AND selected_for_context",
            (answer["run_id"],),
        ).fetchone()[0]
        == 1
    )
    missing = explain_manual(service, replace(request, query="한 손 접기 순서"))
    assert missing["status"] == "no_evidence"
    assert (
        conn.execute(
            "SELECT count(*) FROM rag.retrieval_hit WHERE retrieval_run_id=%s AND selected_for_context",
            (missing["run_id"],),
        ).fetchone()[0]
        == 0
    )
