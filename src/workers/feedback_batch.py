"""[6] 사후 학습 배치 러너.

engine.stage6_feedback.run_batch 를 스케줄(주 1회)로 실행.
데모 = 미가동 (feedback_event 로깅만).
"""
from __future__ import annotations

from src.engine.stage6_feedback import run_batch


def run() -> None:
    run_batch()
