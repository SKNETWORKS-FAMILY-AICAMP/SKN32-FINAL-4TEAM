"""engine.* 저장소 — recommendation_run / recommendation_candidate / candidate_evidence /
validation_result / validation_target / validation_evidence / feedback_event.

파이프라인 실행 결과를 영속화한다. 검색 점수 ≠ 검증 통과(§8.2).
C15: 결과 적용 시 recommendation_run.draft_lock_version 재확인.
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class EngineRepo(Repo):
    # ── 추천 실행 ──
    def start_run(self, revision_id: UUID, domain_version_id: UUID, *,
                  input_snapshot: dict, input_hash: str, draft_lock_version: int,
                  engine_versions: dict) -> UUID:
        raise NotImplementedError

    def complete_run(self, run_id: UUID, status: str = "completed") -> None:
        raise NotImplementedError

    def add_candidate(self, run_id: UUID, requirement_id: UUID, variant_id: UUID, *,
                      result: str, score=None, score_method_version: str | None = None,
                      reason: str | None = None, offer_observation_id: UUID | None = None) -> UUID:
        raise NotImplementedError

    def link_candidate_evidence(self, candidate_id: UUID, evidence_id: UUID, claim_key: str) -> None:
        raise NotImplementedError

    # ── 검증 결과 ([3-A]/[3-C]) ──
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str,
                       executor_version: str, status: str, severity: str,
                       measured_values: dict, threshold: dict, message: str, checked_at) -> UUID:
        raise NotImplementedError

    def link_validation_target(self, validation_result_id: UUID, *,
                               requirement_id: UUID | None = None,
                               purchase_line_id: UUID | None = None,
                               candidate_id: UUID | None = None) -> UUID:
        raise NotImplementedError

    def link_validation_evidence(self, validation_result_id: UUID, evidence_id: UUID) -> None:
        raise NotImplementedError

    # ── 피드백 ([6] 입력) ──
    def log_feedback(self, plan_id: UUID, revision_id: UUID, *, event_type: str,
                     event_key: str, payload: dict, occurred_at,
                     recommendation_run_id: UUID | None = None,
                     user_id: UUID | None = None) -> UUID:
        """추가 전용. UNIQUE(event_key) 로 재전송 멱등. plan_confirmed 는 확정 트랜잭션에서(C23)."""
        raise NotImplementedError
