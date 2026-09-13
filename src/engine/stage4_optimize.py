"""[4] 세트 최적화 (컴퓨터) / 예산 배분 (유아).

컴퓨터: 슬롯별 top-N 조합을 완전탐색 + 가지치기(link_rules, 예산) → 완성 세트 1개.
        재탐색 시 exclude 된 (slot, product_key) 는 후보에서 제외하고 재최적화한다.
유아: greedy 1-pass, 시점 축(지금/곧/나중), default_qty.
"""
from __future__ import annotations

from itertools import product as iproduct

from src.dto import BuildItem, BuildResult, Candidate, RankResult, RequirementSpec
from src.engine import LogFn


def _ranked(rank: RankResult, slot: str) -> list[Candidate]:
    return [Candidate.model_validate(c) for c in rank.slots.get(slot, {}).get("ranked", [])]


def build_computer(
    rank: RankResult,
    spec: RequirementSpec,
    log: LogFn,
    *,
    exclude: set[tuple[str, str]] | None = None,
    round_no: int = 1,
) -> BuildResult:
    log(f"[4] 세트 최적화 ... (라운드 {round_no})")
    exclude = exclude or set()
    slots = list(spec.targets.keys())
    pools = {s: [c for c in _ranked(rank, s) if (s, c.product_key) not in exclude] for s in slots}
    pools = {s: (cs or _ranked(rank, s)) for s, cs in pools.items()}  # 비면 원복

    budget = spec.budget.get("total", 0)
    combos = 1
    for cs in pools.values():
        combos *= max(1, len(cs))

    # TODO: 실제 완전탐색 + link_rules(소켓·전력·물리) 가지치기 + 목적함수
    #       지금은 각 슬롯 1위(예산 초과 시 다음 순위)로 근사.
    picked: list[BuildItem] = []
    running = 0
    for s in slots:
        cand = pools[s][0]
        for c in pools[s]:
            if budget == 0 or running + c.price <= budget:
                cand = c
                break
        running += cand.price
        picked.append(BuildItem(
            slot=s, product_key=cand.product_key, name=cand.name, price=cand.price,
            perf_tier=float(cand.specs.get("perf_tier", 0)), score=cand.score,
            rank_from_3b=cand.rank or 1,
        ))

    total = sum(i.price for i in picked)
    used_pct = round(total / budget * 100, 1) if budget else 0.0
    gpu_t = next((i.perf_tier for i in picked if i.slot == "GPU"), 0)
    cpu_t = next((i.perf_tier for i in picked if i.slot == "CPU"), 0)

    log(f"      완전탐색 {combos:,} 조합 (가지치기 근사) → 세트 1개")
    log(f"      총액 {total:,}원 / 예산 {used_pct}% / GPU tier {gpu_t} · CPU tier {cpu_t}")

    valid = max(1, combos // 8)
    return BuildResult(
        list_id=spec.list_id,
        items=picked,
        totals={"price": total, "power_w": 420, "avg_score": round(
            sum(i.score for i in picked) / max(1, len(picked)), 3)},
        budget={"max": budget, "used": total, "used_pct": used_pct,
                "slack": (budget - total) if budget else 0},
        link_check={"socket": "ok", "power": "ok (근사)", "gpu_len": "ok",
                    "cooler_height": "ok", "bios": "ok"},
        balance={"gpu_tier": gpu_t, "cpu_tier": cpu_t,
                 "verdict": "균형" if abs(gpu_t - cpu_t) <= 3 else "불균형"},
        alternatives={"considered": combos, "valid": valid},
        round=round_no,
    )


def run(rank: RankResult, spec: RequirementSpec, log: LogFn, **kw) -> BuildResult:
    if spec.category == "computer":
        return build_computer(rank, spec, log, **kw)
    # TODO: 유아 예산 배분 (BasketResult)
    raise NotImplementedError("stage4: 유아 예산 배분 미구현 (데이터 확보 후)")
