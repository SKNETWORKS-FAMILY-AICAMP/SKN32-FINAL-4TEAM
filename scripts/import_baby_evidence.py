#!/usr/bin/env python3
"""Load one validated evidence manifest into the DB (P3 execution doc, phase 2).

    uv run python scripts/import_baby_evidence.py \\
      --manifest data/baby/evidence/synthetic-demo-v1.yaml --scope synthetic_demo

Writes, per claim, in one transaction per record:
  - evidence.source (get-or-create)
  - for claim_key=manufacturer_document: assets.file_object/product_material/
    material_revision/material_applicability (via src.repo.material_repo).
    Only `stroller` (src.rag.verification.CONDITION_CHECKED_SLOTS) also pushes
    chunk text to the configured SearchProvider — that machinery exists so
    verify_seat's manual-text search keeps working; the other 14 slots only need
    the document to exist and be published, not be full-text searchable.
  - evidence.evidence (one row per claim)
  - catalog.product_fact (one row per claim, status=verified|proposed from the
    manifest's `verified` flag)

Re-running with an unchanged file hash/source/version/claim/product/variant
combination is a no-op (idempotent) — see `_reuse_existing`. A changed hash or
source_version creates a new product_fact revision and supersedes the old one
(ProductRepo.add_fact), never overwriting the past value in place.

Does not touch scripts/seed_baby_catalog.py's catalog rows — a record whose
product_key/variant_key is not already in the catalog fails loudly rather than
fabricating one (catalog identity is that script's job, not this one's).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.evidence_manifest import Claim, load_and_validate_manifest  # noqa: E402
from src.rag.verification import CONDITION_CHECKED_SLOTS  # noqa: E402
from src.repo.material_repo import EvidenceRepo, MaterialRepo, SourceRepo  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402

_AUTHORITY_TO_SOURCE_TYPE = {
    "official": "public_registry",
    "manufacturer": "manufacturer",
    "synthetic_fixture": "derived",
}


class ImportError_(RuntimeError):
    pass


def _resolve_ids(product_repo: ProductRepo, product_key: str, variant_key: str, *, corpus: str) -> tuple[UUID, UUID]:
    resolved = product_repo.resolve_ids(product_key, variant_key, corpus=corpus)
    if resolved is None:
        raise ImportError_(f"product_or_variant_not_found_in_catalog:{product_key}/{variant_key}")
    return resolved


def _retrieved_at(claim: Claim) -> datetime:
    return datetime(claim.retrieved_on.year, claim.retrieved_on.month, claim.retrieved_on.day, tzinfo=timezone.utc)


def _reuse_existing(product_repo: ProductRepo, product_id: UUID, variant_id: UUID, claim: Claim, *, scope: str) -> bool:
    """True if an unchanged (file hash + source_url + source_version + claim_key +
    scope) verified/proposed fact already exists for this product/variant — the
    import must then be a no-op, not a duplicate revision."""
    existing = product_repo._one(
        """SELECT pf.id FROM catalog.product_fact pf JOIN evidence.evidence ev ON ev.id = pf.evidence_id
        WHERE pf.product_id=%s AND pf.variant_id IS NOT DISTINCT FROM %s AND pf.attribute_key=%s
          AND pf.status IN ('proposed','verified')
          AND ev.status='active' AND ev.facts->>'scope'=%s
          AND ev.citation_snapshot->>'sha256'=%s
          AND ev.citation_snapshot->>'source_url'=%s
          AND ev.citation_snapshot->>'source_version'=%s""",
        (product_id, variant_id, claim.claim_key, scope, claim.sha256, claim.source_url, claim.source_version),
    )
    return existing is not None


def _publish_document_only(material_repo: MaterialRepo, source_id: UUID, *, title: str,
                            claim: Claim, product_id: UUID, variant_id: UUID, scope: str, market: str) -> dict:
    """assets.* rows for a manufacturer_document claim on a slot with NO implemented
    condition-layer text search (i.e. not in CONDITION_CHECKED_SLOTS). No provider
    chunk indexing — nothing currently queries this slot's manual text."""
    file_bytes = claim.file_path.read_bytes()
    file_id = material_repo.register_file(
        bucket="baby-evidence", object_key=str(claim.file_path), storage_version="v1",
        original_filename=claim.file_path.name, mime_type="application/json",
        byte_size=len(file_bytes), sha256=claim.sha256,
        use_policy={"allow_rag": False, "allow_excerpt": True, "allow_original": False},
        access_scope="internal", scan_status="clean", storage_status="available",
    )
    material_id = material_repo.create_material(source_id, title, "certification")
    revision_id = material_repo.add_revision(
        material_id, file_id, language="ko", issued_at=claim.retrieved_on,
        retrieved_at=_retrieved_at(claim), source_url=claim.source_url,
    )
    material_repo.publish_revision(material_id, revision_id)
    material_repo.add_applicability(
        revision_id, product_id, variant_id=variant_id,
        conditions={"domain": "baby", "market": market, "corpus": "synthetic" if scope == "synthetic_demo" else "real", "scope": scope},
        verified=True,
    )
    return {"material_revision_id": str(revision_id), "file_sha256": claim.sha256}


