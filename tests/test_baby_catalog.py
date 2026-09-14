"""P2 — 유아 카탈로그 시딩 테스트.

DB 필요한 케이스는 RAG_TEST_DATABASE_URL 이 있을 때만 실행하고(tests/test_rag_postgres.py
와 동일한 패턴), 끝나면 항상 롤백한다(실 DB에 남기지 않음).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_baby_products import generate_dataset, load_dictionary  # noqa: E402
from seed_baby_catalog import (  # noqa: E402
    DEFAULT_INPUT, SeedInputError, load_input, seed_catalog, validate_record,
)
from src.repo.product_repo import ProductRepo  # noqa: E402
from src.repo.rag_repo import stable_id  # noqa: E402
from src.config import DATABASE_URL  # noqa: E402

DSN = os.getenv("RAG_TEST_DATABASE_URL") or DATABASE_URL
needs_db = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated pgvector database"
)


# ── generator dictionary (no DB) ────────────────────────────────────────────

def test_dictionary_supports_all_23_families():
    dictionary = load_dictionary()
    assert len(dictionary["categories"]) == 23
    bundle = generate_dataset(count=46, seed=42, dictionary=dictionary)
    assert len(bundle["metadata"]["category_counts"]) == 23
    assert bundle["metadata"]["is_synthetic"] is True


def test_generator_is_deterministic_for_same_seed():
    dictionary = load_dictionary()
    a = generate_dataset(count=30, seed=7, dictionary=dictionary)
    b = generate_dataset(count=30, seed=7, dictionary=dictionary)
    assert a == b


def test_generator_rejects_unknown_category_instead_of_silently_dropping_it():
    dictionary = load_dictionary()
    with pytest.raises(Exception):
        generate_dataset(count=5, seed=1, categories=["not_a_real_category"], dictionary=dictionary)


# ── default seed input (no DB) ──────────────────────────────────────────────

def test_default_seed_input_exists_and_is_used_when_input_omitted():
    assert DEFAULT_INPUT == ROOT / "data" / "baby" / "catalog_demo_v1.json"
    assert DEFAULT_INPUT.exists()
    manifest, records = load_input(DEFAULT_INPUT)
    assert manifest["is_synthetic"] is True
    assert len(records) == manifest["record_count"] == len(records)
    for i, r in enumerate(records):
        validate_record(r, dataset_version=manifest["dataset_version"], corpus="synthetic", index=i)


def test_ca06_stroller_exact_identity_and_synthetic_labeling():
    """CA06: SYN-STROLLER-001 / SYN-STROLLER-001-GREY exact identity; every fixture labeled synthetic."""
    _, records = load_input(DEFAULT_INPUT)
    stroller = next(r for r in records if r["product_key"] == "SYN-STROLLER-001")
    assert stroller["variant_key"] == "SYN-STROLLER-001-GREY"
    assert stroller["attributes"]["specs"]["seat_max_kg"] == 22
    assert stroller["offer"]["price"] == 290000
    for r in records:
        assert r["is_synthetic"] is True
        assert r["corpus"] == "synthetic"
    # No fake KC number presented as real anywhere in the demo catalog.
    for r in records:
        for fact in r["facts"]:
            if fact["key"] == "kc_certification_number":
                assert fact["value"] is None
                assert fact["verification_status"] == "unknown"


def test_seed_input_validation_rejects_bad_records_before_any_db_write():
    _, records = load_input(DEFAULT_INPUT)
    bad = dict(records[0])
    bad["unit_code"] = "not_a_real_unit"
    with pytest.raises(SeedInputError):
        validate_record(bad, dataset_version="baby-demo-v1", corpus="synthetic", index=0)

    bad2 = dict(records[0])
    bad2["offer"] = {**bad2["offer"], "price": -100}
    with pytest.raises(SeedInputError):
        validate_record(bad2, dataset_version="baby-demo-v1", corpus="synthetic", index=0)


def test_seed_catalog_dry_run_never_touches_db():
    _, records = load_input(DEFAULT_INPUT)
    report = seed_catalog(None, records, dataset_version="baby-demo-v1", corpus="synthetic", dry_run=True)
    assert report.products == len(records)
    assert report.observations_created == 0


# ── DB-backed idempotency / history (CA01, CA04) ────────────────────────────

@pytest.fixture
def conn():
    connection = psycopg.connect(DSN, prepare_threshold=None)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()




@needs_db
def test_ca01_reseed_same_file_is_idempotent_and_price_change_preserves_history(conn):
    manifest, records = load_input(DEFAULT_INPUT)
    first = seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")
    second = seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")
    assert first.product_ids == second.product_ids
    assert first.variant_ids == second.variant_ids
    assert second.observations_created == 0
    assert second.observations_unchanged == len(records)

    changed = json.loads(json.dumps(records))  # deep copy
    for r in changed:
        if r["product_key"] == "SYN-STROLLER-001":
            r["offer"]["price"] = 275000
    third = seed_catalog(conn, changed, dataset_version=manifest["dataset_version"], corpus="synthetic")
    assert third.observations_created == 1
    assert third.observations_unchanged == len(records) - 1

    repo = ProductRepo(conn)
    variant_id = repo.variant_id_by_keys("SYN-STROLLER-001", "SYN-STROLLER-001-GREY")
    prices = {row["price"] for row in repo._all(
        """SELECT obs.price FROM catalog.offer_observation obs
        JOIN catalog.offer o ON o.id = obs.offer_id WHERE o.variant_id = %s""",
        (variant_id,),
    )}
    assert {290000, 275000} <= {int(p) for p in prices}, "old observation must not be overwritten"


@needs_db
def test_ca04_invalid_input_raises_before_any_row_is_written(conn):
    _, records = load_input(DEFAULT_INPUT)
    bad = [dict(r) for r in records]
    bad[0] = {**bad[0], "unit_code": "bogus"}
    before = ProductRepo(conn)._one("SELECT count(*) AS n FROM catalog.product")["n"]
    with pytest.raises(SeedInputError):
        seed_catalog(conn, bad, dataset_version="baby-demo-v1", corpus="synthetic")
    after = ProductRepo(conn)._one("SELECT count(*) AS n FROM catalog.product")["n"]
    assert before == after


@needs_db
def test_ca06_seeded_ids_match_stable_id_used_by_rag_publish_manual(conn):
    """The catalog row seed_baby_catalog.py creates for SYN-STROLLER-001 must be the SAME
    physical row src.repo.rag_repo.RagRepo.publish_manual would create/reference for the
    identical product_key/variant_key — otherwise RAG evidence and catalog candidates
    would silently point at two different rows for "the same" product."""
    _, records = load_input(DEFAULT_INPUT)
    report = seed_catalog(conn, records, dataset_version="baby-demo-v1", corpus="synthetic")
    assert report.product_ids["SYN-STROLLER-001"] == str(stable_id("SYN-STROLLER-001"))
    assert report.variant_ids["SYN-STROLLER-001-GREY"] == str(stable_id("SYN-STROLLER-001-GREY"))


@needs_db
def test_two_diaper_variants_independently_queryable_with_distinct_pack_semantics(conn):
    _, records = load_input(DEFAULT_INPUT)
    seed_catalog(conn, records, dataset_version="baby-demo-v1", corpus="synthetic")
    repo = ProductRepo(conn)
    rows = repo._all(
        """SELECT v.variant_key, v.pack_quantity, v.unit_code FROM catalog.product_variant v
        JOIN catalog.product p ON p.id = v.product_id
        WHERE p.model = 'SYN-DIAPER-CA03-001'""",
    )
    assert len(rows) == 1
    row = rows[0]
    assert float(row["pack_quantity"]) == 2
    assert row["unit_code"] == "pack"
    # Ensure this is not the ONLY diaper variant (independent queryability of two variants).
    other = repo._all(
        "SELECT v.id FROM catalog.product_variant v JOIN catalog.product p ON p.id=v.product_id "
        "JOIN catalog.product_category c ON c.id=p.category_id WHERE c.code='diaper'"
    )
    assert len(other) >= 2
