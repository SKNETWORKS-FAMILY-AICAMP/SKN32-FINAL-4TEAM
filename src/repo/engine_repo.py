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
        reason_status = "ready" if reason is not None else "pending"
        row=self._one("""INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status)); return row["id"]
    def link_candidate_evidence(self, candidate_id: UUID, evidence_id: UUID, claim_key: str) -> None:
        self._exec("INSERT INTO engine.candidate_evidence (candidate_id,evidence_id,claim_key) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",(candidate_id,evidence_id,claim_key))
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str, executor_version: str, status: str, severity: str, measured_values: dict, threshold: dict, message: str, checked_at) -> UUID:
        row=self._one("""INSERT INTO engine.validation_result (run_id,rule_key,rule_version,executor_version,status,severity,measured_values,threshold,message,checked_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,rule_key,rule_version,executor_version,status,severity,Jsonb(measured_values),Jsonb(threshold),message,checked_at)); return row["id"]
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
               of.purchase_url, o.price, o.observed_at,
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
