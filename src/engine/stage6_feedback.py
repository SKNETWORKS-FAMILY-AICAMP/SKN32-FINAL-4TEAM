"""[6] 사후 학습 (되먹임) — 별도 오프라인 배치.

요청 경로 밖. 엔진이 읽는 설정·룩업 테이블만 갱신 (balance_profiles / budget_profiles /
DEFAULT_WEIGHTS / game_requirements / perf_tier / RAG 코퍼스).
데모 = feedback_event 로깅만. 이 모듈은 최종 배치(feedback_batch worker)가 호출.
"""
from __future__ import annotations


def run_batch() -> None:
    """feedback_event 집계 → 확정/구매 세트로 프로필 EMA 갱신 → staging → 가드 통과분 prod 스왑.
    승인 게이트: balance/budget/weights 자동, game_req/perf_tier/RAG 는 사람 승인.
    """
    raise NotImplementedError
