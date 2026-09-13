"""RAG boundaries. Retrieval relevance never implies a verified product fact."""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SearchRequest:
    domain: str
    query: str
    product_key: str
    variant_key: str | None = None
    language: str = "ko"
    market: str = "KR"
    corpus: Literal["synthetic", "real"] = "real"
    purpose: Literal["validation", "recommendation"] = "validation"
    recommendation_run_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    k: int = 5

    def __post_init__(self):
        if self.domain not in {"baby", "computer"} or not self.product_key.strip():
            raise ValueError("domain and exact product_key are required")
        if not self.query.strip() or len(self.query) > 2000:
            raise ValueError("query must contain 1..2000 characters")
        if self.corpus not in {"synthetic", "real"} or self.purpose not in {
            "validation",
            "recommendation",
        }:
            raise ValueError("invalid corpus or purpose")
        if not 1 <= self.k <= 20:
            raise ValueError("k must be 1..20")


@dataclass
class SearchResult:
    status: Literal["success", "no_evidence", "error"]
    hits: list[dict] = field(default_factory=list)
    run_id: str | None = None
    error_code: str | None = None
    profile_key: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ManualChunk:
    ordinal: int
    text: str
    locator: dict
    content_hash: str


@dataclass(frozen=True)
class ManualDocument:
    path: str
    text: str
    sha256: str
    manual_id: str
    revision: str
    product_key: str
    variant_key: str
    market: str
    chunks: tuple[ManualChunk, ...]
    coverage_status: str


class EmbeddingError(RuntimeError):
    pass


class RetrievalError(RuntimeError):
    pass
