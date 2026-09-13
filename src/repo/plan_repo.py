"""planning.* 저장소 (P0 v3: plan_node 제거, requirement.slot_key 로 대체)."""
from __future__ import annotations

from uuid import UUID
from psycopg.types.json import Jsonb

from src.db.base import Repo
from src.errors import Conflict


class PlanRepo(Repo):
    def create_plan(self, conversation_id: UUID, name: str, owner_user_id: UUID | None) -> UUID:
        row = self._one("INSERT INTO planning.plan (conversation_id, name, owner_user_id) VALUES (%s, %s, %s) RETURNING id", (conversation_id, name, owner_user_id))
        return row["id"]

    _DOMAIN_COLS = "SELECT id, code, status, current_version_no, definition, attribute_schema, content_hash FROM config.domain"

    def _domain_snapshot(self, domain: dict) -> Jsonb:
        return Jsonb({
            "version_no": domain["current_version_no"],
            "definition": domain["definition"],
            "attribute_schema": domain["attribute_schema"],
            "content_hash": domain["content_hash"],
        })

    def published_domain(self, code: str) -> dict | None:
        """카테고리 코드로 게시(active) 도메인 1행. 런타임은 항상 이 경로로만 규칙을 고른다."""
        return self._one(f"{self._DOMAIN_COLS} WHERE code=%s AND status='active'", (code,))

    def new_revision(self, plan_id: UUID, domain_id: UUID, name_snapshot: str) -> UUID:
        """domain_snapshot 은 생성 시점 config.domain 정의를 그대로 얼려 담는다 —
        이후 규칙이 바뀌어도 이미 만든 리비전의 스냅샷은 바뀌지 않는다."""
        domain = self._one(f"{self._DOMAIN_COLS} WHERE id=%s", (domain_id,))
        if domain is None:
            raise ValueError("unknown domain_id")
        row = self._one("""INSERT INTO planning.plan_revision (plan_id, revision_no, domain_id, domain_snapshot, name_snapshot)
            SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s, %s FROM planning.plan_revision WHERE plan_id=%s
            RETURNING id""", (plan_id, domain_id, self._domain_snapshot(domain), name_snapshot, plan_id))
        return row["id"]

    def bind_domain(self, revision_id: UUID, code: str) -> UUID:
        """카테고리 확정 시점에 리비전을 그 카테고리의 게시 도메인으로 다시 묶는다.

        세션 생성 시점에는 아직 카테고리가 없어 임시 도메인이 들어가 있다. 이 호출이
        domain_id 와 domain_snapshot 을 실제 사용될 규칙으로 교체한다 — 이걸 빼먹으면
        baby 세션이 computer 규칙을 스냅샷으로 들고 다니게 된다(P0 SR07).
        이미 확정(draft 아님)된 리비전은 스냅샷을 바꾸지 않는다.
        """
        domain = self.published_domain(code)
        if domain is None:
            raise ValueError(f"게시된 도메인이 없습니다: {code}")
        row = self._one(
            """UPDATE planning.plan_revision SET domain_id=%s, domain_snapshot=%s, updated_at=now()
               WHERE id=%s AND state='draft' AND domain_id IS DISTINCT FROM %s RETURNING id""",
            (domain["id"], self._domain_snapshot(domain), revision_id, domain["id"]),
        )
        if row is None:
            current = self._one("SELECT domain_id, state FROM planning.plan_revision WHERE id=%s", (revision_id,))
            if current is None:
                raise ValueError("unknown revision_id")
            if current["domain_id"] != domain["id"] and current["state"] != "draft":
                raise Conflict("확정된 계획의 카테고리는 바꿀 수 없습니다.", code="revision_not_draft")
        return domain["id"]

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

    def _lock_revision(self, revision_id: UUID) -> None:
        """조건 쓰기 전체를 리비전 단위로 직렬화한다.

        `SELECT ... FOR UPDATE`로 (revision_id,key) 활성 행만 잠그면, 그 키의 첫 값을 쓰는
        두 동시 요청은 서로 잠글 대상이 없어(행이 아직 없음) 둘 다 "old 없음"으로 판단하고
        INSERT 해 unique 제약(`plan_condition_active_key`)을 위반한다(실측: SS05 동시 PATCH
        재현). 존재가 보장된 plan_revision 행을 먼저 잠그면 같은 리비전에 대한 조건 쓰기가
        전부 직렬화되어 이 경합이 사라진다."""
        self._one("SELECT id FROM planning.plan_revision WHERE id=%s FOR UPDATE", (revision_id,))

    def upsert_condition(self, revision_id: UUID, key: str, value: dict, origin: str, source_message_id: UUID | None = None) -> UUID:
        self._lock_revision(revision_id)
        old = self._one("SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active'", (revision_id, key))
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        row = self._one("INSERT INTO planning.plan_condition (revision_id, condition_key, value, origin, source_message_id, supersedes_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (revision_id, key, Jsonb(value), origin, source_message_id, old["id"] if old else None))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))
        return row["id"]

    def clear_condition(self, revision_id: UUID, key: str) -> None:
        """PATCH .../slot 의 value=null 계약: 새 값을 넣지 않고 활성 행을 지운다 → 다시 missing.

        `upsert_condition`과 달리 대체 행을 만들지 않는다 — "명시적으로 none" 과 "아예 미응답"을
        구분하려면 빈 리스트([])는 answered 로 유지하고, 진짜 clear 는 행 자체가 없어야 한다.
        """
        self._lock_revision(revision_id)
        old = self._one(
            "SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active'",
            (revision_id, key),
        )
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))

    def ensure_requirement(self, revision_id: UUID, slot_key: str, match_spec: dict, *,
                           group_key: str | None = None, position: int = 0) -> UUID:
        """슬롯 키(=카테고리 yaml 이 고정으로 정의) 로 requirement 1개 보장. 노드 테이블 없이 직접 관리(P0 v3)."""
        row = self._one(
            "SELECT id FROM planning.requirement WHERE revision_id=%s AND slot_key=%s",
            (revision_id, slot_key),
        )
        if row is not None:
            self._exec(
                "UPDATE planning.requirement SET match_spec=%s, group_key=%s, position=%s WHERE id=%s",
                (Jsonb(match_spec), group_key, position, row["id"]),
            )
            return row["id"]
        row = self._one(
            """INSERT INTO planning.requirement (revision_id, slot_key, group_key, position, match_spec)
            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (revision_id, slot_key, group_key, position, Jsonb(match_spec)),
        )
        return row["id"]

    def load_full(self, revision_id: UUID) -> dict:
        revision = self.get_revision(revision_id)
        if revision is None:
            raise ValueError("revision not found")
        revision["conditions"] = self._all("SELECT condition_key, value, origin FROM planning.plan_condition WHERE revision_id=%s AND status='active' ORDER BY created_at", (revision_id,))
        revision["requirements"] = self._all("SELECT * FROM planning.requirement WHERE revision_id=%s AND status='active' ORDER BY position, created_at", (revision_id,))
        return revision
