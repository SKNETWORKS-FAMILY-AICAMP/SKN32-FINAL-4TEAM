"""Scoped pgvector + keyword evidence search; legacy scenarios remain explicit mocks.

Real calls require exact product scope and a recommendation run. Material access,
usage policy, current revision, corpus and embedding profile are enforced in SQL.
"""

from __future__ import annotations

from typing import Any

from src.config import MOCK_MODE

# 시나리오 로더가 주입하는 미니 코퍼스 (list[dict]: {domain, axis, text, source_url, collected_at})
_MINI_CORPUS: list[dict[str, Any]] = []


def load_mini_corpus(chunks: list[dict[str, Any]]) -> None:
    """시나리오 파일의 corpus 배열을 인메모리 코퍼스로 적재 (데모 전용)."""
    global _MINI_CORPUS
    _MINI_CORPUS = list(chunks)


def evidence_search(
    domain: str, query: str, filters: dict | None = None, k: int = 3
) -> list[dict]:
    """근거 청크 검색.

    Returns:
        각 dict: text(발췌 요약), source_url, collected_at, score. 0건이면 빈 리스트("회색").
    """
    if not MOCK_MODE:
        from src.rag.contracts import RetrievalError, SearchRequest

        allowed = {
            "product_key",
            "variant_key",
            "language",
            "market",
            "corpus",
            "purpose",
            "recommendation_run_id",
            "context",
            "axis",
        }
        supplied = dict(filters or {})
        if set(supplied) - allowed:
            raise ValueError("unsupported_search_filters")
        supplied.pop(
            "axis", None
        )  # Axis describes a query; it cannot bypass product scope.
        request = SearchRequest(domain=domain, query=query, k=k, **supplied)
        result = search_evidence(request)
        if result.status == "error":
            raise RetrievalError(result.error_code)
        return result.hits

    filters = filters or {}
    axis = filters.get("axis", "")
    hits = [
        {
            "text": c["text"],
            "source_url": c.get("source_url", ""),
            "collected_at": c.get("collected_at", ""),
            "score": round(0.9 - i * 0.1, 2),
        }
        for i, c in enumerate(_MINI_CORPUS)
        if c.get("domain") == domain and (not axis or c.get("axis") == axis)
    ]
    print(f"[MOCK] evidence_search(domain={domain!r}, axis={axis!r}) → {len(hits)}건")
    return hits[:k]


def search_evidence(request, *, repo=None, embedder=None):
    """Typed production entry point; does not depend on global MOCK_MODE."""
    from src.rag.embedding import get_embedder
    from src.rag.service import RagService

    embedder = embedder or get_embedder()
    if repo is not None:
        return RagService(repo, embedder).search(request)
    import psycopg
    from src.config import DATABASE_URL
    from src.repo.rag_repo import RagRepo
    from src.rag.contracts import SearchResult

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            return RagService(RagRepo(conn), embedder).search(request)
    except psycopg.Error:
        return SearchResult("error", error_code="retrieval_database_unavailable")
