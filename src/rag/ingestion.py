"""Ingest generated Markdown manuals without indexing answer ledgers."""

from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

from src.rag.contracts import ManualChunk, ManualDocument

PIPELINE_VERSION = "manual-markdown-v1"


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
    if (
        digest((root / "mapping.json").read_bytes())
        != manifest["files"]["mapping.json"]
    ):
        raise ValueError("mapping_hash_mismatch")
    if (
        manifest.get("is_synthetic") is not True
        or mapping.get("is_synthetic") is not True
    ):
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
            "section": heading.group(1),
            "section_code": blocks[0].split("-")[0],
            "block_ids": blocks,
            "char_start": start,
            "char_end": start + len(section_text),
            "line_start": text.count("\n", 0, start) + 1,
        }
        chunks.append(
            ManualChunk(
                len(chunks), section_text, locator, digest(section_text.encode())
            )
        )
    if not chunks:
        raise ValueError("manual_has_no_supported_sections")
    return ManualDocument(
        str(path),
        text,
        sha,
        mapping["manual_id"],
        mapping["revision"],
        mapping["product_id"],
        mapping["variant_id"],
        mapping["market"],
        tuple(chunks),
        mapping["coverage_status"],
    )


def ingest_manual(bundle, repo, embedder, *, reviewed: bool = False) -> dict:
    document = read_manual(bundle)
    vectors = embedder.embed([chunk.text for chunk in document.chunks])
    if len(vectors) != len(document.chunks):
        raise ValueError("incomplete_embedding_batch")
    return repo.publish_manual(document, vectors, embedder, reviewed=reviewed)


def run_ingestion(ingestion_id: UUID, *, conn=None, embedder=None) -> None:
    from src.rag.embedding import get_embedder
    from src.repo.rag_repo import RagRepo

    if conn is None:
        import psycopg
        from src.config import DATABASE_URL

        with psycopg.connect(DATABASE_URL, connect_timeout=5) as connection:
            return run_ingestion(ingestion_id, conn=connection, embedder=embedder)
    RagRepo(conn).process_job(ingestion_id, embedder or get_embedder())
