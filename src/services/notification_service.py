"""알림 서비스 — 목표가 추적 설정 · 판정 결과 조회.

발송 자체는 notification_worker. 이 서비스는 watch 생성/조회와 판정 이력 조회.
"""
from __future__ import annotations

from uuid import UUID


def create_watch(list_id: UUID, user_id: UUID, *, target_amount, ends_at,
                 purchase_line_id: UUID | None = None) -> dict:
    raise NotImplementedError


def get_watch_status(list_id: UUID, user_id: UUID) -> dict:
    """현재 총액·목표가·도달 여부·최근 판정 시각."""
    raise NotImplementedError
