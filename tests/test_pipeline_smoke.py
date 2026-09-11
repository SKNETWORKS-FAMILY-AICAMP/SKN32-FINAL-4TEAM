"""엔진 파이프라인 스모크 테스트 (DB·네트워크 없이 목으로 end-to-end).

실제 로직 테스트는 각 stage 구현 시 tests/engine/ 아래 추가.
"""
from src.pipeline import run_pipeline


def test_computer_pass_runs_end_to_end():
    r = run_pipeline("computer_pass", on_log=lambda _m: None)
    assert r.build is not None and len(r.build.items) == 8
    assert r.verification.targets[0].passed is True
    assert set(r.explanation.contribution) == {"가격", "성능", "호환성"}


def test_computer_research_triggers_retry_then_passes():
    r = run_pipeline("computer_research", on_log=lambda _m: None)
    assert r.verification.targets[0].rounds == 2          # 1회 실패 후 재탐색
    assert r.verification.targets[0].passed is True
