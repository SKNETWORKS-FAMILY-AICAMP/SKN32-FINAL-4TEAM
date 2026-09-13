"""notification.* 저장소 — price_watch / price_watch_evaluation / notification_event.

S5-b 목표가 추적 → 판정 → 이메일. 같은 범위에 active watch 는 하나(부분 UNIQUE).
이벤트 생성은 도달 상태 갱신과 같은 트랜잭션, 발송은 커밋 후 워커(§53).
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class NotificationRepo(Repo):
    def get_for_revision(self, revision_id: UUID) -> dict | None:
        """purchase_line_id 없는(전체 구성 대상) watch 1건 — revision당 최대 하나(부분 UNIQUE)."""
        return self._one(
            "SELECT * FROM notification.price_watch WHERE revision_id=%s AND purchase_line_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (revision_id,),
        )

    def upsert_active(self, revision_id: UUID, *, target_amount, ends_at) -> dict:
        """활성 watch를 만들거나(없으면) 기존 것을 갱신+재활성화한다. purchase_line_id는 항상 NULL(전체 구성 대상)."""
        existing = self.get_for_revision(revision_id)
        if existing is None:
            return self._one(
                "INSERT INTO notification.price_watch "
                "(revision_id, target_amount, pricing_policy, state, ends_at) "
                "VALUES (%s, %s, '{}'::jsonb, 'active', %s) RETURNING *",
                (revision_id, target_amount, ends_at),
            )
        return self._one(
            "UPDATE notification.price_watch SET target_amount=%s, state='active', ends_at=%s, "
            "updated_at=now() WHERE id=%s RETURNING *",
            (target_amount, ends_at, existing["id"]),
        )

    def pause(self, watch_id: UUID) -> None:
        self._exec(
            "UPDATE notification.price_watch SET state='paused', updated_at=now() WHERE id=%s",
            (watch_id,),
        )

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
