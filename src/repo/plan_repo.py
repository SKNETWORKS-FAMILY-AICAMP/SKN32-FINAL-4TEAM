"""planning.* 저장소 (develop `da79839` 정렬, P0 v3)."""
from __future__ import annotations

from uuid import UUID
from psycopg.types.json import Jsonb

from src.db.base import Repo
from src.errors import Conflict


class PlanRepo(Repo):
    def create_plan(self, conversation_id: UUID, name: str, owner_user_id: UUID | None) -> UUID:
        row = self._one("INSERT INTO planning.plan (conversation_id, name, owner_user_id) VALUES (%s, %s, %s) RETURNING id", (conversation_id, name, owner_user_id))
        return row["id"]

    def new_revision(self, plan_id: UUID, domain_version_id: UUID, name_snapshot: str) -> UUID:
        row = self._one("""INSERT INTO planning.plan_revision (plan_id, revision_no, domain_version_id, name_snapshot)
            SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s FROM planning.plan_revision WHERE plan_id=%s
            RETURNING id""", (plan_id, domain_version_id, name_snapshot, plan_id))
        return row["id"]

    def published_domain_version(self, code: str) -> dict | None:
        """카테고리 코드의 최신 **활성(active)** domain_version 1행.

        런타임이 실제로 실행에 쓸 규칙을 고르는 유일한 경로다. `domain.status`가
        draft/disabled인 코드는 아직 실행 규칙으로 선택될 수 없다(P1 review R1) —
        baby는 더 이상 스텁이 아니라 실제 구현된 카테고리이므로 db/seed.py가 이제
        active로 심는다. "이 카테고리를 아예 못 쓰게 막는다"는 별도 업무 규칙(계정/기능
        플래그 등)은 여기서 처리할 일이 아니고, 여기는 오직 "게시된 규칙만 실행에 쓴다"만
        보장한다.
        """
        return self._one(
            """SELECT dv.id, dv.domain_id, dv.version_no, dv.definition, dv.attribute_schema, dv.content_hash
               FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id
               WHERE d.code=%s AND d.status='active' ORDER BY dv.version_no DESC LIMIT 1""",
            (code,),
        )

    def bind_domain_version(self, revision_id: UUID, code: str) -> UUID:
        """카테고리 확정 시점에 리비전을 그 카테고리의 게시 도메인 버전으로 묶는다.

        세션 생성 시점에는 아직 카테고리가 없어 임의의(첫) 활성 도메인이 들어가
        있을 수 있다 — 이 호출이 domain_version_id 를 실제 선택된 카테고리 규칙으로
        교체한다. 안 하면 baby 세션이 computer 규칙(또는 그 반대)을 물고 있을 수
        있다(P0 SR07). 이미 이 카테고리로 묶여 있으면 **그 버전을 그대로 유지**한다 —
        같은 카테고리를 다시 선택할 때마다 매번 최신 version_no로 재결합하면, 진행 중인
        초안이 실행 중간에 다른 규칙 버전으로 바뀔 수 있다(P1 review R1); 규칙 갱신은
        새 revision을 통한 명시적 절차로만 반영한다. 이미 확정(draft 아님)된 리비전은
        바꾸지 않는다.
        """
        current = self._one(
            """SELECT r.domain_version_id, r.state, d.code AS current_code
               FROM planning.plan_revision r
               JOIN config.domain_version dv ON dv.id=r.domain_version_id
               JOIN config.domain d ON d.id=dv.domain_id
               WHERE r.id=%s""",
            (revision_id,),
        )
        if current is None:
            raise ValueError("unknown revision_id")
        if current["current_code"] == code:
            return current["domain_version_id"]
        version = self.published_domain_version(code)
        if version is None:
            raise ValueError(f"게시된 도메인이 없습니다: {code}")
        row = self._one(
            """UPDATE planning.plan_revision SET domain_version_id=%s, updated_at=now()
               WHERE id=%s AND state='draft' RETURNING id""",
            (version["id"], revision_id),
        )
        if row is None:
            raise Conflict("확정된 계획의 카테고리는 바꿀 수 없습니다.", code="revision_not_draft")
        return version["id"]

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
                          amount: int, snapshot: dict, *, pack_count: int = 1, currency: str = "KRW") -> UUID:
        """확정 시점에 후보를 얼려서 기록 — 이후 추천 결과가 바뀌어도 리포트는 그대로다."""
        row = self._one(
            "INSERT INTO planning.purchase_line "
            "(revision_id, offer_id, selected_observation_id, pack_count, line_amount, currency, snapshot) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (revision_id, offer_id, offer_observation_id, pack_count, amount, currency, Jsonb(snapshot)),
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

    def get_revision_locked(self, revision_id: UUID) -> dict | None:
        """P5 review R3: lock the revision row and re-read its CURRENT lock_version
        before comparing against a request's If-Match — without this, two concurrent
        edits that both read the same (stale) lock_version can both pass the check.
        The second caller's FOR UPDATE blocks until the first commits, then sees the
        already-bumped version."""
        return self._one("SELECT * FROM planning.plan_revision WHERE id=%s FOR UPDATE", (revision_id,))

    def bump_lock_version(self, revision_id: UUID, expected_version: int) -> int:
        """결과 화면 편집(아이템 선택/수량/시점/교체)마다 낙관적 잠금 버전을 올린다.

        P5 review R3: `WHERE lock_version=expected_version` 조건부 UPDATE — 호출자가
        `get_revision_locked` 로 이미 잠갔다면 이 조건은 항상 참이어야 하지만, 그 잠금
        없이 잘못 호출되는 경로가 생겨도 조용히 남의 버전을 밀어버리지 않는다."""
        from src.errors import Conflict

        row = self._one(
            "UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() "
            "WHERE id=%s AND state='draft' AND lock_version=%s RETURNING lock_version",
            (revision_id, expected_version),
        )
        if row is None:
            raise Conflict("조건이 변경되어 최신 상태가 아닙니다. 최신 결과를 다시 불러오세요.", code="stale_version")
        return row["lock_version"]

    def _lock_revision(self, revision_id: UUID) -> None:
        """조건 쓰기 전체를 리비전 단위로 직렬화한다.

        `SELECT ... FOR UPDATE`로 (revision_id,key) 활성 행만 잠그면, 그 키의 첫 값을 쓰는
        두 동시 요청은 서로 잠글 대상이 없어(행이 아직 없음) 둘 다 "old 없음"으로 판단하고
        INSERT 해 unique 제약(`plan_condition_active_key`)을 위반한다(실측: SS05 동시 PATCH
        재현). 존재가 보장된 plan_revision 행을 먼저 잠그면 같은 리비전에 대한 조건 쓰기가
        전부 직렬화되어 이 경합이 사라진다."""
        self._one("SELECT id FROM planning.plan_revision WHERE id=%s FOR UPDATE", (revision_id,))

    def lock_revision(self, revision_id: UUID) -> None:
        """공개 래퍼 — P2 review R2: persist_baby_requirements도 조건 쓰기와 같은 리비전
        단위 직렬화가 필요하다(동시 두 계산이 같은 슬롯을 동시에 처음 만들면 경합)."""
        self._lock_revision(revision_id)

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
        """슬롯 노드당 requirement 1개 보장 (없으면 생성, 있으면 match_spec 갱신).

        기존 행을 되살릴 때(P2 review R3 — 사라졌던 슬롯이 재요청되면 새 UUID 대신 이
        행을 되쓴다) status도 'active'로 되돌린다 — excluded로 표시됐던 행이 그대로
        비활성으로 남지 않게."""
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
        """P2 review R4: 기존 match_spec을 먼저 읽어야 다른 키를 보존한 채 baby_requirement
        키만 갱신할 수 있다 — ensure_requirement({}) 로 먼저 지웠다가 되쓰는 대신."""
        return self._one(
            "SELECT id, match_spec, status FROM planning.requirement WHERE revision_id=%s AND node_id=%s",
            (revision_id, node_id),
        )

    def set_requirement_totals(self, requirement_id: UUID, *, quantity, unit_code: str,
                               required: bool, match_spec: dict) -> None:
        """requirement.quantity/unit_code/required + match_spec 를 한 번에 갱신한다.

        `ensure_requirement`는 match_spec만 다루므로(신규 행은 quantity=1/unit_code='each'/
        required=true 기본값에 머무른다), 실제 총 필요량을 쓰려면 이 메서드가 필요하다
        (P2 v3 — 유아 persist_baby_requirements 전용, PC 경로는 기본값을 그대로 쓴다).
        status도 'active'로 되돌린다(ensure_requirement와 동일한 되살리기 보장)."""
        self._exec(
            "UPDATE planning.requirement SET quantity=%s, unit_code=%s, required=%s, "
            "match_spec=%s, status='active', updated_at=now() WHERE id=%s",
            (quantity, unit_code, required, Jsonb(match_spec), requirement_id),
        )

    def exclude_requirements_not_in(self, revision_id: UUID, keep_slot_keys: list[str]) -> None:
        """P2 review R3: 이번 계산에서 더 이상 나오지 않는 baby 슬롯의 requirement을
        비활성(excluded)으로 전환한다 — PC 등 baby_requirement이 없는 requirement은
        건드리지 않는다. `keep_slot_keys`가 비어 있으면(모든 baby 슬롯이 사라짐) 전부
        제외한다."""
        self._exec(
            """UPDATE planning.requirement SET status='excluded', updated_at=now()
               WHERE revision_id=%s AND status='active' AND match_spec ? 'baby_requirement'
                 AND node_id IN (
                   SELECT id FROM planning.plan_node
                   WHERE revision_id=%s AND NOT (template_key = ANY(%s)))""",
            (revision_id, revision_id, list(keep_slot_keys)),
        )

    def active_condition_id(self, revision_id: UUID, condition_key: str) -> UUID | None:
        """이 리비전의 활성 plan_condition 1행 id — 보유 출처 참조 검증용(P2 v3)."""
        row = self.active_condition(revision_id, condition_key)
        return None if row is None else row["id"]

    def active_condition(self, revision_id: UUID, condition_key: str) -> dict | None:
        """이 리비전의 활성 plan_condition 1행 (id + value) — P2 review R1: 보유 출처의
        존재뿐 아니라 실제 신고 내용(value)까지 대조해야 caller가 부풀린 owned qty를
        걸러낼 수 있다."""
        return self._one(
            "SELECT id, value FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s "
            "AND status='active'",
            (revision_id, condition_key),
        )

    def load_full(self, revision_id: UUID) -> dict:
        revision = self.get_revision(revision_id)
        if revision is None:
            raise ValueError("revision not found")
        revision["conditions"] = self._all("SELECT condition_key, value, origin FROM planning.plan_condition WHERE revision_id=%s AND status='active' ORDER BY created_at", (revision_id,))
        revision["nodes"] = self._all("SELECT * FROM planning.plan_node WHERE revision_id=%s ORDER BY position, created_at", (revision_id,))
        revision["requirements"] = self._all(
            "SELECT req.*, n.template_key AS slot_key FROM planning.requirement req "
            "JOIN planning.plan_node n ON n.id=req.node_id "
            "WHERE req.revision_id=%s AND req.status='active'", (revision_id,))
        return revision
