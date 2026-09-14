"""P3 evidence manifest schema/validator (pure — no DB, no network).

A manifest declares, per (product_key, variant_key, slot_key), the claims that
back that candidate's verification: product_identity, safety_route,
manufacturer_document, recall_status (docs/agent-tasks/baby/
P3_full_catalog_verification_execution.md "증빙 manifest"). This module only
checks the manifest is internally consistent and that every referenced file's
SHA-256 actually matches — it never touches the database or asserts a claim's
truth. `scripts/import_baby_evidence.py` is the DB-writing consumer.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SCOPES = {"synthetic_demo", "production"}
_PRODUCTION_ALLOWED_AUTHORITIES = {"official", "manufacturer"}
# Claim vocabulary mirrors config/baby_verification_rules.yaml's required_claims
# union across all slots. A manifest may carry a subset (a "blocked" fixture
# deliberately omits one), never a claim key outside this set.
_KNOWN_CLAIM_KEYS = {"product_identity", "safety_route", "manufacturer_document", "recall_status"}


class BabyEvidenceManifestError(ValueError):
    """Raised when an evidence manifest fails schema, hash, source or date checks."""


def _fail(code: str, detail: str = "") -> None:
    raise BabyEvidenceManifestError(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Claim:
    claim_key: str
    value: dict
    source_authority: str
    source_url: str
    source_version: str
    file_path: Path          # resolved absolute path, hash already verified
    sha256: str
    retrieved_on: date
    verified: bool
    manual_bundle: Path | None = None  # only set for claim_key == manufacturer_document


@dataclass(frozen=True)
class EvidenceRecord:
    product_key: str
    variant_key: str
    slot_key: str
    claims: tuple[Claim, ...]


@dataclass(frozen=True)
class EvidenceManifest:
    scope: str
    dataset_version: str
    records: tuple[EvidenceRecord, ...]


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_claim(raw: dict, *, scope: str, manifest_dir: Path, today: date) -> Claim:
    claim_key = raw.get("claim_key")
    if claim_key not in _KNOWN_CLAIM_KEYS:
        _fail("unknown_claim_key", str(claim_key))
    value = raw.get("value")
    if value is None or not isinstance(value, dict):
        _fail("claim_value_must_be_object", claim_key)
    source = raw.get("source") or {}
    authority, url, version = source.get("authority"), source.get("url"), source.get("version")
    if not authority or not url or not version:
        _fail("incomplete_claim_source", claim_key)
    if scope == "production":
        if authority not in _PRODUCTION_ALLOWED_AUTHORITIES:
            _fail("production_claim_requires_official_or_manufacturer_source", claim_key)
        if not str(url).startswith("https://"):
            _fail("production_claim_requires_https_url", claim_key)
    elif scope == "synthetic_demo":
        if authority != "synthetic_fixture":
            _fail("synthetic_demo_claim_requires_synthetic_fixture_source", claim_key)
        if not str(url).startswith("synthetic://"):
            _fail("synthetic_demo_claim_requires_synthetic_url", claim_key)
    file_rel = raw.get("file")
    sha256 = raw.get("sha256")
    if not file_rel or not sha256:
        _fail("missing_file_or_sha256", claim_key)
    sha256 = str(sha256).lower()
    if not _SHA256_RE.match(sha256):
        _fail("malformed_sha256", claim_key)
    file_path = (manifest_dir / file_rel).resolve()
    if not file_path.is_file():
        _fail("evidence_file_missing", str(file_path))
    actual_hash = _sha256_of(file_path)
    if actual_hash != sha256:
        _fail("evidence_file_hash_mismatch", f"{claim_key}: expected {sha256} got {actual_hash}")
    retrieved_on_raw = raw.get("retrieved_on")
    try:
        retrieved_on = retrieved_on_raw if isinstance(retrieved_on_raw, date) else date.fromisoformat(str(retrieved_on_raw))
    except ValueError:
        _fail("invalid_retrieved_on", claim_key)
    if retrieved_on > today:
        _fail("future_retrieved_on", claim_key)
    verified = raw.get("verified")
    if not isinstance(verified, bool):
        _fail("verified_must_be_bool", claim_key)
    manual_bundle = None
    if raw.get("manual_bundle"):
        if claim_key != "manufacturer_document":
            _fail("manual_bundle_only_allowed_for_manufacturer_document", claim_key)
        manual_bundle = (manifest_dir / raw["manual_bundle"]).resolve()
        if not manual_bundle.is_dir():
            _fail("manual_bundle_missing", str(manual_bundle))
    return Claim(
        claim_key=claim_key, value=value, source_authority=authority, source_url=str(url),
        source_version=str(version), file_path=file_path, sha256=sha256,
        retrieved_on=retrieved_on, verified=verified, manual_bundle=manual_bundle,
    )


def _validate_record(raw: dict, *, scope: str, manifest_dir: Path, today: date) -> EvidenceRecord:
    product_key, variant_key, slot_key = raw.get("product_key"), raw.get("variant_key"), raw.get("slot_key")
    if not product_key or not variant_key or not slot_key:
        _fail("record_missing_identity", str(raw.get("product_key")))
    claims_raw = raw.get("claims")
    if not claims_raw or not isinstance(claims_raw, list):
        _fail("record_has_no_claims", product_key)
    claims = tuple(_validate_claim(c, scope=scope, manifest_dir=manifest_dir, today=today) for c in claims_raw)
    seen = set()
    for c in claims:
        if c.claim_key in seen:
            _fail("duplicate_claim_key_in_record", f"{product_key}:{c.claim_key}")
        seen.add(c.claim_key)
    return EvidenceRecord(product_key=product_key, variant_key=variant_key, slot_key=slot_key, claims=claims)


def load_and_validate_manifest(path: Path | str, *, today: date | None = None) -> EvidenceManifest:
    """Load + fully validate one evidence manifest. Never touches the DB.

    Every claim's file is read and its SHA-256 checked against the manifest's
    declared hash right here — a caller can trust `claim.sha256` without
    re-reading the file (P3 doc "누락 파일, 해시 불일치 ... 는 적재를 실패시킨다").
    """
    resolved = Path(path).resolve()
    today = today or date.today()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        _fail("unsupported_schema_version")
    scope = raw.get("scope")
    if scope not in _ALLOWED_SCOPES:
        _fail("invalid_scope", str(scope))
    dataset_version = raw.get("dataset_version")
    if not dataset_version:
        _fail("missing_dataset_version")
    records_raw = raw.get("records")
    if not records_raw or not isinstance(records_raw, list):
        _fail("empty_records")
    manifest_dir = resolved.parent
    records = tuple(
        _validate_record(r, scope=scope, manifest_dir=manifest_dir, today=today) for r in records_raw
    )
    return EvidenceManifest(scope=scope, dataset_version=dataset_version, records=records)
