"""오프라인 리뷰 클렌징 배치 (리뷰 담당 팀원).

수집 → 진위 라벨(메타데이터 우선, 텍스트 AI탐지 최하위 가중치) → 평점 재계산 →
임베딩 → 평가축별 대표 리뷰 → 요약 3건 → evidence.review_summary / review_aggregate 저장.
산출물만 저장, 원문 미저장. dataset 의 합성 표본은 운영 집계에 포함하지 않음(C21).
"""
from __future__ import annotations


def run() -> None:
    raise NotImplementedError
