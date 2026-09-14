"""P3 Phase 2 — evidence manifest validation (pure) + DB import (real PostgreSQL).

DB-backed tests need DATABASE_URL pointed at a disposable, migrated database (see
tests/test_baby_recommendation_http.py's module docstring for the setup commands).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
import yaml

from scripts.import_baby_evidence import import_manifest
from src.ids import stable_id
from src.rag.evidence_manifest import BabyEvidenceManifestError, load_and_validate_manifest
from src.repo.product_repo import ProductRepo

DSN = os.getenv("DATABASE_URL")
pytestmark_db = pytest.mark.skipif(not DSN, reason="set DATABASE_URL to a disposable migrated database")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(path: Path, content: bytes) -> tuple[Path, str]:
    path.write_bytes(content)
    return path, _sha256(content)


def _claim(claim_key: str, value: dict, file_path: Path, sha256: str, *, verified: bool = True,
           authority: str = "synthetic_fixture", url: str = "synthetic://test/x",
           retrieved_on: str = "2026-09-14") -> dict:
    return {
        "claim_key": claim_key, "value": value,
        "source": {"authority": authority, "url": url, "version": "test-v1"},
        "file": file_path.name, "sha256": sha256, "retrieved_on": retrieved_on, "verified": verified,
    }


def _manifest_dict(records: list[dict], *, scope: str = "synthetic_demo") -> dict:
    return {"schema_version": 1, "scope": scope, "dataset_version": "test-v1", "records": records}


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    return path


# ── pure manifest validation (no DB) ────────────────────────────────────────

def test_valid_manifest_loads(tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"x"}')
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "x"}, tmp_path / "identity.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)
    loaded = load_and_validate_manifest(path)
    assert loaded.scope == "synthetic_demo"
    assert loaded.records[0].claims[0].sha256 == sha


def test_hash_mismatch_is_rejected(tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"x"}')
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "x"}, tmp_path / "identity.json",
                          "0" * 64)],  # wrong hash
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="evidence_file_hash_mismatch"):
        load_and_validate_manifest(path)


def test_missing_file_is_rejected(tmp_path):
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [{"claim_key": "product_identity", "value": {"x": 1},
                    "source": {"authority": "synthetic_fixture", "url": "synthetic://x", "version": "v1"},
                    "file": "does_not_exist.json", "sha256": "a" * 64,
                    "retrieved_on": "2026-09-14", "verified": True}],
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="evidence_file_missing"):
        load_and_validate_manifest(path)


def test_future_retrieved_on_is_rejected(tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"x"}')
    future = (date.today() + timedelta(days=10)).isoformat()
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "x"}, tmp_path / "identity.json", sha,
                          retrieved_on=future)],
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="future_retrieved_on"):
        load_and_validate_manifest(path)


def test_synthetic_demo_scope_rejects_non_synthetic_authority(tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"x"}')
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "x"}, tmp_path / "identity.json", sha,
                          authority="official", url="https://example.gov/x")],
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="synthetic_demo_claim_requires_synthetic_fixture_source"):
        load_and_validate_manifest(path)


def test_production_scope_rejects_synthetic_authority(tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"x"}')
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "x"}, tmp_path / "identity.json", sha)],
    }], scope="production")
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="production_claim_requires_official_or_manufacturer_source"):
        load_and_validate_manifest(path)


def test_unknown_claim_key_is_rejected(tmp_path):
    _, sha = _write_file(tmp_path / "x.json", b"{}")
    manifest = _manifest_dict([{
        "product_key": "P1", "variant_key": "P1-V1", "slot_key": "bath",
        "claims": [_claim("made_up_claim", {}, tmp_path / "x.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(BabyEvidenceManifestError, match="unknown_claim_key"):
        load_and_validate_manifest(path)


# ── DB-backed import ─────────────────────────────────────────────────────

@pytest.fixture
def conn():
    if not DSN:
        pytest.skip("set DATABASE_URL to a disposable migrated database")
    with psycopg.connect(DSN) as c:
        yield c
        c.rollback()


def _seed_product(conn, product_key: str, variant_key: str, *, category_code: str = "bath") -> None:
    repo = ProductRepo(conn)
    category_id = repo.resolve_category_id(category_code)
    product_id = repo.upsert_synthetic_product(
        product_key=product_key, name=product_key, brand="test-brand", category_id=category_id,
        product_type=category_code, attributes={"corpus": "synthetic"},
    )
    repo.upsert_synthetic_variant(product_id, variant_key, attributes={}, unit_code="each")


def test_import_creates_product_fact_and_evidence_rows(conn, tmp_path):
    # A unique key per test run (not a fixed "TEST-IMPORT-001") so this test's
    # correctness never depends on whether an earlier run of this same test left
    # committed rows in the disposable DB.
    from uuid import uuid4
    suffix = uuid4().hex[:8]
    product_key, variant_key = f"TEST-IMPORT-{suffix}", f"TEST-IMPORT-{suffix}-V1"
    _seed_product(conn, product_key, variant_key)
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"test"}')
    manifest = _manifest_dict([{
        "product_key": product_key, "variant_key": variant_key, "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "test"}, tmp_path / "identity.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)

    result = import_manifest(conn, path, scope="synthetic_demo")
    assert result["claims_imported"] == 1
    assert result["skipped_records"] == []

    facts = ProductRepo(conn).verified_facts(stable_id(product_key), stable_id(variant_key), scope="synthetic_demo")
    assert "product_identity" in facts
    assert facts["product_identity"]["value"] == {"manufacturer": "test"}
    conn.rollback()


def test_import_is_idempotent_on_unchanged_hash(conn, tmp_path):
    from uuid import uuid4
    suffix = uuid4().hex[:8]
    product_key, variant_key = f"TEST-IMPORT-{suffix}", f"TEST-IMPORT-{suffix}-V1"
    _seed_product(conn, product_key, variant_key)
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"test"}')
    manifest = _manifest_dict([{
        "product_key": product_key, "variant_key": variant_key, "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "test"}, tmp_path / "identity.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)

    # Same open transaction throughout (no commit): a later read/write in this
    # connection already sees the earlier write, and the final fixture rollback
    # leaves the disposable DB clean for the next test run — a mid-test commit
    # would instead leave TEST-IMPORT-002 permanently imported after the first
    # ever run, making the "claims_imported == 1" assertion below fail on rerun.
    first = import_manifest(conn, path, scope="synthetic_demo")
    second = import_manifest(conn, path, scope="synthetic_demo")
    assert first["claims_imported"] == 1
    assert second["claims_imported"] == 0
    assert second["claims_reused"] == 1
    conn.rollback()


def test_import_supersedes_changed_value_instead_of_duplicating(conn, tmp_path):
    from uuid import uuid4
    suffix = uuid4().hex[:8]
    product_key, variant_key = f"TEST-IMPORT-{suffix}", f"TEST-IMPORT-{suffix}-V1"
    _seed_product(conn, product_key, variant_key)
    _, sha1 = _write_file(tmp_path / "v1.json", b'{"manufacturer":"first"}')
    manifest1 = _manifest_dict([{
        "product_key": product_key, "variant_key": variant_key, "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "first"}, tmp_path / "v1.json", sha1)],
    }])
    import_manifest(conn, _write_manifest(tmp_path, manifest1), scope="synthetic_demo")

    _, sha2 = _write_file(tmp_path / "v2.json", b'{"manufacturer":"second"}')
    manifest2 = _manifest_dict([{
        "product_key": product_key, "variant_key": variant_key, "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "second"}, tmp_path / "v2.json", sha2,
                          url="synthetic://test/y")],
    }])
    import_manifest(conn, _write_manifest(tmp_path, manifest2), scope="synthetic_demo")

    facts = ProductRepo(conn).verified_facts(stable_id(product_key), stable_id(variant_key), scope="synthetic_demo")
    assert facts["product_identity"]["value"] == {"manufacturer": "second"}
    superseded = conn.execute(
        "SELECT count(*) FROM catalog.product_fact WHERE product_id=%s AND status='superseded'",
        (stable_id(product_key),),
    ).fetchone()[0]
    assert superseded == 1
    conn.rollback()


def test_import_skips_record_for_uncataloged_product(conn, tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"test"}')
    manifest = _manifest_dict([{
        "product_key": "TEST-NEVER-SEEDED-001", "variant_key": "TEST-NEVER-SEEDED-001-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "test"}, tmp_path / "identity.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)
    result = import_manifest(conn, path, scope="synthetic_demo")
    assert result["claims_imported"] == 0
    assert len(result["skipped_records"]) == 1
    assert result["skipped_records"][0]["product_key"] == "TEST-NEVER-SEEDED-001"
    conn.rollback()


def test_import_rejects_manifest_scope_mismatch(conn, tmp_path):
    _, sha = _write_file(tmp_path / "identity.json", b'{"manufacturer":"test"}')
    manifest = _manifest_dict([{
        "product_key": "TEST-X", "variant_key": "TEST-X-V1", "slot_key": "bath",
        "claims": [_claim("product_identity", {"manufacturer": "test"}, tmp_path / "identity.json", sha)],
    }])
    path = _write_manifest(tmp_path, manifest)
    with pytest.raises(Exception, match="manifest_scope_mismatch"):
        import_manifest(conn, path, scope="production")
