"""[3-B] 적합도 · 병목 순위.

[3-A] 통과분을 슬롯별 점수화 → 슬롯별 top-N. LLM·RAG 없음.
score = Σ w_axis·norm_axis − (Pending 이면 0.20).
축: 가격 / 성능 여유 / 밸런스 적합 / 리뷰 신뢰도 / 호환 여유.
병목: balance_profiles 의 ideal_tier 대비 최선 후보가 낮으면 bottleneck_hint 방출.
"""
from __future__ import annotations

from src.config import PENDING_SCORE_PENALTY, REVIEW_AXIS_EXCESS, TOP_N_DEFAULT, TOP_N_IMPACT
from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, Slots
from src.engine import LogFn
from src.repo.review_repo import (OBS_FLAG_OBSERVED, RISK_STORE_OK, default_risk_store, format_obs_flag,
                                 risk_store_note, risk_store_reason)

_IMPACT_SLOTS = {"GPU", "CPU"}

# TODO: data/balance_profiles.csv 로 교체 (purpose × resolution → ideal tier)
_IDEAL_TIER = {
    ("game", "FHD_144"): {"GPU": 6.0, "CPU": 6.0},
    ("game", "QHD_165"): {"GPU": 7.5, "CPU": 5.5},
    ("game", "4K"): {"GPU": 9.0, "CPU": 5.5},
}

_WEIGHTS = {"가격": 0.35, "성능": 0.25, "밸런스": 0.15, "리뷰": 0.20, "호환여유": 0.05}

# ── 리뷰축: 관계·행동 축의 관측 사실을 랭킹 신호로만 쓴다 (docs/decisions/0001 §3) ──
# 세 단계뿐이다. 관측 없음 0.5(모름) · 관측됨·중앙값의 REVIEW_AXIS_EXCESS 배를 넘는 지표 없음 0.75 ·
# 하나라도 넘음 0.25. 판정이 아니다 — 덜 보여줄 뿐이고 되돌릴 수 있는 자리라 검증 없이 쓴다.
# 넘은 지표는 flags 에 남겨 [5] 설명이 "왜" 를 보여줄 수 있게 한다.
_REVIEW_UNKNOWN, _REVIEW_CLEAR, _REVIEW_FLAGGED = 0.5, 0.75, 0.25


def _review_axis(cand: Candidate) -> tuple[float, list[str]]:
    store = default_risk_store()
    if store is None or store.get(cand.product_key) is None:
        return _REVIEW_UNKNOWN, []
    over = [(k, v, m) for k, v, m in store.excess(cand.product_key) if v >= REVIEW_AXIS_EXCESS * m]
    if over:
        return _REVIEW_FLAGGED, [format_obs_flag(k, v, m, REVIEW_AXIS_EXCESS) for k, v, m in over]
    return _REVIEW_CLEAR, [OBS_FLAG_OBSERVED]


def _score(cand: Candidate, ideal_tier: float | None, slot_budget: int) -> Candidate:
    tier = float(cand.specs.get("perf_tier", 5))
    price = cand.price or 1
    review, review_flags = _review_axis(cand)
    b = {
        "가격": max(0.0, 1 - price / max(slot_budget, 1)),
        "성능": min(1.0, tier / 10),
        "밸런스": (1 - abs(tier - ideal_tier) / 4) if ideal_tier else 0.5,
        "리뷰": review,
        "호환여유": 0.5,       # TODO: 파워·길이 마진
    }
    raw = sum(_WEIGHTS[k] * v for k, v in b.items())
    if cand.verdict == "Pending":
        raw -= PENDING_SCORE_PENALTY
    return cand.model_copy(update={"score": round(raw, 3), "breakdown": {k: round(v, 3) for k, v in b.items()},
                                   "flags": list(cand.flags) + review_flags})


def run(hf: HardFilterResult, spec: RequirementSpec, slots: Slots, log: LogFn) -> RankResult:
    log("[3-B] 적합도 · 병목 순위 ...")
    # 산출물을 못 쓰면 리뷰축이 전 후보에서 0.5(모름) 고정이라 구성이 달라진다.
    # 조용히 지나가면 "리뷰가 적은 상품들" 로 오해하므로 한 번 알린다.
    reason = risk_store_reason()
    if reason != RISK_STORE_OK:
        log(f"      ⚠ 리뷰축 비활성 — {risk_store_note()} (리뷰 관측 0건으로 계산)")
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
        n_obs = sum(1 for c in scored if c.breakdown.get("리뷰") != _REVIEW_UNKNOWN)
        n_flag = sum(1 for c in scored if c.breakdown.get("리뷰") == _REVIEW_FLAGGED)
        log(f"      {slot}: top-{len(top)}  (ideal_tier={ideal})  1위 score={top[0].score if top else '-'}"
            f"  리뷰관측 {n_obs}/{len(scored)}" + (f" (검토필요 {n_flag})" if n_flag else ""))
    return rr
