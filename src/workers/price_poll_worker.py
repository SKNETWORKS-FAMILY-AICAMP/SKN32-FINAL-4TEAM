"""가격 폴링 워커.

제휴 커머스 API 로 active offer 의 가격·재고를 주기적으로 조회 →
catalog.offer_observation 적재. 목표가 알림(notification 스키마)은 P0 v3 에서 범위 밖으로
완전히 제거됐다(db_schema_reduction.md).
"""
from __future__ import annotations


def run() -> None:
    raise NotImplementedError
