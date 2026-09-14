"""Ingest generated Markdown manuals into assets.* + the external search provider.

`read_manual` is unchanged (pure parsing). `publish_manual`/`ingest_manual` replace
the old `RagRepo.publish_manual` — they write assets.product_material/
material_revision/material_applicability (develop's real, unmerged tables) and push
chunk text to the configured `SearchProvider` instead of PostgreSQL pgvector rows.
"""

from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb

from src.rag.contracts import ManualChunk, ManualDocument

PIPELINE_VERSION = "manual-markdown-v2-external-provider"

_SOURCE_NAME = "가상제품 RAG 테스트 자료"
_SOURCE_TYPE = "derived"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manual(bundle: str | Path) -> ManualDocument:
    """Only manual.md is retrieval content; mapping supplies identity/hash.
    facts.jsonl, snapshots and validation labels are intentionally never read.
    Section grouping preserves ALL eligibility conditions and procedure warnings.
    """
    root = Path(bundle).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((root / "mapping.json").read_text(encoding="utf-8"))
    path = root / "manual.md"
    raw = path.read_bytes()
    if len(raw) > 2_000_000 or b"\x00" in raw:
        raise ValueError("manual_size_or_encoding_invalid")
    sha = digest(raw)
    if sha != manifest["files"]["manual.md"] or sha != mapping["manual_sha256"]:
        raise ValueError("manual_hash_mismatch")
    if digest((root / "mapping.json").read_bytes()) != manifest["files"]["mapping.json"]:
        raise ValueError("mapping_hash_mismatch")
    if manifest.get("is_synthetic") is not True or mapping.get("is_synthetic") is not True:
        raise ValueError("synthetic_bundle_required")
    text = raw.decode("utf-8")
    if "\r" in text:
        raise ValueError("manual_requires_lf_for_stable_locators")
    for key in ("manual_id", "revision", "product_id", "variant_id", "market"):
        if not isinstance(mapping.get(key), str) or not mapping[key].strip():
            raise ValueError(f"missing_manual_metadata:{key}")
    headings = list(re.finditer(r"^## (.+)$", text, re.M))
    chunks = []
    for i, heading in enumerate(headings):
        start = heading.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section_text = text[start:end].rstrip()
        blocks = re.findall(r"<!-- (S\d+-B\d+) -->", section_text)
        if not blocks:
            continue
        if len(section_text) > 12000:
            raise ValueError("section_too_large_requires_reviewed_split")
        locator = {
            "section": heading.group(1), "section_code": blocks[0].split("-")[0],
            "block_ids": blocks, "char_start": start, "char_end": start + len(section_text),
            "line_start": text.count("\n", 0, start) + 1,
        }
        chunks.append(ManualChunk(len(chunks), section_text, locator, digest(section_text.encode())))
    if not chunks:
        raise ValueError("manual_has_no_supported_sections")
    return ManualDocument(
        str(path), text, sha, mapping["manual_id"], mapping["revision"],
        mapping["product_id"], mapping["variant_id"], mapping["market"],
        tuple(chunks), mapping["coverage_status"],
    )


