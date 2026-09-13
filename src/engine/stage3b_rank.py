"""[3-B] 적합도 · 병목 순위.

[3-A] 통과분을 슬롯별 점수화 → 슬롯별 top-N. LLM·RAG 없음.
score = Σ w_axis·norm_axis − (Pending 이면 0.20).
축: 가격 / 성능 여유 / 밸런스 적합 / 리뷰 신뢰도 / 호환 여유.
병목: balance_profiles 의 ideal_tier 대비 최선 후보가 낮으면 bottleneck_hint 방출.
"""
from __future__ import annotations

from src.config import PENDING_SCORE_PENALTY, TOP_N_DEFAULT, TOP_N_IMPACT
from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, Slots
from src.engine import LogFn

_IMPACT_SLOTS = {"GPU", "CPU"}

# TODO: data/balance_profiles.csv 로 교체 (purpose × resolution → ideal tier)
_IDEAL_TIER = {
    ("game", "FHD_144"): {"GPU": 6.0, "CPU": 6.0},
    ("game", "QHD_165"): {"GPU": 7.5, "CPU": 5.5},
    ("game", "4K"): {"GPU": 9.0, "CPU": 5.5},
}

_WEIGHTS = {"가격": 0.35, "성능": 0.25, "밸런스": 0.15, "리뷰": 0.20, "호환여유": 0.05}


def _score(cand: Candidate, ideal_tier: float | None, slot_budget: int) -> Candidate:
    tier = float(cand.specs.get("perf_tier", 5))
    price = cand.price or 1
    b = {
        "가격": max(0.0, 1 - price / max(slot_budget, 1)),
        "성능": min(1.0, tier / 10),
        "밸런스": (1 - abs(tier - ideal_tier) / 4) if ideal_tier else 0.5,
        "리뷰": 0.5,          # TODO: review_summaries 연동
        "호환여유": 0.5,       # TODO: 파워·길이 마진
    }
    raw = sum(_WEIGHTS[k] * v for k, v in b.items())
    if cand.verdict == "Pending":
        raw -= PENDING_SCORE_PENALTY
    return cand.model_copy(update={"score": round(raw, 3), "breakdown": {k: round(v, 3) for k, v in b.items()}})


def run(hf: HardFilterResult, spec: RequirementSpec, slots: Slots, log: LogFn) -> RankResult:
    log("[3-B] 적합도 · 병목 순위 ...")
    rr = RankResult(weights_used=dict(_WEIGHTS))
    purpose = slots.values.get("purpose", "game")
    res = slots.values.get("resolution", "FHD_144")
    ideals = _IDEAL_TIER.get((purpose, res), {})
    alloc = spec.budget.get("alloc", {})
    total = spec.budget.get("total", 0)

    for slot, cands in hf.slots.items():
        ideal = ideals.get(slot)
        slot_budget = int(total * alloc.get(slot, 0.1)) if total else 1
        scored = sorted((_score(c, ideal, slot_budget) for c in cands),
                        key=lambda c: c.score, reverse=True)
        n = TOP_N_IMPACT if slot in _IMPACT_SLOTS else TOP_N_DEFAULT
        top = [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(scored[:n])]

        hint = None
        if ideal and top and float(top[0].specs.get("perf_tier", 5)) < ideal - 0.5:
            hint = {"slot": slot, "gap": round(ideal - float(top[0].specs.get("perf_tier", 5)), 1),
                    "suggestion": "alloc 상향 또는 tier 하향 수용"}
            log(f"      병목 힌트: {slot} tier {top[0].specs.get('perf_tier')} < ideal {ideal}")

        rr.slots[slot] = {
            "ideal_tier": ideal,
            "ranked": [c.model_dump() for c in top],
            "bottleneck_hint": hint,
        }
        log(f"      {slot}: top-{len(top)}  (ideal_tier={ideal})  1위 score={top[0].score if top else '-'}")
    return rr
