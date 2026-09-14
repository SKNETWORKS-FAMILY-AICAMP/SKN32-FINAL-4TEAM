"""External search provider boundary (develop `da79839` / P3-D3 alignment).

`0011_drop_rag_schema.sql` removed the PostgreSQL `rag` schema (chunks, vectors,
retrieval history) entirely — that state now lives outside PostgreSQL, behind this
Protocol. PostgreSQL keeps only the *selected conclusion* (evidence.evidence rows)
and the material/source records the app already owns (assets.*, evidence.source).

No provider configured -> `get_search_provider()` returns None and every caller must
treat that as an explicit unavailable state (unknown eligibility, no auto-selection),
never a silent fallback to the removed PostgreSQL path and never `no_evidence`
(CONTRACTS: "provider 미설정/타임아웃은 unknown 및 선택 금지").

`LocalFileSearchProvider` is a real, working implementation of this boundary — it
publishes/searches/resolves/revokes against files on disk, genuinely external to
PostgreSQL — usable for local development and CI (D3-01). No third-party search
backend (Elasticsearch/OpenSearch/a hosted vector store, etc.) is configured in this
environment; wiring one in is D3-02 and stays explicitly blocked until a real backend
selection/credentials exist (see reports/P3.md).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol


class ProviderUnavailable(RuntimeError):
    """No search provider is configured. Never substitute the removed PostgreSQL path."""


class ProviderError(RuntimeError):
    """The configured provider was reachable as a concept but the call failed
    (backend error, corruption, timeout-equivalent). Distinct from `no_evidence`."""


@dataclass(frozen=True)
class ProviderChunk:
    ordinal: int
    text: str
    locator: dict
    content_hash: str


@dataclass(frozen=True)
class ProviderDocument:
    """What `publish()` accepts: a full material revision, chunked."""

    document_id: str  # app-chosen, stable per material_revision
    material_revision_id: str
    product_id: str
    variant_id: str | None
    market: str
    language: str
    corpus: Literal["synthetic", "real"]
    file_sha256: str
    chunks: tuple[ProviderChunk, ...]
    verified: bool = False


@dataclass(frozen=True)
class ProviderHit:
    """CONTRACTS: hit 는 provider/외부 hit ID/material_revision_id/product_id/
    variant_id/file_sha256/locator/text/corpus 를 담아야 한다."""

    provider: str
    external_hit_id: str
    material_revision_id: str
    product_id: str
    variant_id: str | None
    file_sha256: str
    locator: dict
    text: str
    corpus: str
    verified: bool
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class SearchProvider(Protocol):
    name: str

    def publish(self, document: ProviderDocument) -> str:
        """Idempotent for the same document_id. Returns the external_document_id."""
        ...

    def search(
        self, *, query: str, product_id: str, variant_id: str | None, market: str,
        language: str, corpus: str, k: int = 5,
    ) -> list[ProviderHit]:
        ...

    def resolve(self, external_hit_id: str) -> ProviderHit | None:
        """None means the hit no longer resolves — revoked, corrupted, or unknown id.
        Never fabricate a hit for an id that does not currently exist."""
        ...

    def revoke(self, external_document_id: str) -> None:
        ...


def _tokens(text: str) -> list[str]:
    # Reuses the project's existing Korean-aware lexical tokenizer (word + character
    # bigrams) instead of a naive whitespace/regex split — Korean particles/endings
    # attach directly to a word ("체중이", "초과하면"), so exact-word overlap alone
    # would miss almost every real match; bigrams recover them without a morphological
    # analyzer.
    from src.rag.text import tokens as _lexical_tokens

    return _lexical_tokens(text)


def _score(query_tokens: list[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(text)
    if not doc_tokens:
        return 0.0
    doc_set = set(doc_tokens)
    overlap = sum(1 for t in set(query_tokens) if t in doc_set)
    return overlap / len(set(query_tokens))


@dataclass
class LocalFileSearchProvider:
    """A real, working external-search backend, file-backed instead of hosted.

    Each published document is one JSON file under `root`. `search` does lexical
    token-overlap scoring (no embeddings — v3 has no vector requirement); this is a
    genuine, functioning implementation of the Protocol, not a canned-response mock.
    """

    root: Path
    name: str = "local-file"

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, document_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", document_id)
        return self.root / f"{safe}.json"

    def publish(self, document: ProviderDocument) -> str:
        path = self._path(document.document_id)
        payload = {
            "document_id": document.document_id,
            "material_revision_id": document.material_revision_id,
            "product_id": document.product_id,
            "variant_id": document.variant_id,
            "market": document.market,
            "language": document.language,
            "corpus": document.corpus,
            "file_sha256": document.file_sha256,
            "verified": document.verified,
            "revoked": False,
            "chunks": [
                {"ordinal": c.ordinal, "text": c.text, "locator": c.locator, "content_hash": c.content_hash}
                for c in document.chunks
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return document.document_id

    def _load(self, document_id: str) -> dict | None:
        path = self._path(document_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ProviderError(f"corrupt_document:{document_id}") from exc

    def search(
        self, *, query: str, product_id: str, variant_id: str | None, market: str,
        language: str, corpus: str, k: int = 5,
    ) -> list[ProviderHit]:
        query_tokens = _tokens(query)
        hits: list[ProviderHit] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ProviderError(f"corrupt_index:{path.name}") from exc
            if doc.get("revoked"):
                continue
            if doc.get("product_id") != product_id:
                continue
            if variant_id is not None and doc.get("variant_id") not in (None, variant_id):
                continue
            if doc.get("market") != market or doc.get("language") != language or doc.get("corpus") != corpus:
                continue
            for chunk in doc.get("chunks", []):
                score = _score(query_tokens, chunk["text"])
                if score <= 0:
                    continue
                hits.append(ProviderHit(
                    provider=self.name,
                    external_hit_id=f"{doc['document_id']}:{chunk['ordinal']}",
                    material_revision_id=doc["material_revision_id"],
                    product_id=doc["product_id"], variant_id=doc.get("variant_id"),
                    file_sha256=doc["file_sha256"], locator=chunk["locator"], text=chunk["text"],
                    corpus=doc["corpus"], verified=bool(doc.get("verified")), score=score,
                ))
        hits.sort(key=lambda h: (-h.score, h.external_hit_id))
        return hits[:k]

    def resolve(self, external_hit_id: str) -> ProviderHit | None:
        document_id, _, ordinal = external_hit_id.rpartition(":")
        if not document_id or not ordinal.isdigit():
            return None
        doc = self._load(document_id)
        if doc is None or doc.get("revoked"):
            return None
        chunk = next((c for c in doc.get("chunks", []) if str(c["ordinal"]) == ordinal), None)
        if chunk is None:
            return None
        return ProviderHit(
            provider=self.name, external_hit_id=external_hit_id,
            material_revision_id=doc["material_revision_id"], product_id=doc["product_id"],
            variant_id=doc.get("variant_id"), file_sha256=doc["file_sha256"],
            locator=chunk["locator"], text=chunk["text"], corpus=doc["corpus"],
            verified=bool(doc.get("verified")),
        )

    def revoke(self, external_document_id: str) -> None:
        path = self._path(external_document_id)
        doc = self._load(external_document_id)
        if doc is None:
            return
        doc["revoked"] = True
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def get_search_provider() -> SearchProvider | None:
    """None means unconfigured — callers must surface an explicit unavailable state.

    `BABY_SEARCH_PROVIDER=local-file` is the only backend implemented in this
    environment (D3-01: provider boundary + unconfigured path). A real third-party
    backend (D3-02) has no product/connection selected here; adding one means adding
    another branch here plus its own credentials, not changing this contract.
    """
    kind = os.getenv("BABY_SEARCH_PROVIDER")
    if not kind:
        return None
    if kind == "local-file":
        root = Path(os.getenv("BABY_SEARCH_STORAGE_ROOT", ".baby-search-index"))
        return LocalFileSearchProvider(root)
    raise ValueError(f"unknown_search_provider:{kind}")
