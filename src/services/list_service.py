"""리스트(계획) 서비스 — S5-a 확정 · S5-b 리포트.

확정 = plan_revision draft → confirmed (이름·구매예정일·목표가). 비로그인은 로그인 요구.
확정 후 하위 조건·구성 불변(C14). price_watch 생성은 확정 트랜잭션 이후.
"""
from __future__ import annotations

from uuid import UUID


def confirm(list_id: UUID, user_id: UUID, *, name: str, planned_purchase_at, target_amount) -> dict:
    """소유권 확인 → lock_version 재확인 → confirm_revision → feedback(plan_confirmed) 동일 트랜잭션.
    이어서 target_amount 있으면 price_watch 생성.
    """
    raise NotImplementedError


def get_report(list_id: UUID) -> dict:
    """S5-b: 읽기전용 리포트 + 구매 링크 모아보기 + 가격 추적 상태."""
    raise NotImplementedError


def list_conversations(user_id: UUID) -> list[dict]:
    """사이드바 대화 기록 (대화 1건 = 리스트 1건)."""
    raise NotImplementedError
