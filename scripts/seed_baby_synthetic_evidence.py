#!/usr/bin/env python3
"""Generate + import the synthetic_demo evidence manifest for all 15 P3 slots
(P3_full_catalog_verification_execution.md phase 2 step 4).

Reads `data/baby/catalog_demo_v1.json` (the seeded synthetic catalog) and, where
one exists, the matching pre-generated manual bundle under
`generated/synthetic_manuals/catalog_demo_v1_r1/<product_key>/` (from
scripts/generate_baby_manual.py). Writes:

  - data/baby/evidence/files/*.json   — one small claim-content file per
    (product_key, claim_key), each carrying the claim value plus an explicit
    "가상 데이터" / not-a-real-safety-verdict notice
  - data/baby/evidence/synthetic-demo-v1.yaml — the manifest referencing those
    files (+ manual bundles) with real SHA-256 hashes

then imports it via scripts/import_baby_evidence.py's import_manifest().

Per required slot this writes exactly two fixtures:
  - a "pass" product: all four required claims (product_identity, safety_route,
    manufacturer_document, recall_status), verified=true, no active recall
  - a "blocked" product: only product_identity is imported (bottle/car_seat use
    their existing dedicated negative fixtures instead — see BLOCKED_OVERRIDES)
    so the candidate resolves to unknown/missing_rule_evidence, or for the
    bottle recall fixture, a verified active_synthetic_recall claim so it
    resolves to fail/active_recall instead.

This is real DB writes through the same import path production evidence would
use — never a test-only CandidateCheck(pass) injection (P3 doc "금지 사항").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from os.path import relpath
from datetime import date
from pathlib import Path

import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_baby_evidence import import_manifest  # noqa: E402
from src.rag.verification import CONDITION_CHECKED_SLOTS, REQUIRED_VERIFICATION_SLOTS  # noqa: E402

CATALOG_PATH = ROOT / "data" / "baby" / "catalog_demo_v1.json"
MANUALS_ROOT = ROOT / "generated" / "synthetic_manuals" / "catalog_demo_v1_r1"
EVIDENCE_DIR = ROOT / "data" / "baby" / "evidence"
FILES_DIR = EVIDENCE_DIR / "files"
MANIFEST_PATH = EVIDENCE_DIR / "synthetic-demo-v1.yaml"
DATASET_VERSION = "baby-demo-v1"
RETRIEVED_ON = "2026-09-14"
NOTICE = "가상 데이터. 실제 제품 안전 인증·리콜 정보가 아닙니다 (synthetic_demo 전용)."

# bottle/car_seat already have hand-authored negative fixtures in the catalog
# (scripts/build_baby_catalog_demo.py curated_fixtures) — reuse those product_keys
# as the "blocked" fixture instead of picking an arbitrary second product.
BLOCKED_OVERRIDES = {
    "bottle": "SYN-BOTTLE-RECALL-001",
    "car_seat": "SYN-CARSEAT-CERT-001",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_claim_file(product_key: str, claim_key: str, value: dict) -> Path:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    path = FILES_DIR / f"{product_key}-{claim_key}.json"
    payload = {
        "is_synthetic": True, "notice": NOTICE, "dataset_version": DATASET_VERSION,
        "product_key": product_key, "claim_key": claim_key, "value": value,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _manual_bundle_for(product_key: str) -> Path | None:
    bundle = MANUALS_ROOT / product_key
    return bundle if (bundle / "manual.md").is_file() and (bundle / "manifest.json").is_file() else None


def _load_catalog_records() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data["records"]


def _pick_products(records: list[dict]) -> dict[str, list[dict]]:
    by_slot: dict[str, list[dict]] = {}
    for r in records:
        by_slot.setdefault(r["slot_key"], []).append(r)
    return by_slot


def _claim(product_key: str, variant_key: str, claim_key: str, value: dict, *, verified: bool,
           manual_bundle: Path | None = None) -> dict:
    if manual_bundle is not None:
        manifest = json.loads((manual_bundle / "manifest.json").read_text(encoding="utf-8"))
        manual_sha = manifest["files"]["manual.md"]
        file_rel = relpath(manual_bundle / "manual.md", EVIDENCE_DIR)
        claim = {
            "claim_key": claim_key, "value": value,
            "source": {"authority": "synthetic_fixture", "url": f"synthetic://{DATASET_VERSION}/{product_key}",
                       "version": DATASET_VERSION},
            "file": file_rel, "sha256": manual_sha, "retrieved_on": RETRIEVED_ON, "verified": verified,
            "manual_bundle": relpath(manual_bundle, EVIDENCE_DIR),
        }
        return claim
    path = _write_claim_file(product_key, claim_key, value)
    return {
        "claim_key": claim_key, "value": value,
        "source": {"authority": "synthetic_fixture", "url": f"synthetic://{DATASET_VERSION}/{product_key}",
                   "version": DATASET_VERSION},
        "file": str(path.relative_to(EVIDENCE_DIR)), "sha256": _sha256(path.read_bytes()),
        "retrieved_on": RETRIEVED_ON, "verified": verified,
    }


def _record_for(product: dict, *, full: bool, recall_active: bool = False) -> dict:
    product_key, variant_key, slot_key = product["product_key"], product["variant_key"], product["slot_key"]
    claims = [_claim(product_key, variant_key, "product_identity",
                     {"manufacturer": product["brand"], "model": product_key}, verified=True)]
    if recall_active:
        claims.append(_claim(product_key, variant_key, "recall_status",
                             {"status": "active_synthetic_recall"}, verified=True))
    elif full:
        claims.append(_claim(product_key, variant_key, "safety_route",
                             {"route": "synthetic_demo_only", "classification": f"{slot_key}_synthetic_demo"},
                             verified=True))
        bundle = _manual_bundle_for(product_key)
        claims.append(_claim(product_key, variant_key, "manufacturer_document", {"has_manual": bundle is not None},
                             verified=True, manual_bundle=bundle))
        claims.append(_claim(product_key, variant_key, "recall_status",
                             {"status": "no_active_recall"}, verified=True))
    return {"product_key": product_key, "variant_key": variant_key, "slot_key": slot_key, "claims": claims}


def build_manifest_records() -> list[dict]:
    by_slot = _pick_products(_load_catalog_records())
    records: list[dict] = []
    for slot in sorted(REQUIRED_VERIFICATION_SLOTS):
        pool = by_slot.get(slot, [])
        if not pool:
            raise RuntimeError(f"no_catalog_products_for_required_slot:{slot}")
        override_key = BLOCKED_OVERRIDES.get(slot)
        blocked_product = next((p for p in pool if p["product_key"] == override_key), None) if override_key else None
        pass_pool = [p for p in pool if p is not blocked_product]
        if not pass_pool:
            raise RuntimeError(f"no_pass_candidate_left_for_slot:{slot}")
        pass_product = pass_pool[0]
        if blocked_product is None:
            blocked_product = pass_pool[1] if len(pass_pool) > 1 else pass_pool[0]
        records.append(_record_for(pass_product, full=True))
        records.append(_record_for(blocked_product, full=False, recall_active=blocked_product is not None
                                   and blocked_product["product_key"] == "SYN-BOTTLE-RECALL-001"))
    return records


def write_manifest() -> Path:
    records = build_manifest_records()
    manifest = {"schema_version": 1, "scope": "synthetic_demo", "dataset_version": DATASET_VERSION, "records": records}
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return MANIFEST_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-version", default=DATASET_VERSION)
    parser.parse_args(argv)  # accepted for CLI-compat with the P3 test command; not yet a variable dataset
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    path = write_manifest()
    with psycopg.connect(dsn) as conn:
        result = import_manifest(conn, path, scope="synthetic_demo")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["skipped_records"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
