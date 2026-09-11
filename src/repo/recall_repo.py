"""리콜 이력 큐레이션 룩업 ([3-A] 유아 하드 필터가 사용).

데모: 큐레이션 목록에서 브랜드/모델 매칭. 최종: 공공 안전정보 API 동기화.
유아 도메인 전용 — 컴퓨터 경로에서는 호출되지 않는다. 데이터 확보 전까지 스텁.
"""
from __future__ import annotations

from typing import Any

# TODO: 유아 상품 카탈로그 확보 시 큐레이션 채움
_CURATED_RECALLS: list[dict[str, Any]] = [
    # {"brand": "...", "model": "...", "recall_date": "2025-03", "reason": "질식 위험",
    #  "grade": "자발적 리콜", "source_url": "..."}
]


def lookup_recall(brand: str = "", model: str = "", product_name: str = "") -> list[dict]:
    """제품이 리콜 목록에 있으면 매칭 항목 반환. 없으면 빈 리스트.

    Returns:
        각 dict: brand, model, recall_date, reason, grade, source_url
    """
    q = f"{brand} {model} {product_name}".lower()
    hits = []
    for r in _CURATED_RECALLS:
        key = f"{r.get('brand','')} {r.get('model','')}".lower().strip()
        if key and key in q:
            hits.append(dict(r))
    return hits
