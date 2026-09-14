"""engine recommendation 실행 결과 저장소."""
from __future__ import annotations
from uuid import UUID
from psycopg.types.json import Jsonb
from src.db.base import Repo
from src.errors import Conflict

class EngineRepo(Repo):
    def start_run(self, revision_id: UUID, domain_version_id: UUID, *, input_snapshot: dict, input_hash: str, draft_lock_version: int, engine_versions: dict) -> UUID:
        row = self._one("""INSERT INTO engine.recommendation_run (revision_id, domain_version_id, input_snapshot, input_hash, draft_lock_version, engine_versions, status)
        VALUES (%s,%s,%s,%s,%s,%s,'running') RETURNING id""", (revision_id, domain_version_id, Jsonb(input_snapshot), input_hash, draft_lock_version, Jsonb(engine_versions)))
        return row["id"]
    def complete_run(self, run_id: UUID, status: str = "completed") -> None:
        if status not in {"completed", "failed", "stale"}: raise ValueError("invalid terminal run status")
        run = self._one("SELECT r.*, p.lock_version FROM engine.recommendation_run r JOIN planning.plan_revision p ON p.id=r.revision_id WHERE r.id=%s FOR UPDATE", (run_id,))
        if run is None: raise ValueError("recommendation run not found")
        if run["status"] != "running": raise Conflict("추천 실행이 이미 종료되었습니다.")
        terminal = "stale" if status == "completed" and run["lock_version"] != run["draft_lock_version"] else status
        self._exec("UPDATE engine.recommendation_run SET status=%s, completed_at=now(), updated_at=now() WHERE id=%s", (terminal, run_id))
        if terminal == "stale": raise Conflict("추천 도중 조건이 변경되었습니다.")
    def add_candidate(self, run_id: UUID, requirement_id: UUID, variant_id: UUID, *, result: str, score=None, score_method_version: str | None = None, reason: str | None = None, offer_observation_id: UUID | None = None) -> UUID:
        # PostgreSQL has individual FKs for run and requirement, but cannot express
        # that they belong to the same revision with those columns alone.
        scope = self._one(
            """SELECT 1 FROM engine.recommendation_run run
               JOIN planning.requirement req ON req.id=%s
               WHERE run.id=%s AND req.revision_id=run.revision_id""",
            (requirement_id, run_id),
        )
        if scope is None:
            raise ValueError("cross_revision_candidate_rejected")
        reason_status = "ready" if reason is not None else "pending"
        row=self._one("""INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)); return row["id"]
    def link_candidate_evidence(self, candidate_id: UUID, evidence_id: UUID, claim_key: str) -> None:
        self._exec("INSERT INTO engine.candidate_evidence (candidate_id,evidence_id,claim_key) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",(candidate_id,evidence_id,claim_key))
    def update_candidate_reason(self, candidate_id: UUID, reason: str) -> None:
        """[5] 설명 문장이 부품표 확정보다 늦게 끝날 때, 나중에 reason만 채워 넣는다."""
        self._exec("UPDATE engine.recommendation_candidate SET reason=%s, reason_status='ready' WHERE id=%s",(reason,candidate_id))
    def fail_candidate_reason(self, candidate_id: UUID) -> None:
        """[5] 실패 — reason은 NULL로 남기고(제약상 ready만 값을 가짐) 상태만 failed로."""
        self._exec("UPDATE engine.recommendation_candidate SET reason_status='failed' WHERE id=%s",(candidate_id,))
    def update_candidate_checks(self, candidate_id: UUID, checks: str) -> None:
        """부품 사용 가이드 RAG 검색 결과 — "구매 전 확인" 문장을 채운다."""
        self._exec("UPDATE engine.recommendation_candidate SET checks=%s, checks_status='ready' WHERE id=%s",(checks,candidate_id))
    def fail_candidate_checks(self, candidate_id: UUID) -> None:
        """가이드 검색/임베딩 실패 — checks는 NULL로 남기고 상태만 failed로."""
        self._exec("UPDATE engine.recommendation_candidate SET checks_status='failed' WHERE id=%s",(candidate_id,))
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str, executor_version: str, status: str, severity: str, measured_values: dict, threshold: dict, message: str, checked_at) -> UUID:
        row=self._one("""INSERT INTO engine.validation_result (run_id,rule_key,rule_version,executor_version,status,severity,measured_values,threshold,message,checked_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,rule_key,rule_version,executor_version,status,severity,Jsonb(measured_values),Jsonb(threshold),message,checked_at)); return row["id"]
    def set_candidate_result(self, candidate_id: UUID, *, result: str, score=None) -> None:
        if result not in {"pending", "passed", "rejected", "selected"}:
            raise ValueError("invalid_candidate_result")
        self._exec("UPDATE engine.recommendation_candidate SET result=%s, score=%s, score_method_version=%s WHERE id=%s",
                   (result, score, "baby-v1" if score is not None else None, candidate_id))
    def link_validation_target(self, validation_result_id: UUID, *, requirement_id: UUID | None = None, purchase_line_id: UUID | None = None, candidate_id: UUID | None = None) -> UUID:
        row=self._one("INSERT INTO engine.validation_target (validation_result_id,requirement_id,purchase_line_id,candidate_id) VALUES (%s,%s,%s,%s) RETURNING id",(validation_result_id,requirement_id,purchase_line_id,candidate_id)); return row["id"]
    def link_validation_evidence(self, validation_result_id: UUID, evidence_id: UUID) -> None:
        self._exec("INSERT INTO engine.validation_evidence (validation_result_id,evidence_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",(validation_result_id,evidence_id))
    def set_explanation(self, run_id: UUID, *, headline: str, text: str, reasoning_log: list) -> None:
        self._exec(
            """UPDATE engine.recommendation_run
            SET explanation_status='ready', explanation_headline=%s, explanation_text=%s,
                reasoning_log=%s, updated_at=now()
            WHERE id=%s""",
            (headline, text, Jsonb(reasoning_log), run_id),
        )
    def fail_explanation(self, run_id: UUID) -> None:
        """[5] 실패 — headline/text는 NULL로 남기고(제약상 ready만 값을 가짐) 상태만 failed로.
        run.status는 건드리지 않는다 — 부품·가격·검증은 이미 complete_run으로 확정된 뒤다."""
        self._exec("UPDATE engine.recommendation_run SET explanation_status='failed', updated_at=now() WHERE id=%s",(run_id,))
    def get_run(self, run_id: UUID) -> dict | None:
        return self._one("SELECT * FROM engine.recommendation_run WHERE id=%s",(run_id,))
    def get_latest_run(self, revision_id: UUID) -> dict | None:
        return self._one("SELECT * FROM engine.recommendation_run WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1",(revision_id,))
    def has_running_run(self, revision_id: UUID) -> bool:
        row = self._one("SELECT 1 FROM engine.recommendation_run WHERE revision_id=%s AND status='running' LIMIT 1", (revision_id,))
        return row is not None
    def get_candidates(self, run_id: UUID) -> list[dict]:
        return self._all("""
        SELECT c.*, p.model AS product_key, v.id AS variant_id, v.variant_key,
               p.name AS product_name, p.brand, p.attributes, p.image_url,
               of.id AS offer_id, of.purchase_url, o.price, o.observed_at,
               n.template_key AS slot, n.name AS slot_label
        FROM engine.recommendation_candidate c
        JOIN catalog.product_variant v ON v.id=c.variant_id
        JOIN catalog.product p ON p.id=v.product_id
        LEFT JOIN catalog.offer_observation o ON o.id=c.offer_observation_id
        LEFT JOIN catalog.offer of ON of.id=o.offer_id
        JOIN planning.requirement r2 ON r2.id=c.requirement_id
        JOIN planning.plan_node n ON n.id=r2.node_id
        WHERE c.run_id=%s ORDER BY n.position, c.created_at""", (run_id,))
    def get_validations(self, run_id: UUID) -> list[dict]:
        return self._all("SELECT * FROM engine.validation_result WHERE run_id=%s ORDER BY created_at", (run_id,))
    def get_candidate_evidence(self, candidate_id: UUID) -> list[dict]:
        return self._all("""SELECT ev.id AS evidence_id, ev.citation_snapshot, ev.status
        FROM engine.candidate_evidence ce JOIN evidence.evidence ev ON ev.id=ce.evidence_id
        WHERE ce.candidate_id=%s AND ev.status='active'""", (candidate_id,))
    def update_candidate_state(self, candidate_id: UUID, *, selected: bool | None = None,
                                qty: int | None = None, timing: str | None = None) -> None:
        sets, params = [], []
        if selected is not None:
            sets.append("selected=%s"); params.append(selected)
        if qty is not None:
            sets.append("qty=%s"); params.append(qty)
        if timing is not None:
            sets.append("timing=%s"); params.append(timing)
        if not sets:
            return
        params.append(candidate_id)
        self._exec(f"UPDATE engine.recommendation_candidate SET {', '.join(sets)} WHERE id=%s", params)
    def update_candidate_variant(self, candidate_id: UUID, *, variant_id: UUID,
                                  offer_observation_id: UUID | None) -> None:
        """후보 교체 — item_id(행 자체)는 그대로 두고 내용만 바꿔치기한다(계약: item_id 고정).
        점수·설명 문장은 더 이상 새 상품을 반영하지 않으므로 pending으로 되돌린다."""
        self._exec(
            "UPDATE engine.recommendation_candidate SET variant_id=%s, offer_observation_id=%s, "
            "score=NULL, score_method_version=NULL, reason=NULL, reason_status='pending' WHERE id=%s",
            (variant_id, offer_observation_id, candidate_id),
        )


def persist_candidate_check(conn, run_id: UUID, candidate_id: UUID, check, _context) -> None:
    """Persist P3 checks for a real candidate row (shared by pipeline and tests)."""
    from datetime import datetime, timezone
    repo = EngineRepo(conn)
    for issue in check.issues:
        validation_id = repo.add_validation(run_id, rule_key=issue["rule_key"], rule_version=issue.get("rule_version", "v1"),
                            executor_version="baby-v1", status=issue["status"], severity=issue["severity"],
                            measured_values=issue.get("measured") or {}, threshold=issue.get("threshold") or {},
                            message=issue.get("reason") or issue["rule_key"], checked_at=datetime.now(timezone.utc))
        # A result-level blocker must remain attributable to the candidate and
        # requirement after the worker transaction has ended.
        target = issue.get("target") or {}
        requirement_id = target.get("requirement_id")
        target_candidate_id = target.get("candidate_id") or candidate_id
        repo.link_validation_target(
            validation_id,
            requirement_id=UUID(str(requirement_id)) if requirement_id else None,
            candidate_id=UUID(str(target_candidate_id)),
        )
