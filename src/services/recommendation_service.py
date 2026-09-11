"""추천 서비스 — [추천 실행] → 엔진 파이프라인 → 결과 영속화.

현재 스켈레톤은 시나리오 파일 기반(src/pipeline.run_pipeline).
실제 구현: plan_revision 의 조건·슬롯 → RequirementSpec 빌드 → [3-0]~[5] →
engine.recommendation_run / candidate / validation_result 로 저장 → S4 응답.
"""
from __future__ import annotations

from uuid import UUID

from src.dto import PipelineResult
from src.pipeline import run_pipeline as _run_scenario


def run_from_scenario(scenario_name: str) -> PipelineResult:
    """개발용: 시나리오 파일로 파이프라인 1회 (DB 미사용)."""
    return _run_scenario(scenario_name, on_log=lambda _m: None)


def run_for_revision(revision_id: UUID) -> dict:
    """실제 경로: 계획 버전의 조건으로 추천 실행 → 저장 → S4 페이로드."""
    # TODO: 실제 로직 구현 필요
    #   1. EngineRepo.start_run(...)
    #   2. slots ← PlanRepo.load_full(revision_id)  → Slots
    #   3. stage2..stage5 (카테고리 분기 + 재탐색 루프)
    #   4. EngineRepo.add_candidate / add_validation / link_*  저장
    #   5. EngineRepo.log_feedback(recommendation_shown)
    #   6. return S4 DTO
    raise NotImplementedError


def get_result(revision_id: UUID) -> dict:
    """S4 재조회 (폴링 or 새로고침). 진행 중이면 단계 상태."""
    raise NotImplementedError
