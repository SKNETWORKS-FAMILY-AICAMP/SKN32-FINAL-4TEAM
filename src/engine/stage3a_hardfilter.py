"""[3-A] 하드 필터 (Pass / Fail / Pending).

규칙으로 확정 판정 가능한 것만. LLM·RAG 없음.
컴퓨터: 슬롯 내부 조건(perf_tier / socket / capacity ...) — 단방향 확정 제약만.
        양방향 조합 제약(link_rules)은 [4]/[3-C]로 넘긴다.
Pending ≠ Fail: 판정 데이터가 없으면 후보 유지하고 [3-B]에서 감점.
"""
from __future__ import annotations

from src.config import TOP_N_DEFAULT
from src.dto import Candidate, HardFilterResult, RequirementSpec
from src.engine import LogFn


def _judge_computer(cand: Candidate, target: dict) -> Candidate:
    reasons: list[str] = []
    verdict = "Pass"
    tier = cand.specs.get("perf_tier")
    tmin = target.get("perf_tier_min")
    if tmin is not None:
        if tier is None:
            verdict, reasons = "Pending", ["PENDING_SPEC_MISSING:perf_tier"]
        elif tier < tmin:
            verdict, reasons = "Fail", [f"FAIL_PERF_BELOW:{tier}<{tmin}"]
    # TODO: socket / vram / capacity / wattage / plus_rating 실제 비교
    if verdict == "Pass":
        reasons = ["PASS"]
    return cand.model_copy(update={"verdict": verdict, "reasons": reasons})


def run(spec: RequirementSpec, by_slot: dict[str, list[Candidate]], log: LogFn) -> HardFilterResult:
    log("[3-A] 하드 필터 (Pass/Fail/Pending) ...")
    result = HardFilterResult()
    for slot, cands in by_slot.items():
        target = spec.targets.get(slot, {})
        judged = [_judge_computer(c, target) for c in cands]
        p = [c for c in judged if c.verdict == "Pass"]
        pend = [c for c in judged if c.verdict == "Pending"]
        fail = [c for c in judged if c.verdict == "Fail"]

        # Pass 부족 시에만 Pending 승격 (스코어는 [3-B]에서 -20%)
        keep = p if len(p) >= TOP_N_DEFAULT else p + pend
        if not keep:  # 하드 완화 트리거 자리
            log(f"      ! {slot}: Pass 0 / Pending 0 → 하드 완화 필요 (데모는 목 후보로 진행)")
            keep = judged
        result.slots[slot] = keep
        result.stats[slot] = {"pool": len(cands), "pass": len(p),
                              "fail": len(fail), "pending": len(pend)}
        log(f"      {slot}: {len(cands)} → Pass {len(p)} / Fail {len(fail)} / Pending {len(pend)}")
    return result
