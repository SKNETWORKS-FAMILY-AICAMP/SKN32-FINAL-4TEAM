"""[3-0] 후보 수집.

[2]와 [3-A] 사이의 별도 스텝. 실시간 커머스 데이터 API 호출·캐시·재시도를
필터 로직에서 격리한다. 재탐색 시에는 스킵(이미 수집된 후보 재사용).
데모: 로컬 합성 카탈로그만 읽음 (제휴 커머스 API는 최종에서).
"""
from __future__ import annotations

from src.dto import Candidate, RequirementSpec
from src.engine import LogFn
from src.repo.catalog_repo import load_candidates_by_slot


def run(spec: RequirementSpec, log: LogFn) -> dict[str, list[Candidate]]:
    log("[3-0] 후보 수집 ...")
    if spec.category == "computer":
        by_slot = load_candidates_by_slot()
        summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
        log(f"      [MOCK] 합성 카탈로그 로드 → 슬롯별 후보: {summary}")
        return by_slot
    # TODO: 유아 baby_products 로드
    raise NotImplementedError("stage3_0: 유아 후보 수집 미구현 (데이터 확보 후)")