def publish_manual(document: ManualDocument, material_repo, provider, *, reviewed: bool = False) -> dict:
    """Publish one manual revision: file_object + product_material + material_revision
    + material_applicability in PostgreSQL, chunk text in the external provider.

    Deterministic ids (src.ids.stable_id) make a republish of the *same* content
    idempotent and let a seeded catalog row and this manual's product/variant share
    one physical id (P2's existing contract) even though there is no pgvector table
    to co-locate them in anymore.
    """
    from src.ids import stable_id
    from src.rag.provider import ProviderChunk, ProviderDocument
    from src.repo.material_repo import SourceRepo

    if not document.revision.startswith("R") or not document.revision[1:].isdigit():
        raise ValueError("manual_revision_must_be_R_positive_integer")
    revision_no = int(document.revision[1:])
    if revision_no < 1:
        raise ValueError("invalid_revision")

    root = Path(os.getenv("RAG_STORAGE_ROOT", ".rag-files")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    object_path = root / (document.sha256 + ".md")
    data = document.text.encode("utf-8")
    if digest(data) != document.sha256:
        raise ValueError("manual_changed_during_ingestion")
    try:
        with object_path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if digest(object_path.read_bytes()) != document.sha256:
            raise ValueError("stored_object_hash_mismatch")

    product_id, variant_id = stable_id(document.product_key), stable_id(document.variant_key)
    material_id, file_id = stable_id(document.manual_id), stable_id(document.sha256)
    revision_id = stable_id(document.manual_id + ":" + document.revision)
    source_repo = SourceRepo(material_repo.conn)

    with material_repo.conn.transaction():
        material_repo._exec("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(material_id),))
        source_id = source_repo.get_or_create(_SOURCE_NAME, _SOURCE_TYPE)
        # Self-registers a minimal catalog row if none exists yet (stable_id makes
        # this the SAME physical row a separate `seed_baby_catalog.py` run would
        # create/update for this product_key/variant_key — P2's existing contract).
        # A pure RAG-path test must not require the full catalog seed to run first.
        material_repo._exec(
            """INSERT INTO catalog.product (id, name, brand, model, product_type, attributes)
            VALUES (%s,%s,'synthetic',%s,'manual-test',%s)
            ON CONFLICT (id) DO NOTHING""",
            (product_id, document.product_key, document.product_key,
             Jsonb({"corpus": "synthetic", "is_synthetic": True})),
        )
        material_repo._exec(
            """INSERT INTO catalog.product_variant (id, product_id, variant_key)
            VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (variant_id, product_id, document.variant_key),
        )
        existing_material = material_repo._one(
            "SELECT status FROM assets.product_material WHERE id=%s", (material_id,)
        )
        if existing_material is not None and existing_material["status"] == "retired":
            raise ValueError("revoked_material_cannot_republish")
        latest = material_repo._one(
            "SELECT revision_no, status FROM assets.material_revision WHERE material_id=%s "
            "ORDER BY revision_no DESC LIMIT 1", (material_id,),
        )
        if latest is not None:
            if latest["revision_no"] > revision_no:
                raise ValueError("cannot_publish_older_revision")
            if latest["revision_no"] == revision_no and latest["status"] == "revoked":
                raise ValueError("immutable_or_revoked_revision_use_new_revision")

        material_repo._exec(
            """INSERT INTO assets.product_material (id, source_id, title, material_type, status)
            VALUES (%s,%s,%s,'manual','draft')
            ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title""",
            (material_id, source_id, document.manual_id),
        )
        if material_repo._one("SELECT id FROM assets.file_object WHERE id=%s", (file_id,)) is None:
            material_repo._exec(
                """INSERT INTO assets.file_object
                  (id, bucket, object_key, storage_version, original_filename, mime_type, byte_size,
                   sha256, access_scope, use_policy, scan_status, storage_status)
                VALUES (%s,'local',%s,'v1','manual.md','text/markdown',%s,%s,'public',%s,'clean','available')""",
                (file_id, str(object_path), len(data), document.sha256,
                 Jsonb({"allow_rag": True, "allow_excerpt": True, "allow_original": True})),
            )
        if material_repo._one("SELECT id FROM assets.material_revision WHERE id=%s", (revision_id,)) is None:
            material_repo._exec(
                """INSERT INTO assets.material_revision
                  (id, material_id, revision_no, file_object_id, language, issued_at, retrieved_at, status)
                VALUES (%s,%s,%s,%s,'ko',%s,now(),'staged')""",
                (revision_id, material_id, revision_no, file_id, date.today()),
            )
        material_repo.publish_revision(material_id, revision_id)
        material_repo._exec("DELETE FROM assets.material_applicability WHERE revision_id=%s", (revision_id,))
        # `verified` here means "this applicability scope (product/variant/market/
        # corpus) is confirmed correct" — always true once actually published, and a
        # DIFFERENT axis than `reviewed` (whether the manual TEXT has been human
        # fact-checked, carried as ProviderDocument.verified below). Conflating the
        # two would make an as-published-but-unreviewed manual unsearchable at all,
        # not merely ineligible for a `pass` verdict (CONTRACTS: "unreviewed manual
        # cannot produce pass", not "cannot be found").
        material_repo.add_applicability(
            revision_id, product_id, variant_id=variant_id,
            conditions={"domain": "baby", "market": document.market, "corpus": "synthetic"}, verified=True,
        )

    provider_document = ProviderDocument(
        document_id=str(revision_id), material_revision_id=str(revision_id),
        product_id=str(product_id), variant_id=str(variant_id), market=document.market,
        language="ko", corpus="synthetic", file_sha256=document.sha256, verified=reviewed,
        chunks=tuple(
            ProviderChunk(c.ordinal, c.text, c.locator, c.content_hash) for c in document.chunks
        ),
    )
    external_document_id = provider.publish(provider_document)
    return {
        "material_id": str(material_id), "revision_id": str(revision_id),
        "external_document_id": external_document_id, "chunk_count": len(document.chunks),
        "file_sha256": document.sha256,
    }


def ingest_manual(bundle, material_repo, provider, *, reviewed: bool = False) -> dict:
    document = read_manual(bundle)
    return publish_manual(document, material_repo, provider, reviewed=reviewed)
