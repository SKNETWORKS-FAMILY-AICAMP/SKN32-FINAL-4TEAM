"""가격 폴링 워커.

제휴 커머스 API 로 active offer 의 가격·재고를 주기적으로 조회 →
catalog.offer_observation 적재 → active price_watch 판정 → 도달 시 notification_event 생성
(도달 상태 갱신과 같은 트랜잭션, 발송은 notification_worker).
"""
from __future__ import annotations


def run() -> None:
    raise NotImplementedError
