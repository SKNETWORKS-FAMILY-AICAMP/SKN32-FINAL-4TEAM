"""planning.* 저장소."""
from __future__ import annotations

from uuid import UUID
from psycopg.types.json import Jsonb

from src.db.base import Repo


class PlanRepo(Repo):
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
        return self._one("SELECT r.*, p.conversation_id, p.owner_user_id, c.user_id, c.guest_session_hash FROM planning.plan_revision r JOIN planning.plan p ON p.id=r.plan_id JOIN identity.conversation c ON c.id=p.conversation_id WHERE r.id=%s", (revision_id,))

    def get_current_revision(self, plan_id: UUID) -> dict | None:
        return self._one("SELECT r.*, p.conversation_id, p.owner_user_id, c.user_id, c.guest_session_hash FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id JOIN identity.conversation c ON c.id=p.conversation_id WHERE p.id=%s", (plan_id,))

    def get_lock_version(self, revision_id: UUID) -> int | None:
        row = self._one("SELECT lock_version FROM planning.plan_revision WHERE id=%s", (revision_id,))
        return None if row is None else row["lock_version"]

    def upsert_condition(self, revision_id: UUID, key: str, value: dict, origin: str, source_message_id: UUID | None = None) -> UUID:
        old = self._one("SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active' FOR UPDATE", (revision_id, key))
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        row = self._one("INSERT INTO planning.plan_condition (revision_id, condition_key, value, origin, source_message_id, supersedes_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (revision_id, key, Jsonb(value), origin, source_message_id, old["id"] if old else None))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))
        return row["id"]

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
                "UPDATE planning.requirement SET match_spec=%s WHERE id=%s",
                (Jsonb(match_spec), row["id"]),
            )
            return row["id"]
        row = self._one(
            """INSERT INTO planning.requirement (revision_id, node_id, match_spec)
            VALUES (%s, %s, %s) RETURNING id""",
            (revision_id, node_id, Jsonb(match_spec)),
        )
        return row["id"]

    def load_full(self, revision_id: UUID) -> dict:
        revision = self.get_revision(revision_id)
        if revision is None:
            raise ValueError("revision not found")
        revision["conditions"] = self._all("SELECT condition_key, value, origin FROM planning.plan_condition WHERE revision_id=%s AND status='active' ORDER BY created_at", (revision_id,))
        revision["nodes"] = self._all("SELECT * FROM planning.plan_node WHERE revision_id=%s ORDER BY position, created_at", (revision_id,))
        revision["requirements"] = self._all("SELECT * FROM planning.requirement WHERE revision_id=%s AND status='active'", (revision_id,))
        return revision
