"""notification.* 저장소 — price_watch / price_watch_evaluation / notification_event.

S5-b 목표가 추적 → 판정 → 이메일. 같은 범위에 active watch 는 하나(부분 UNIQUE).
이벤트 생성은 도달 상태 갱신과 같은 트랜잭션, 발송은 커밋 후 워커(§53).
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class NotificationRepo(Repo):
    def create_watch(self, revision_id: UUID, *, target_amount, pricing_policy: dict,
                     ends_at, purchase_line_id: UUID | None = None) -> UUID:
        raise NotImplementedError

    def list_active_watches(self, *, due_before=None) -> list[dict]:
        raise NotImplementedError

    def add_evaluation(self, watch_id: UUID, *, evaluated_at, amount, status: str,
                       target_reached: bool | None, breakdown: dict) -> UUID:
        raise NotImplementedError

    def create_event(self, evaluation_id: UUID, user_id: UUID, *, dedupe_key: str,
                     payload_snapshot: dict) -> UUID:
        """UNIQUE(dedupe_key) 로 중복 알림 방지."""
        raise NotImplementedError

    def pending_events(self, limit: int = 100) -> list[dict]:
        raise NotImplementedError

    def mark_sent(self, event_id: UUID) -> None:
        raise NotImplementedError

    def mark_failed(self, event_id: UUID) -> None:
        raise NotImplementedError
