"""engine recommendation 실행 결과 저장소 (develop `da79839` 정렬, P0 v3).

candidate.evidence_refs / validation_result.issues 는 develop `0012_schema_reduction_
safe_subset.sql` 이 남긴 평면 JSON 배열이다(래퍼 객체 아님) — DEVELOP_DB_TRANSITION.md
"Evidence and external search" 참고. rag 스키마가 완전히 삭제됐으므로(0011_drop_rag_
schema.sql) 근거 메타데이터(자료/버전/해시/로케이터)를 되읽어 채우는 일은 P3 외부 검색
adapter 의 몫이다 — 여기서는 호출자가 넘긴 값을 그대로 배열에 담고 스키마 형태만 보장한다.
"""
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
        reason_status = "ready" if reason is not None else "pending"
        row=self._one("""INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)); return row["id"]
    def link_candidate_evidence(self, candidate_id: UUID, evidence_id: UUID, claim_key: str, *, ref: dict | None = None) -> None:
        """candidate.evidence_refs (평면 jsonb 배열) 에 (evidence_id, claim_key) 중복 없이 추가."""
        entry = {**(ref or {}), "evidence_id": str(evidence_id), "claim_key": claim_key}
        self._exec(
            """UPDATE engine.recommendation_candidate SET evidence_refs = CASE WHEN EXISTS (
                 SELECT 1 FROM jsonb_array_elements(evidence_refs) e
                 WHERE e->>'evidence_id'=%s AND e->>'claim_key'=%s)
               THEN evidence_refs ELSE evidence_refs || %s::jsonb END WHERE id=%s""",
            (str(evidence_id), claim_key, Jsonb([entry]), candidate_id),
        )
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str, executor_version: str, status: str, severity: str, measured_values: dict, threshold: dict, message: str, checked_at) -> UUID:
        row=self._one("""INSERT INTO engine.validation_result (run_id,rule_key,rule_version,executor_version,status,severity,measured_values,threshold,message,checked_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,rule_key,rule_version,executor_version,status,severity,Jsonb(measured_values),Jsonb(threshold),message,checked_at)); return row["id"]
    def link_validation_target(self, validation_result_id: UUID, *, requirement_id: UUID | None = None, candidate_id: UUID | None = None, item_id: UUID | None = None) -> None:
        """validation_result.issues (평면 jsonb 배열) 에 대상 정보를 담은 issue 항목 추가."""
        entry = {"target": {"requirement_id": str(requirement_id) if requirement_id else None,
                            "candidate_id": str(candidate_id) if candidate_id else None,
                            "item_id": str(item_id) if item_id else None},
                 "evidence_refs": []}
        self._exec(
            "UPDATE engine.validation_result SET issues = issues || %s::jsonb WHERE id=%s",
            (Jsonb([entry]), validation_result_id),
        )
    def link_validation_evidence(self, validation_result_id: UUID, evidence_id: UUID, *, ref: dict | None = None) -> None:
        """가장 최근에 추가된 issue(있으면)의 evidence_refs 에 근거를 붙인다."""
        entry = {**(ref or {}), "evidence_id": str(evidence_id)}
        self._exec(
            """UPDATE engine.validation_result SET issues = jsonb_set(
                 issues, array[(jsonb_array_length(issues)-1)::text, 'evidence_refs'],
                 COALESCE(issues#>array[(jsonb_array_length(issues)-1)::text,'evidence_refs'],'[]'::jsonb)
                   || %s::jsonb)
               WHERE id=%s AND jsonb_array_length(issues) > 0""",
            (Jsonb([entry]), validation_result_id),
        )
    def set_explanation(self, run_id: UUID, *, headline: str, text: str, reasoning_log: list) -> None:
        self._exec(
            """UPDATE engine.recommendation_run
            SET explanation_status='ready', explanation_headline=%s, explanation_text=%s,
                reasoning_log=%s, updated_at=now()
            WHERE id=%s""",
            (headline, text, Jsonb(reasoning_log), run_id),
        )
    def fail_explanation(self, run_id: UUID) -> None:
        """실패 — headline/text는 NULL로 남기고(제약상 ready만 값을 가짐) 상태만 failed로."""
        self._exec("UPDATE engine.recommendation_run SET explanation_status='failed', updated_at=now() WHERE id=%s", (run_id,))
    def set_candidate_reason(self, candidate_id: UUID, *, reason: str | None, status: str) -> None:
        self._exec(
            "UPDATE engine.recommendation_candidate SET reason=%s, reason_status=%s, updated_at=now() WHERE id=%s",
            (reason, status, candidate_id),
        )
    def set_candidate_result(self, candidate_id: UUID, *, result: str, score: float | None = None) -> None:
        if score is not None:
            self._exec(
                "UPDATE engine.recommendation_candidate SET result=%s, score=%s, score_method_version=%s, updated_at=now() WHERE id=%s",
                (result, score, "baby-optimizer-v1", candidate_id),
            )
        else:
            self._exec(
                "UPDATE engine.recommendation_candidate SET result=%s, updated_at=now() WHERE id=%s",
                (result, candidate_id),
            )
    def get_candidate(self, candidate_id: UUID) -> dict | None:
        return self._one("SELECT * FROM engine.recommendation_candidate WHERE id=%s", (candidate_id,))
    def get_candidates_by_requirement(self, run_id: UUID, requirement_id: UUID) -> list[dict]:
        return self._all(
            """SELECT c.*, p.model AS product_key, p.name AS product_name, p.brand, p.image_url,
                      v.variant_key, of.purchase_url, obs.price
               FROM engine.recommendation_candidate c
               JOIN catalog.product_variant v ON v.id=c.variant_id
               JOIN catalog.product p ON p.id=v.product_id
               LEFT JOIN catalog.offer_observation obs ON obs.id=c.offer_observation_id
               LEFT JOIN catalog.offer of ON of.id=obs.offer_id
               WHERE c.run_id=%s AND c.requirement_id=%s ORDER BY c.score DESC NULLS LAST, c.created_at""",
            (run_id, requirement_id),
        )
    def get_candidate_eligibility(self, run_id: UUID, candidate_id: UUID) -> dict:
        """validation_result.issues[].target.candidate_id 로 이 후보의 적격성을 재구성한다."""
        rows = self._all(
            """SELECT status, severity FROM engine.validation_result vr
               WHERE vr.run_id=%s AND EXISTS (
                 SELECT 1 FROM jsonb_array_elements(vr.issues) i WHERE i->'target'->>'candidate_id'=%s)""",
            (run_id, str(candidate_id)),
        )
        statuses = [r["status"] for r in rows]
        eligibility = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
        return {"eligibility": eligibility, "selection_allowed": eligibility == "pass", "issue_count": len(rows)}
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
        FROM engine.recommendation_candidate c
        CROSS JOIN LATERAL jsonb_array_elements(c.evidence_refs) ref
        JOIN evidence.evidence ev ON ev.id=(ref->>'evidence_id')::uuid
        WHERE c.id=%s AND ev.status='active'""", (candidate_id,))
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
