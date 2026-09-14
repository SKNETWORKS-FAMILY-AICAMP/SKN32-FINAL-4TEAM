"""P8 RV01 — 리뷰 작성·게시·요약 HTTP 통합 테스트 (실 PostgreSQL + 실 FastAPI, mock 없음).

`DATABASE_URL`이 가리키는, 마이그레이션+유아 카탈로그 시드가 이미 적용된 일회용 DB가 필요하다
(tests/test_baby_recommendation_http.py와 같은 준비):

    export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/<disposable>?sslmode=disable'
    uv run python db/setup_all.py
    uv run python scripts/seed_baby_catalog.py --corpus synthetic --dataset-version baby-demo-v1
    uv run python -m pytest -q tests/test_baby_reviews_http.py

파일 기반 분석 적재(RV02/RV03/RV04)의 순수 검증 로직은 tests/test_review_analysis_files.py
(DB 불필요)에 있다. 여기서는 그 적재 결과가 실제로 evidence.review_aggregate에 반영되고
GET /reviews/summary가 그것을 읽으며, 작성 소유권·게시 멱등성·수정 시 stale 처리가 실제
DB 트랜잭션에서 성립함을 검증한다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set DATABASE_URL to a disposable migrated+baby-seeded database (see module docstring)",
)

if DSN:
    os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local-test")
    from fastapi.testclient import TestClient

    from src.api import app
    from import_review_analysis import apply_plan, validate_and_compute

    FIXTURE = ROOT / "tests" / "fixtures" / "reviews" / "approved_demo" / "manifest.json"
    STROLLER_VARIANT_ID = None  # resolved per-test from the DB (seed ids are stable but let's not hardcode)

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()

    @pytest.fixture()
    def stroller_variant_id(raw_conn) -> str:
        row = raw_conn.execute(
            "SELECT v.id FROM catalog.product_variant v JOIN catalog.product p ON p.id=v.product_id "
            "WHERE p.model='SYN-STROLLER-001' ORDER BY v.variant_key LIMIT 1"
        ).fetchone()
        assert row is not None, "seed_baby_catalog must have created SYN-STROLLER-001"
        return str(row[0])


def _signed_up_client() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"p8-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "P8 Reviewer", "terms_agreed": True, "privacy_agreed": True,
        "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def test_rv01_own_draft_publish_and_reject_other_owner(stroller_variant_id):
    author = _signed_up_client()
    r = author.post("/reviews/part", json={
        "variant_id": stroller_variant_id, "rating": 4, "title": "가볍고 편해요",
        "body": "접이식 구조가 편리했습니다.", "axis_scores": {"내구성": 4},
    })
    assert r.status_code == 201, r.text
    review_id = r.json()["review_id"]
    assert r.json()["status"] == "draft"

    other = _signed_up_client()
    r = other.post(f"/reviews/{review_id}/publish")
    assert r.status_code == 404, "다른 사용자는 이 리뷰의 존재조차 알면 안 된다"

    r = author.post(f"/reviews/{review_id}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"

    # 게시는 멱등 — 다시 불러도 같은 리뷰 버전이 current로 남는다
    r = author.post(f"/reviews/{review_id}/publish")
    assert r.status_code == 200


def test_rv01_invalid_rating_is_rejected_before_reaching_the_service(stroller_variant_id):
    author = _signed_up_client()
    r = author.post("/reviews/part", json={
        "variant_id": stroller_variant_id, "rating": 6, "title": "x", "body": "y", "axis_scores": {},
    })
    assert r.status_code == 422


def test_rv01_unknown_subject_is_not_found():
    author = _signed_up_client()
    r = author.post("/reviews/part", json={
        "variant_id": str(uuid4()), "rating": 5, "title": "x", "body": "y", "axis_scores": {},
    })
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_rv01_editing_a_published_review_marks_its_ready_aggregate_stale(raw_conn, stroller_variant_id):
    """P8 IMPLEMENTATION1: "edits invalidate affected summary/aggregate until
    recomputed, not silently keep stale values." Import an approved file-based
    analysis for this subject first (making it 'ready'), then have the SAME author
    edit their review and confirm the aggregate flips to 'stale'."""
    plans = validate_and_compute(FIXTURE)
    conn = psycopg.connect(DSN, autocommit=False)
    try:
        with conn.transaction():
            result = apply_plan(conn, plans[0], dataset_version="test-rv01")
        conn.commit()
    finally:
        conn.close()
    assert result["status"] == "imported"
    aggregate_id = result["aggregate_id"]
    assert raw_conn.execute(
        "SELECT status FROM evidence.review_aggregate WHERE id=%s", (aggregate_id,)
    ).fetchone()[0] == "ready"

    subject_id = raw_conn.execute(
        "SELECT s.id FROM evidence.review_subject s JOIN catalog.product p ON p.id=s.product_id "
        "WHERE p.model=%s", (plans[0].subject_key,)
    ).fetchone()[0]

    author = _signed_up_client()
    variant_id = raw_conn.execute(
        "SELECT id FROM catalog.product_variant WHERE product_id=%s LIMIT 1", (subject_id,)
    ).fetchone()[0]
    r = author.post("/reviews/part", json={
        "variant_id": str(variant_id), "rating": 3, "title": "재작성", "body": "다시 씁니다.", "axis_scores": {},
    })
    assert r.status_code == 201, r.text

    assert raw_conn.execute(
        "SELECT status FROM evidence.review_aggregate WHERE id=%s", (aggregate_id,)
    ).fetchone()[0] == "stale", "editing a review for the same subject must invalidate its ready aggregate"


def test_rv02_get_summary_reflects_the_imported_analysis_over_http(raw_conn):
    """이미 test_rv01_editing... 등에서 SYN-STROLLER-001 분석이 적재됐을 수 있으니,
    이 테스트는 독립적으로 다시 적재해 계약이 낸 정확한 숫자를 HTTP 응답에서 확인한다."""
    plans = validate_and_compute(FIXTURE)
    conn = psycopg.connect(DSN, autocommit=False)
    try:
        with conn.transaction():
            apply_plan(conn, plans[0], dataset_version="test-rv02")
        conn.commit()
    finally:
        conn.close()

    client = TestClient(app)
    r = client.get("/reviews/summary/SYN-STROLLER-001")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ready" and j["analysis_version"]
    assert j["total_count"] == 3 and j["excluded_count"] == 1
    assert j["rating_raw"] == pytest.approx(11 / 3, abs=1e-4)
    assert j["rating_refined"] == 5.0
    assert j["excluded_ratio"] == pytest.approx(1 / 3, abs=1e-4)
    assert any(s["source"].startswith("파일 기반") for s in j["summaries"])
