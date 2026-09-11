"""planning.* 저장소 — plan / plan_revision / plan_condition / plan_node /
requirement / owned_item / purchase_line / fulfillment_allocation.

교차 무결성 (명세서 §6): C01(plan↔revision), C02(node·req·alloc↔revision) 는 복합 FK 로 DB 가 강제.
C14 게시/확정 불변성, C15 낙관적 잠금(lock_version), C16 배분 합계·통화 = 이 계층의 트랜잭션에서 검증.
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class PlanRepo(Repo):
    # ── plan / revision ──
    def create_plan(self, conversation_id: UUID, name: str, owner_user_id: UUID | None) -> UUID:
        """planning.plan INSERT. current_revision_id 는 NULL, 이후 set_current_revision."""
        raise NotImplementedError

    def new_revision(self, plan_id: UUID, domain_version_id: UUID, name_snapshot: str) -> UUID:
        """다음 revision_no 로 draft 버전 생성."""
        raise NotImplementedError

    def set_current_revision(self, plan_id: UUID, revision_id: UUID) -> None:
        raise NotImplementedError

    def get_revision(self, revision_id: UUID) -> dict | None:
        raise NotImplementedError

    def confirm_revision(
        self, revision_id: UUID, *, expected_lock_version: int,
        name: str, planned_purchase_at, confirmed_total,
    ) -> None:
        """draft → confirmed. lock_version 재확인(C15), 하위 조건·구성 불변(C14)."""
        raise NotImplementedError

    # ── condition / node / requirement ──
    def upsert_condition(self, revision_id: UUID, key: str, value: dict, origin: str,
                         source_message_id: UUID | None = None) -> UUID:
        """활성 조건 UNIQUE(revision_id,key). 값 변경은 supersede."""
        raise NotImplementedError

    def add_node(self, revision_id: UUID, node_type: str, template_key: str, name: str,
                 parent_id: UUID | None = None, position: int = 0) -> UUID:
        """C03: parent 는 같은 revision. 초기 깊이 제한은 여기서 거절."""
        raise NotImplementedError

    def add_requirement(self, revision_id: UUID, node_id: UUID, *, quantity=1,
                        required: bool = True, match_spec: dict | None = None) -> UUID:
        raise NotImplementedError

    def add_owned_item(self, revision_id: UUID, *, variant_id: UUID | None,
                       item_spec: dict, quantity=1) -> UUID:
        raise NotImplementedError

    # ── purchase / allocation ──
    def add_purchase_line(self, revision_id: UUID, offer_id: UUID,
                          selected_observation_id: UUID, *, pack_count: int,
                          line_amount, snapshot: dict) -> UUID:
        raise NotImplementedError

    def allocate(self, revision_id: UUID, requirement_id: UUID, *,
                 purchase_line_id: UUID | None = None, owned_item_id: UUID | None = None,
                 quantity=1) -> UUID:
        """C16: 배분 합계·통화 일관성 검증 후 삽입."""
        raise NotImplementedError

    def load_full(self, revision_id: UUID) -> dict:
        """S4 렌더용: nodes + requirements + purchase_lines + allocations 한 번에."""
        raise NotImplementedError
