"""engine recommendation 실행 결과 저장소 (P0 v3: candidate_evidence/validation_target/
validation_evidence 는 evidence_refs/issues jsonb 로 흡수됨)."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from psycopg.types.json import Jsonb
from src.db.base import Repo
from src.errors import Conflict

class EngineRepo(Repo):
    def start_run(self, revision_id: UUID, domain_id: UUID, *, input_snapshot: dict, input_hash: str, draft_lock_version: int, engine_versions: dict) -> UUID:
        row = self._one("""INSERT INTO engine.recommendation_run (revision_id, domain_id, domain_snapshot, input_snapshot, input_hash, draft_lock_version, engine_versions, status)
        SELECT %s, %s, jsonb_build_object('version_no',current_version_no,'definition',definition,'attribute_schema',attribute_schema,'content_hash',content_hash),
               %s,%s,%s,%s,'running' FROM config.domain WHERE id=%s
        RETURNING id""", (revision_id, domain_id, Jsonb(input_snapshot), input_hash, draft_lock_version, Jsonb(engine_versions), domain_id))
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
    # evidence_id 하나를 v1 EvidenceRef 로 펼치는 공통 CTE.
    # material/version/hash/locator 를 실제 적재 이력에서 복원한다 — 이 메타데이터가 빠지면
    # 0013 의 evidence_refs_items_check 가 거부한다(P0 SR08).
    _EVIDENCE_REF_CTE = """
        ref AS (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'evidence_id', ev.id::text,
            'claim_key', {claim_key},
            'material_id', ij.material_id::text,
            'material_version', COALESCE(ij.material_version, 'v0'),
            'file_sha256', ev.citation_snapshot->>'file_sha256',
            'locator', COALESCE(ev.citation_snapshot->'locator', '{{}}'::jsonb),
            'retrieval_run_id', rh.retrieval_run_id::text
          )) AS obj
          FROM evidence.evidence ev
          JOIN rag.retrieval_hit rh ON rh.id = ev.retrieval_hit_id
          JOIN rag.document_chunk dc ON dc.id = rh.chunk_id
          JOIN rag.ingestion_job ij ON ij.id = dc.ingestion_id
          WHERE ev.id = %s
        )"""

    @staticmethod
    def _dedup_append(array_sql: str) -> str:
        """(evidence_id, claim_key) 가 이미 있으면 덧붙이지 않는다 — 중복 인용 금지(P0 SR08)."""
        return f"""CASE WHEN EXISTS (
            SELECT 1 FROM jsonb_array_elements(COALESCE({array_sql}, '[]'::jsonb)) old
            WHERE old->>'evidence_id' = ref.obj->>'evidence_id'
              AND old->>'claim_key' = ref.obj->>'claim_key')
          THEN COALESCE({array_sql}, '[]'::jsonb)
          ELSE COALESCE({array_sql}, '[]'::jsonb) || jsonb_build_array(ref.obj) END"""

    def link_candidate_evidence(self, candidate_id: UUID, evidence_id: UUID, claim_key: str) -> None:
        """Persist v1 evidence references on the candidate, not a join row."""
        appended = self._dedup_append("c.evidence_refs->'refs'")
        cte = self._EVIDENCE_REF_CTE.format(claim_key="%s::text")
        row = self._one(f"""WITH {cte}
        UPDATE engine.recommendation_candidate c
        SET evidence_refs = jsonb_build_object('schema_version', 1, 'refs', {appended})
        FROM ref WHERE c.id=%s RETURNING c.id""", (claim_key, evidence_id, candidate_id))
        if row is None:
            raise ValueError(f"link_candidate_evidence: 근거 메타데이터를 복원할 수 없습니다 (evidence={evidence_id})")
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str, executor_version: str, status: str, severity: str, measured_values: dict, threshold: dict, message: str, checked_at) -> UUID:
        issue = {
            "schema_version": 1, "rule_key": rule_key, "rule_version": rule_version,
            "target": {"candidate_id": None, "requirement_id": None, "item_id": None},
            "status": status, "severity": severity, "measured": measured_values, "threshold": threshold,
            "reason": message, "penalty": None, "evidence_refs": [],
        }
        row=self._one("""INSERT INTO engine.validation_result (run_id,rule_key,rule_version,executor_version,status,severity,measured_values,threshold,message,checked_at,issues)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,rule_key,rule_version,executor_version,status,severity,Jsonb(measured_values),Jsonb(threshold),message,checked_at,Jsonb([issue]))); return row["id"]
    def link_validation_target(self, validation_result_id: UUID, *, requirement_id: UUID | None = None, candidate_id: UUID | None = None, item_id: UUID | None = None) -> None:
        """typed issues[0].target 갱신 — validation_target 테이블 없이 issues jsonb 로 보관(P0 v3)."""
        self._exec(
            """UPDATE engine.validation_result SET issues = jsonb_set(issues,'{0,target}',
            jsonb_build_object('requirement_id',%s::text,'candidate_id',%s::text,'item_id',%s::text))
            WHERE id=%s""",
            (str(requirement_id) if requirement_id else None, str(candidate_id) if candidate_id else None,
             str(item_id) if item_id else None, validation_result_id),
        )
    def link_validation_evidence(self, validation_result_id: UUID, evidence_id: UUID) -> None:
        """typed issues[0].evidence_refs 에 추가 — validation_evidence 테이블 없이 issues jsonb 로 보관(P0 v3).

        candidate 쪽과 동일한 완전 ref(자료/버전/해시/로케이터)를 쓰고 같은 키로 중복 제거한다.
        claim_key 는 이 검증 규칙 키 — 어떤 주장에 붙은 근거인지 남긴다.
        """
        validation = self._one(
            "SELECT rule_key FROM engine.validation_result WHERE id=%s", (validation_result_id,))
        if validation is None:
            raise ValueError(f"link_validation_evidence: 검증 결과가 없습니다 ({validation_result_id})")
        appended = self._dedup_append("v.issues#>'{0,evidence_refs}'")
        cte = self._EVIDENCE_REF_CTE.format(claim_key="%s::text")
        row = self._one(f"""WITH {cte}
        UPDATE engine.validation_result v
        SET issues = jsonb_set(v.issues, '{{0,evidence_refs}}', {appended})
        FROM ref WHERE v.id=%s AND jsonb_array_length(v.issues) > 0 RETURNING v.id""",
            (validation["rule_key"], evidence_id, validation_result_id))
        if row is None:
            raise ValueError(f"link_validation_evidence: 근거 메타데이터를 복원할 수 없습니다 (evidence={evidence_id})")
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
               r2.slot_key AS slot, r2.slot_key AS slot_label
        FROM engine.recommendation_candidate c
        JOIN catalog.product_variant v ON v.id=c.variant_id
        JOIN catalog.product p ON p.id=v.product_id
        LEFT JOIN catalog.offer_observation o ON o.id=c.offer_observation_id
        LEFT JOIN catalog.offer of ON of.id=o.offer_id
        JOIN planning.requirement r2 ON r2.id=c.requirement_id
        WHERE c.run_id=%s ORDER BY r2.position, c.created_at""", (run_id,))
    def get_validations(self, run_id: UUID) -> list[dict]:
        return self._all("SELECT * FROM engine.validation_result WHERE run_id=%s ORDER BY created_at", (run_id,))
    def get_candidate_evidence(self, candidate_id: UUID) -> list[dict]:
        return self._all("""SELECT ev.id AS evidence_id, ev.citation_snapshot, ev.status
        FROM engine.recommendation_candidate c
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.evidence_refs->'refs', '[]'::jsonb)) ref
        JOIN evidence.evidence ev ON ev.id=(ref->>'evidence_id')::uuid
        WHERE c.id=%s AND ev.status='active'""", (candidate_id,))
    def resolve_evidence_ref(self, evidence_id) -> dict | None:
        """Rebuild a v1 EvidenceRef for `evidence_id` plus its owning run/status, for
        persist-time validation (P3 CONTRACTS: reject malformed/orphan/cross-run refs
        before write, not after). None means the id does not exist at all (orphan)."""
        return self._one(
            """SELECT ev.id::text AS evidence_id, ev.status,
                      ij.material_id::text AS material_id,
                      COALESCE(ij.material_version,'v0') AS material_version,
                      ev.citation_snapshot->>'file_sha256' AS file_sha256,
                      COALESCE(ev.citation_snapshot->'locator','{}'::jsonb) AS locator,
                      rh.retrieval_run_id::text AS retrieval_run_id,
                      rr.recommendation_run_id::text AS recommendation_run_id
               FROM evidence.evidence ev
               JOIN rag.retrieval_hit rh ON rh.id = ev.retrieval_hit_id
               JOIN rag.document_chunk dc ON dc.id = rh.chunk_id
               JOIN rag.ingestion_job ij ON ij.id = dc.ingestion_id
               JOIN rag.retrieval_run rr ON rr.id = rh.retrieval_run_id
               WHERE ev.id = %s""",
            (evidence_id,),
        )


def _validated_ref(repo: "EngineRepo", evidence_id: str, run_id: UUID, claim_key: str):
    """Fetch + validate one evidence_id against P0's EvidenceRef contract and run scope.

    Raises ValueError (never writes anything) for: nonexistent/orphan ids, ids whose
    material/evidence was revoked between search and persist, cross-run ids (an id
    that belongs to a *different* recommendation_run's retrieval), and ids whose
    reconstructed shape fails the EvidenceRef pydantic contract (malformed). This is
    the P3 CONTRACTS VE08 gate: rejection happens before any DB write, not as cleanup
    after a partial write.
    """
    from src.reduction_contracts import EvidenceRef

    row = repo.resolve_evidence_ref(evidence_id)
    if row is None:
        raise ValueError(f"orphan_evidence_ref:{evidence_id}")
    if row["status"] != "active":
        raise ValueError(f"revoked_evidence_ref:{evidence_id}")
    if str(row["recommendation_run_id"]) != str(run_id):
        raise ValueError(f"cross_run_evidence_ref:{evidence_id}")
    try:
        EvidenceRef(
            evidence_id=row["evidence_id"], claim_key=claim_key, material_id=row["material_id"],
            material_version=row["material_version"], file_sha256=row["file_sha256"] or "",
            locator=row["locator"], retrieval_run_id=row["retrieval_run_id"],
        )
    except Exception as exc:  # pydantic.ValidationError
        raise ValueError(f"malformed_evidence_ref:{evidence_id}:{exc}") from exc
    return row


def persist_candidate_check(conn, run_id: UUID, candidate_id: UUID, check, explanation) -> None:
    """Persist a P3 CandidateCheck + ExplanationWithRefs for one candidate.

    check: src.dto.CandidateCheck (issues[i] carries a transient "evidence_ids" list of
    already-recorded evidence.evidence ids, produced during the RAG search itself —
    not a full EvidenceRef; this function is the one place that expands + validates
    them into the stored v1 shape). explanation: src.dto.ExplanationWithRefs.

    All-or-nothing: every referenced evidence_id across every issue and the
    explanation is validated (existence, active status, run ownership, EvidenceRef
    shape) BEFORE any row is written for this candidate.
    """
    repo = EngineRepo(conn)
    with conn.transaction():
        owner = repo._one(
            "SELECT id FROM engine.recommendation_candidate WHERE id=%s AND run_id=%s FOR UPDATE",
            (candidate_id, run_id),
        )
        if owner is None:
            raise ValueError("candidate_not_in_run")

        for issue in check.issues:
            for key in ("rule_key", "rule_version", "status", "severity", "reason"):
                if not issue.get(key):
                    raise ValueError(f"malformed_issue_missing:{key}")
            if issue["status"] not in ("pass", "fail", "unknown"):
                raise ValueError(f"malformed_issue_status:{issue['status']}")
        pending_issue_refs = [
            (issue, [
                _validated_ref(repo, eid, run_id, issue["rule_key"])
                for eid in issue.get("evidence_ids", [])
            ])
            for issue in check.issues
        ]
        pending_explanation_refs = []
        if explanation is not None and explanation.status == "ready":
            for ref in explanation.refs:
                evidence_id = ref.get("evidence_id") if isinstance(ref, dict) else None
                if not evidence_id:
                    raise ValueError("malformed_explanation_ref_missing_evidence_id")
                pending_explanation_refs.append(
                    _validated_ref(repo, evidence_id, run_id, "explanation")
                )

        for issue, refs in pending_issue_refs:
            validation_id = repo.add_validation(
                run_id, rule_key=issue["rule_key"], rule_version=issue["rule_version"],
                executor_version="baby-rag-v1", status=issue["status"], severity=issue["severity"],
                measured_values=issue.get("measured") or {}, threshold=issue.get("threshold") or {},
                message=issue["reason"], checked_at=datetime.now(timezone.utc),
            )
            repo.link_validation_target(validation_id, candidate_id=candidate_id,
                                        requirement_id=(issue.get("target") or {}).get("requirement_id"))
            for ref in refs:
                repo.link_validation_evidence(validation_id, ref["evidence_id"])
        for ref in pending_explanation_refs:
            repo.link_candidate_evidence(candidate_id, ref["evidence_id"], "explanation")
