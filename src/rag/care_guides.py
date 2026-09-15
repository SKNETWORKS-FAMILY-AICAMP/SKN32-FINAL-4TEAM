"""부품 사용 가이드·주의 문구 RAG — [3-C] "구매 전 확인"(checks)이 인용하는 근거.

data/pc_care_guides.json(합성 작성, 16개)을 프로세스 시작 시 한 번 임베딩해서 들고 있다가,
품목별 질의(부품명 + 슬롯)로 가장 관련 있는 조각을 코사인 유사도로 찾는다. 문서가 이 정도
개수면 벡터DB 없이 인메모리 검색으로 충분하다 — 별도 서비스도, 스키마도 필요 없다.

검색은 슬롯→문서 고정 매핑이 아니라 실제 임베딩 유사도 비교다 — 같은 슬롯이어도 품목명·
브랜드에 따라 다른 조각이 뽑힐 수 있다. RAG_EMBEDDING_PROVIDER(bedrock, RAG 스키마 삭제로
현재 미사용)와는 무관한 별도 경로 — 이미 동작 확인된 OpenAI 키를 그대로 재사용한다.

MOCK_MODE=1(기본)에서는 실제 호출 없이 결정적 해시 임베딩으로 같은 인터페이스를 유지한다
(src.rag.embedding.LocalHashEmbedder와 같은 방식) — 테스트가 네트워크를 안 타게 한다.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache

from src.config import CARE_GUIDE_EMBEDDING_MODEL, CARE_GUIDES_JSON, MOCK_MODE, OPENAI_API_KEY

_HASH_DIMENSIONS = 256


def _hash_embed(text: str) -> list[float]:
    """MOCK_MODE 전용 — 의미 유사도는 아니지만(어휘 겹침 기반) 같은 입력엔 항상 같은 벡터."""
    vec = [0.0] * _HASH_DIMENSIONS
    for token in text.split():
        idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % _HASH_DIMENSIONS
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _openai_embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(model=CARE_GUIDE_EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in response.data]


def _embed(texts: list[str]) -> list[list[float]]:
    if MOCK_MODE or not OPENAI_API_KEY:
        return [_hash_embed(t) for t in texts]
    return _openai_embed(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


@lru_cache(maxsize=1)
def _load_guides() -> tuple[tuple[dict, ...], tuple[tuple[float, ...], ...]]:
    """가이드 문서 + 임베딩을 프로세스당 한 번만 계산해 들고 있는다(반복 임베딩 호출 방지)."""
    docs = tuple(json.loads(CARE_GUIDES_JSON.read_text(encoding="utf-8")))
    embeddings = tuple(tuple(v) for v in _embed([d["text"] for d in docs]))
    return docs, embeddings


def search_care_guide(query: str, k: int = 1) -> list[dict]:
    """query와 가장 관련 있는 사용 가이드 k개. 각 dict: {id, text, score}. 문서가 없으면 빈 리스트."""
    docs, embeddings = _load_guides()
    if not docs:
        return []
    q = _embed([query])[0]
    scored = sorted(
        ({"id": d["id"], "text": d["text"], "text_en": d.get("text_en"), "score": round(_cosine(q, e), 4)}
         for d, e in zip(docs, embeddings)),
        key=lambda h: h["score"], reverse=True,
    )
    return scored[:k]
