"""planning.* 저장소."""
from __future__ import annotations

from uuid import UUID
from psycopg.types.json import Jsonb

from src.db.base import Repo


class PlanRepo(Repo):
    def published_domain_version(self, category: str) -> dict | None:
        return self._one(
            "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE d.code=%s AND d.status='active' ORDER BY dv.version_no DESC LIMIT 1", (category,)
        )

    def bind_domain_version(self, revision_id: UUID, category: str) -> None:
        version = self.published_domain_version(category)
        if version is None:
            raise ValueError(f"published_domain_not_found:{category}")
        self._exec("UPDATE planning.plan_revision SET domain_version_id=%s, updated_at=now() WHERE id=%s", (version["id"], revision_id))
    def create_plan(self, conversation_id: UUID, name: str, owner_user_id: UUID | None) -> UUID:
        row = self._one("INSERT INTO planning.plan (conversation_id, name, owner_user_id) VALUES (%s, %s, %s) RETURNING id", (conversation_id, name, owner_user_id))
        return row["id"]

    def new_revision(self, plan_id: UUID, domain_version_id: UUID, name_snapshot: str) -> UUID:
        row = self._one("""INSERT INTO planning.plan_revision (plan_id, revision_no, domain_version_id, name_snapshot)
            SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s FROM planning.plan_revision WHERE plan_id=%s
            RETURNING id""", (plan_id, domain_version_id, name_snapshot, plan_id))
        return row["id"]

    def set_current_revision(self, plan_id: UUID, revision_id: UUID) -> None:
        row = self._one("UPDATE planning.plan SET current_revision_id=%s, updated_at=now() WHERE id=%s AND EXISTS (SELECT 1 FROM planning.plan_revision WHERE id=%s AND plan_id=%s) RETURNING id", (revision_id, plan_id, revision_id, plan_id))
        if row is None:
            raise ValueError("revision does not belong to plan")

    def get_revision(self, revision_id: UUID) -> dict | None:
        return self._one(
            "SELECT r.*, p.name AS plan_name, p.conversation_id, p.owner_user_id, "
            "c.user_id, c.guest_session_hash, d.code AS category "
            "FROM planning.plan_revision r JOIN planning.plan p ON p.id=r.plan_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "JOIN config.domain_version dv ON dv.id=r.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE r.id=%s", (revision_id,))

    def get_current_revision(self, plan_id: UUID) -> dict | None:
        """소프트 삭제된 목록은 제외한다 — 일반 조회·추천·확정·리포트 전부 이 경로를 탄다."""
        return self._one(
            "SELECT r.*, p.name AS plan_name, p.conversation_id, p.owner_user_id, "
            "c.user_id, c.guest_session_hash, d.code AS category "
            "FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "JOIN config.domain_version dv ON dv.id=r.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE p.id=%s AND p.status='active'", (plan_id,))

    def list_owned(self, *, user_id: UUID | None, guest_session_hash: str | None) -> list[dict]:
        """사이드바 "내 장바구니" — 최근 수정순(§D-4-3)."""
        return self._all(
            "SELECT p.id AS list_id, p.name, p.updated_at, pr.id AS revision_id, pr.state, "
            "d.code AS category, "
            "EXISTS(SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.condition_key='category' AND pc.status='active') AS has_category, "
            "EXISTS(SELECT 1 FROM engine.recommendation_run rr WHERE rr.revision_id=pr.id "
            "  AND rr.status='completed') AS has_result "
            "FROM planning.plan p "
            "JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
            "JOIN config.domain_version dv ON dv.id=pr.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "WHERE p.status='active' AND ("
            "  (%s::uuid IS NOT NULL AND c.user_id=%s) OR "
            "  (%s::text IS NOT NULL AND c.guest_session_hash=%s)"
            ") ORDER BY p.updated_at DESC",
            (user_id, user_id, guest_session_hash, guest_session_hash),
        )

    def get_summary(self, list_id: UUID) -> dict | None:
        """PATCH /lists/{id} 응답(ListSummary)용 — list_owned와 같은 모양의 단건 조회."""
        return self._one(
            "SELECT p.id AS list_id, p.name, p.updated_at, pr.id AS revision_id, pr.state, "
            "d.code AS category, "
            "EXISTS(SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.condition_key='category' AND pc.status='active') AS has_category, "
            "EXISTS(SELECT 1 FROM engine.recommendation_run rr WHERE rr.revision_id=pr.id "
            "  AND rr.status='completed') AS has_result "
            "FROM planning.plan p "
            "JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
            "JOIN config.domain_version dv ON dv.id=pr.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE p.id=%s",
            (list_id,),
        )

    def rename(self, list_id: UUID, name: str) -> None:
        self._exec("UPDATE planning.plan SET name=%s, updated_at=now() WHERE id=%s", (name, list_id))

    def soft_delete(self, list_id: UUID) -> None:
        self._exec(
            "UPDATE planning.plan SET status='deleted', deleted_at=now(), updated_at=now() "
            "WHERE id=%s AND status='active'",
            (list_id,),
        )

    def confirm_revision(self, revision_id: UUID, *, confirmed_total, planned_purchase_at,
                         target_amount, memo: str) -> bool:
        """draft → confirmed. 이미 confirmed면 아무것도 안 하고 False."""
        row = self._one(
            "UPDATE planning.plan_revision SET state='confirmed', confirmed_at=now(), "
            "confirmed_total=%s, planned_purchase_at=%s, target_amount=%s, memo=%s, updated_at=now() "
            "WHERE id=%s AND state='draft' RETURNING id",
            (confirmed_total, planned_purchase_at, target_amount, memo, revision_id),
        )
        return row is not None

    def add_purchase_line(self, revision_id: UUID, offer_id: UUID, offer_observation_id: UUID,
                          amount: int, snapshot: dict) -> UUID:
        """확정 시점에 후보를 얼려서 기록 — 이후 추천 결과가 바뀌어도 리포트는 그대로다."""
        row = self._one(
            "INSERT INTO planning.purchase_line "
            "(revision_id, offer_id, selected_observation_id, pack_count, line_amount, snapshot) "
            "VALUES (%s, %s, %s, 1, %s, %s) RETURNING id",
            (revision_id, offer_id, offer_observation_id, amount, Jsonb(snapshot)),
        )
        return row["id"]

    def list_purchase_lines(self, revision_id: UUID) -> list[dict]:
        return self._all(
            "SELECT pack_count, line_amount, snapshot FROM planning.purchase_line "
            "WHERE revision_id=%s ORDER BY created_at",
            (revision_id,),
        )

    def get_lock_version(self, revision_id: UUID) -> int | None:
        row = self._one("SELECT lock_version FROM planning.plan_revision WHERE id=%s", (revision_id,))
        return None if row is None else row["lock_version"]

    def lock_revision(self, revision_id: UUID) -> None:
        """같은 리비전의 조건·요구사항 변경을 하나의 행 잠금으로 직렬화한다."""
        self._one("SELECT id FROM planning.plan_revision WHERE id=%s FOR UPDATE", (revision_id,))

    def upsert_condition(self, revision_id: UUID, key: str, value: dict, origin: str, source_message_id: UUID | None = None) -> UUID:
        self.lock_revision(revision_id)
        old = self._one("SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active' FOR UPDATE", (revision_id, key))
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        row = self._one("INSERT INTO planning.plan_condition (revision_id, condition_key, value, origin, source_message_id, supersedes_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (revision_id, key, Jsonb(value), origin, source_message_id, old["id"] if old else None))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))
        return row["id"]

    def clear_condition(self, revision_id: UUID, key: str) -> None:
        self.lock_revision(revision_id)
        old = self._one(
            "SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active'",
            (revision_id, key),
        )
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))

    def add_node(self, revision_id: UUID, node_type: str, template_key: str, name: str,
                 parent_id: UUID | None = None, position: int = 0) -> UUID:
        row = self._one(
            """INSERT INTO planning.plan_node (revision_id, parent_id, node_type, template_key, name, position)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (revision_id, parent_id, node_type, template_key, name, position),
        )
        return row["id"]

    def ensure_node(self, revision_id: UUID, template_key: str, name: str, *, position: int = 0) -> UUID:
        """template_key 로 슬롯 노드 1개 보장 (없으면 생성)."""
        row = self._one(
            "SELECT id FROM planning.plan_node WHERE revision_id=%s AND template_key=%s",
            (revision_id, template_key),
        )
        if row is not None:
            return row["id"]
        return self.add_node(revision_id, "slot", template_key, name, position=position)

    def ensure_requirement(self, revision_id: UUID, node_id: UUID, match_spec: dict) -> UUID:
        """슬롯 노드당 requirement 1개 보장 (없으면 생성, 있으면 match_spec 갱신)."""
        row = self._one(
            "SELECT id FROM planning.requirement WHERE revision_id=%s AND node_id=%s",
            (revision_id, node_id),
        )
        if row is not None:
            self._exec(
                "UPDATE planning.requirement SET match_spec=%s, status='active' WHERE id=%s",
                (Jsonb(match_spec), row["id"]),
            )
            return row["id"]
        row = self._one(
            """INSERT INTO planning.requirement (revision_id, node_id, match_spec)
            VALUES (%s, %s, %s) RETURNING id""",
            (revision_id, node_id, Jsonb(match_spec)),
        )
        return row["id"]

    def get_requirement_by_node(self, revision_id: UUID, node_id: UUID) -> dict | None:
        return self._one(
            "SELECT id, match_spec, status FROM planning.requirement WHERE revision_id=%s AND node_id=%s",
            (revision_id, node_id),
        )

    def set_requirement_totals(self, requirement_id: UUID, *, quantity, unit_code: str,
                               required: bool, match_spec: dict) -> None:
        self._exec(
            "UPDATE planning.requirement SET quantity=%s, unit_code=%s, required=%s, "
            "match_spec=%s, status='active', updated_at=now() WHERE id=%s",
            (quantity, unit_code, required, Jsonb(match_spec), requirement_id),
        )

    def exclude_requirements_not_in(self, revision_id: UUID, keep_slot_keys: list[str]) -> None:
        self._exec(
            """UPDATE planning.requirement SET status='excluded', updated_at=now()
               WHERE revision_id=%s AND status='active' AND match_spec ? 'baby_requirement'
                 AND node_id IN (
                   SELECT id FROM planning.plan_node
                   WHERE revision_id=%s AND NOT (template_key = ANY(%s)))""",
            (revision_id, revision_id, keep_slot_keys),
        )

    def active_condition(self, revision_id: UUID, condition_key: str) -> dict | None:
        return self._one(
            "SELECT id, value FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s "
            "AND status='active'",
            (revision_id, condition_key),
        )

    def active_condition_id(self, revision_id: UUID, condition_key: str) -> UUID | None:
        row = self.active_condition(revision_id, condition_key)
        return None if row is None else row["id"]

    def load_full(self, revision_id: UUID) -> dict:
        revision = self.get_revision(revision_id)
        if revision is None:
            raise ValueError("revision not found")
        revision["conditions"] = self._all("SELECT condition_key, value, origin FROM planning.plan_condition WHERE revision_id=%s AND status='active' ORDER BY created_at", (revision_id,))
        revision["nodes"] = self._all("SELECT * FROM planning.plan_node WHERE revision_id=%s ORDER BY position, created_at", (revision_id,))
        revision["requirements"] = self._all("SELECT * FROM planning.requirement WHERE revision_id=%s AND status='active'", (revision_id,))
        return revision