def _publish_document_with_search(material_repo: MaterialRepo, provider, *, claim: Claim) -> dict:
    """manufacturer_document for a CONDITION_CHECKED_SLOTS slot: full ingest_manual
    (file_object/product_material/material_revision/material_applicability +
    provider chunk indexing), so src.rag.verification.verify_seat's manual-text
    search keeps working."""
    from src.rag.ingestion import ingest_manual

    result = ingest_manual(claim.manual_bundle, material_repo, provider, reviewed=claim.verified)
    return {"material_revision_id": result["revision_id"], "file_sha256": result["file_sha256"]}


def import_manifest(conn: psycopg.Connection, manifest_path: Path, *, scope: str, market: str = "KR_DEMO") -> dict:
    manifest = load_and_validate_manifest(manifest_path)
    if manifest.scope != scope:
        raise ImportError_(f"manifest_scope_mismatch: manifest declares {manifest.scope}, --scope was {scope}")
    corpus = "synthetic" if scope == "synthetic_demo" else "real"
    provider = None
    if any(c.claim_key == "manufacturer_document" and r.slot_key in CONDITION_CHECKED_SLOTS
           for r in manifest.records for c in r.claims):
        from src.rag.provider import get_search_provider
        provider = get_search_provider()  # may be None — only raised on if actually needed below

    source_repo = SourceRepo(conn)
    material_repo = MaterialRepo(conn)
    evidence_repo = EvidenceRepo(conn)
    product_repo = ProductRepo(conn)

    imported, reused, skipped_records = 0, 0, []
    for record in manifest.records:
        try:
            product_id, variant_id = _resolve_ids(product_repo, record.product_key, record.variant_key, corpus=corpus)
        except ImportError_ as exc:
            skipped_records.append({"product_key": record.product_key, "reason": str(exc)})
            continue
        for claim in record.claims:
            if _reuse_existing(product_repo, product_id, variant_id, claim, scope=scope):
                reused += 1
                continue
            with conn.transaction():
                source_id = source_repo.get_or_create(
                    f"{claim.source_authority}:{claim.source_version}",
                    _AUTHORITY_TO_SOURCE_TYPE[claim.source_authority],
                    base_url=claim.source_url,
                )
                citation_extra: dict = {}
                if claim.claim_key == "manufacturer_document":
                    if claim.manual_bundle is not None and record.slot_key in CONDITION_CHECKED_SLOTS:
                        if provider is None:
                            raise ImportError_(
                                f"search_provider_unconfigured_for_condition_checked_slot:{record.slot_key}"
                            )
                        citation_extra = _publish_document_with_search(material_repo, provider, claim=claim)
                    else:
                        citation_extra = _publish_document_only(
                            material_repo, source_id, title=f"{record.product_key} manufacturer document",
                            claim=claim, product_id=product_id, variant_id=variant_id, scope=scope, market=market,
                        )
                facts = {
                    "claim_key": claim.claim_key, "scope": scope, "product_key": record.product_key,
                    "variant_key": record.variant_key, "slot_key": record.slot_key,
                    "dataset_version": manifest.dataset_version, "verified": claim.verified,
                }
                citation_snapshot = {
                    "file": str(claim.file_path), "sha256": claim.sha256,
                    "source_url": claim.source_url, "source_version": claim.source_version,
                    **citation_extra,
                }
                evidence_id = evidence_repo.create_material_evidence(
                    source_id, __import__("uuid").uuid4(), facts=facts,
                    citation_snapshot=citation_snapshot, retrieved_at=_retrieved_at(claim),
                )
                product_repo.add_fact(
                    product_id, claim.claim_key, claim.value, evidence_id=evidence_id,
                    variant_id=variant_id, observed_at=_retrieved_at(claim),
                    status="verified" if claim.verified else "proposed",
                )
            imported += 1
    return {
        "scope": scope, "dataset_version": manifest.dataset_version, "records": len(manifest.records),
        "claims_imported": imported, "claims_reused": reused, "skipped_records": skipped_records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scope", choices=("synthetic_demo", "production"), required=True)
    parser.add_argument("--market", default="KR_DEMO")
    args = parser.parse_args(argv)

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required")
    if args.scope == "production" and os.getenv("BABY_ALLOW_PRODUCTION_IMPORT") != "1":
        parser.error(
            "refusing a --scope production import without BABY_ALLOW_PRODUCTION_IMPORT=1 "
            "as an explicit confirmation — this writes real safety-claim rows"
        )
    with psycopg.connect(dsn) as conn:
        result = import_manifest(conn, args.manifest, scope=args.scope, market=args.market)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["skipped_records"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
