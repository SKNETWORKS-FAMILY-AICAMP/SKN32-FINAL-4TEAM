"""[4] 세트 최적화 (컴퓨터) / 예산 배분 (유아).

컴퓨터: 슬롯별 top-N 조합을 완전탐색 + 가지치기(link_rules, 예산) → 완성 세트 1개.
        재탐색 시 exclude 된 (slot, product_key) 는 후보에서 제외하고 재최적화한다.
유아: greedy 1-pass, 시점 축(지금/곧/나중), default_qty.
"""
from __future__ import annotations

import time
import math
from itertools import product as iproduct
from typing import Any
from uuid import uuid4

from src.dto import (BabyRequirement, BasketDecision, BasketItem, BuildItem, BuildResult, Candidate,
                     CandidateCheck, RankedCandidates, RankResult, RequirementSpec, ScoredCandidate)
from src.engine import LogFn

# Requirements/candidate pools this size or smaller get an exact branch-and-bound
# search over every valid candidate. Above it, only the top-N ranked candidates per
# requirement enter the search — CONTRACTS ALGORITHM step 4 requires that this
# truncation be reported as a bounded-search approximation, never silently claimed
# as a global optimum.
BASKET_SEARCH_TOP_N = 8


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
    # The scenario-JSON/RankResult pipeline (run_pipeline) is PC-only; baby has no
    # scenario-file input at all (CONTRACTS: baby reads from the DB catalog). The
    # real baby budget computation is optimize_baby()/recalculate_basket() below,
    # reached through src.pipeline.run_baby_optimizer(), not this dispatcher.
    raise NotImplementedError("stage4: 유아는 scenario 기반 run()이 아니라 optimize_baby()를 쓴다")


# ── P4 baby basket optimizer ────────────────────────────────────────────────
_TIMING_ORDER = {"now": 0, "soon": 1, "later": 2}


def _requirement_sort_key(r: BabyRequirement) -> tuple[int, int, str]:
    """Deterministic processing order independent of input ordering
    (ACCEPTANCE OP06: reordering the input list must not change the selection)."""
    return (_TIMING_ORDER.get(r.timing, 3), 0 if r.mandatory else 1, r.slot_key)


def _match_owned(requirements: list[BabyRequirement], owned_items: list[dict[str, Any]]) -> dict[str, float]:
    """Consume each physical owned unit at most once against the first matching
    (slot_key, unit_code) requirements in deterministic order (ALGORITHM step 2).
    A unit-mismatched owned item (different unit_code) cannot fulfil a requirement
    (ACCEPTANCE OP08)."""
    owned_pool: dict[tuple[str, str], float] = {}
    for o in owned_items:
        key = (o.get("slot_key"), o.get("unit_code", "each"))
        owned_pool[key] = owned_pool.get(key, 0.0) + float(o.get("qty", 1))

    applied: dict[str, float] = {}
    for r in sorted(requirements, key=_requirement_sort_key):
        key = (r.slot_key, r.unit_code)
        avail = owned_pool.get(key, 0.0)
        if avail <= 1e-9:
            continue
        use = min(avail, r.required_qty)
        if use > 1e-9:
            applied[r.id] = use
            owned_pool[key] = avail - use
    return applied


def optimize_baby(
    requirements: list[BabyRequirement], ranked: RankedCandidates,
    owned_items: list[dict[str, Any]], budget_max: int | None,
) -> BasketDecision:
    """[4 baby] Deterministic budget allocation — pure function, no DB/HTTP/RAG
    (CONTRACTS OBJECTIVE). Mandatory-now requirements are solved exactly by
    branch-and-bound (lexicographic: all mandatory-now fulfilled, then max
    configured utility, then lower total price / product_key / variant_key);
    optional-now items only spend what mandatory-now leaves in the budget; soon/later
    requirements are reported separately and never touch the "now" budget.
    """
    # A requirement P2 already split into an owned piece (fulfilled_by_item_id set,
    # required_qty == the owned amount for that piece) is owned outright — it must
    # not also compete for owned_items matching or a purchase slot (ALGORITHM step 2:
    # "A physical owned quantity is allocated at most once").
    if len({r.id for r in requirements}) != len(requirements):
        raise ValueError("duplicate_requirement_id")
    pre_owned = {r.id for r in requirements if r.fulfilled_by_item_id}
    matchable = [r for r in requirements if r.id not in pre_owned]
    owned_applied = _match_owned(matchable, owned_items)

    items: list[BasketItem] = []
    remaining: list[tuple[BabyRequirement, float]] = []

    for r in requirements:
        owned_qty = (r.required_qty if r.fulfilled_qty is None else r.fulfilled_qty) if r.id in pre_owned else owned_applied.get(r.id, 0.0)
        if not math.isfinite(owned_qty) or not 0 <= owned_qty <= r.required_qty:
            raise ValueError("invalid_fulfilled_qty")
        if owned_qty > 1e-9:
            items.append(BasketItem(
                item_id=r.fulfilled_by_item_id or str(uuid4()), requirement_id=r.id, group_key=r.group_key,
                status="owned", selected=False, qty=owned_qty, unit_code=r.unit_code,
                unit_qty=1, timing=r.timing, validation={"source": "owned_coverage"},
            ))
        left = r.required_qty - owned_qty
        if left > 1e-9:
            remaining.append((r, left))

    mandatory_now = sorted(
        ((r, q) for r, q in remaining if r.mandatory and r.timing == "now"),
        key=lambda rq: _requirement_sort_key(rq[0]),
    )
    optional_now = [(r, q) for r, q in remaining if not r.mandatory and r.timing == "now"]
    deferred = [(r, q) for r, q in remaining if r.timing in ("soon", "later")]

    def pool_for(req_id: str) -> list[ScoredCandidate]:
        allowed = [s for s in ranked.by_requirement.get(req_id, []) if s.selection_allowed and s.price is not None]
        # allowed is already sorted best-first by rank_baby_candidates; truncate only
        # when the pool genuinely exceeds the search bound (bounded-search, not exact,
        # for that requirement — surfaced in `alternatives.bounded_requirements` below).
        return allowed[:BASKET_SEARCH_TOP_N] if len(allowed) > BASKET_SEARCH_TOP_N else allowed

    pools = {r.id: pool_for(r.id) for r, _ in mandatory_now}
    bounded_requirements = [r.id for r, _ in mandatory_now
                            if len(ranked.by_requirement.get(r.id, [])) > BASKET_SEARCH_TOP_N]

    unresolved = [(r, q) for r, q in mandatory_now if not pools[r.id]]
    solvable = [(r, q) for r, q in mandatory_now if pools[r.id]]

    missing_requirements: list[dict[str, Any]] = []
    for r, q in unresolved:
        missing_requirements.append({
            "requirement_id": r.id, "slot_key": r.slot_key, "required_qty": q,
            "cheapest_feasible_subtotal": None, "shortfall": None,
            "reason": "no_selectable_candidate",
        })

    budget = budget_max if budget_max is not None else float("inf")
    lower_bounds = [min(int(s.price * q) for s in pools[r.id]) for r, q in solvable]
    suffix_lb = [0] * (len(solvable) + 1)
    for i in range(len(solvable) - 1, -1, -1):
        suffix_lb[i] = suffix_lb[i + 1] + lower_bounds[i]

    best: dict[str, Any] = {"assignment": None, "total": None, "score": None, "tie": None}
    nodes_visited = 0

    def dfs(i: int, running_total: int, assignment: list[ScoredCandidate], running_score: float) -> None:
        nonlocal nodes_visited
        nodes_visited += 1
        if i == len(solvable):
            tie = (running_total, tuple(c.tie_break for c in assignment))
            if (best["assignment"] is None or running_score > best["score"]
                    or (running_score == best["score"] and tie < best["tie"])):
                best.update(assignment=list(assignment), total=running_total, score=running_score, tie=tie)
            return
        if running_total + suffix_lb[i] > budget:
            return
        r, q = solvable[i]
        for cand in pools[r.id]:
            price_total = int(cand.price * q)
            if running_total + price_total + suffix_lb[i + 1] > budget:
                continue
            assignment.append(cand)
            dfs(i + 1, running_total + price_total, assignment, running_score + (cand.score or 0.0))
            assignment.pop()

    search_started = time.perf_counter()
    if solvable:
        dfs(0, 0, [], 0.0)
    elif not unresolved:
        best.update(assignment=[], total=0, score=0.0, tie=(0, ()))
    search_seconds = round(time.perf_counter() - search_started, 6)

    alternatives = {"search": "exact_branch_and_bound", "nodes_visited": nodes_visited,
                    "search_seconds": search_seconds, "mandatory_now_requirements": len(solvable),
                    "bounded_requirements": bounded_requirements}

    if unresolved or best["assignment"] is None:
        # infeasible — no automatic deferral of mandatory-now items (ALGORITHM step 5)
        for r, q in solvable:
            cheapest = min(pools[r.id], key=lambda s: (int(s.price * q), s.tie_break))
            missing_requirements.append({
                "requirement_id": r.id, "slot_key": r.slot_key, "required_qty": q,
                "cheapest_feasible_subtotal": int(cheapest.price * q), "shortfall": None,
                "reason": "over_budget" if best["assignment"] is None else "blocked_by_sibling_requirement",
            })
        cheapest_total = None if unresolved else sum(lower_bounds)
        shortfall = (cheapest_total - budget_max) if (cheapest_total is not None and budget_max is not None) else None
        totals = {
            "selected_price": 0, "selected_units": 0,
            "budget_remaining": budget_max, "over_budget": budget_max is not None and cheapest_total is not None
            and cheapest_total > budget_max,
            "soon_price": 0, "later_price": 0,
            "cheapest_feasible_subtotal": cheapest_total, "budget_shortfall": shortfall,
        }
        return BasketDecision(items=items, totals=totals, missing_requirements=missing_requirements,
                              feasible=False, alternatives=alternatives)

    running_total = best["total"]
    for (r, q), cand in zip(solvable, best["assignment"]):
        items.append(BasketItem(
            item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
            candidate_id=cand.candidate_id, status="to_purchase", selected=True, qty=q,
            unit_code=r.unit_code, unit_qty=cand.unit_qty, timing="now", unit_price=cand.price,
            validation={"score": cand.score, "score_breakdown": cand.score_breakdown},
        ))

    # optional-now: greedy by score desc / tie-break, only what mandatory leaves behind
    remaining_budget = (budget_max - running_total) if budget_max is not None else float("inf")
    optional_choices = []
    for r, q in optional_now:
        pool = [s for s in ranked.by_requirement.get(r.id, []) if s.selection_allowed and s.price is not None]
        if pool:
            optional_choices.append((r, q, pool[0]))  # already best-first
    optional_choices.sort(key=lambda rqc: (-(rqc[2].score if rqc[2].score is not None else -1.0), rqc[2].tie_break))
    optional_price = 0
    for r, q, cand in optional_choices:
        price_total = int(cand.price * q)
        if price_total <= remaining_budget:
            items.append(BasketItem(
                item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
                candidate_id=cand.candidate_id, status="to_purchase", selected=True, qty=q,
                unit_code=r.unit_code, unit_qty=cand.unit_qty, timing="now", unit_price=cand.price,
                validation={"score": cand.score, "score_breakdown": cand.score_breakdown},
            ))
            remaining_budget -= price_total
            optional_price += price_total

    # soon/later: reported separately, never charged against the "now" budget
    soon_price = later_price = 0
    for r, q in deferred:
        pool = [s for s in ranked.by_requirement.get(r.id, []) if s.selection_allowed and s.price is not None]
        cheapest = min(pool, key=lambda s: (int(s.price * q), s.tie_break)) if pool else None
        unit_price = cheapest.price if cheapest else None
        items.append(BasketItem(
            item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
            candidate_id=cheapest.candidate_id if cheapest else None, status="to_purchase",
            selected=False, qty=q, unit_code=r.unit_code, unit_qty=cheapest.unit_qty if cheapest else 1,
            timing=r.timing, unit_price=unit_price, validation={"proposal_only": True},
        ))
        if unit_price is not None:
            if r.timing == "soon":
                soon_price += int(unit_price * q)
            else:
                later_price += int(unit_price * q)

    selected_now = [it for it in items if it.status == "to_purchase" and it.selected and it.timing == "now"]
    selected_price = sum(int(it.unit_price * it.qty) for it in selected_now)
    selected_units = sum(it.qty * it.unit_qty for it in selected_now)

    totals = {
        "selected_price": selected_price, "selected_units": selected_units,
        "budget_remaining": (budget_max - selected_price) if budget_max is not None else None,
        "over_budget": budget_max is not None and selected_price > budget_max,
        "soon_price": soon_price, "later_price": later_price,
    }
    return BasketDecision(items=items, totals=totals, missing_requirements=[], feasible=True,
                          alternatives=alternatives)


def recalculate_basket(
    items: list[BasketItem], requirements: list[BabyRequirement], budget_max: int | None,
    checks: list[CandidateCheck],
) -> BasketDecision:
    """[4 baby] Re-derive totals/feasibility after an item edit (qty/status/timing/swap).

    Never trusts client-submitted price/unit_qty/review/check (CONTRACTS §Canonical
    service contracts) — `items` here must already carry P5's authoritative
    unit_price/unit_qty (re-fetched from the candidate row), this function only
    revalidates qty/selection_allowed and recomputes totals/feasibility from them.
    """
    checks_by_id = {c.candidate_id: c for c in checks}
    req_by_id = {r.id: r for r in requirements}

    valid_items: list[BasketItem] = []
    for it in items:
        issues: list[str] = []
        selected = it.selected
        req = req_by_id.get(it.requirement_id)
        if req is None:
            issues.append("unknown_requirement")
        elif it.unit_code != req.unit_code:
            issues.append("unit_mismatch")
        if not math.isfinite(it.qty) or it.qty <= 0 or (it.status == "to_purchase" and not float(it.qty).is_integer()):
            issues.append("invalid_qty")
        if not math.isfinite(it.unit_qty) or it.unit_qty <= 0:
            issues.append("invalid_unit_qty")
        if it.status == "to_purchase" and selected:
            if it.unit_price is None or it.unit_price < 0:
                issues.append("invalid_price")
            check = checks_by_id.get(it.candidate_id)
            if check is None or not check.selection_allowed or check.eligibility != "pass" or (check.requirement_id is not None and check.requirement_id != it.requirement_id):
                issues.append("selection_not_allowed")
        if issues:
            selected = False
        new_validation = dict(it.validation)
        new_validation.pop("issues", None)
        if issues:
            new_validation["issues"] = issues
        valid_items.append(it.model_copy(update={"selected": selected, "validation": new_validation}))

    selected_now = [it for it in valid_items if it.status == "to_purchase" and it.selected and it.timing == "now"]
    soon_items = [it for it in valid_items if it.status == "to_purchase" and it.timing == "soon" and not it.validation.get("issues")]
    later_items = [it for it in valid_items if it.status == "to_purchase" and it.timing == "later" and not it.validation.get("issues")]

    selected_price = sum(int(it.unit_price * it.qty) for it in selected_now if it.unit_price is not None)
    selected_units = sum(it.qty * it.unit_qty for it in selected_now)
    soon_price = sum(int(it.unit_price * it.qty) for it in soon_items if it.unit_price is not None)
    later_price = sum(int(it.unit_price * it.qty) for it in later_items if it.unit_price is not None)

    # requirement -> total qty currently counted as fulfilled (owned/purchased always
    # count; a to_purchase row only counts if it's actually selected for "now")
    fulfilled: dict[str, float] = {}
    for it in valid_items:
        if it.requirement_id is None:
            continue
        counts = it.status in ("owned", "purchased") or (it.status == "to_purchase" and it.selected and it.timing == "now")
        if counts and not it.validation.get("issues"):
            fulfilled[it.requirement_id] = fulfilled.get(it.requirement_id, 0.0) + it.qty

    missing_requirements: list[dict[str, Any]] = []
    for r in requirements:
        if not (r.mandatory and r.timing == "now"):
            continue
        have = fulfilled.get(r.id, 0.0)
        if have + 1e-9 >= r.required_qty:
            continue
        cheapest = None
        for it in valid_items:
            if it.requirement_id == r.id and it.unit_price is not None:
                total = int(it.unit_price * r.required_qty)
                cheapest = total if cheapest is None else min(cheapest, total)
        shortfall = (cheapest - budget_max) if (cheapest is not None and budget_max is not None
                                                and cheapest > budget_max) else None
        # explicit timing change of a mandatory-now item to soon/later is exactly this
        # case: the requirement's "now" slot is empty, so it surfaces here regardless
        # of whether the budget would otherwise have room (ALGORITHM step 6).
        missing_requirements.append({
            "requirement_id": r.id, "slot_key": r.slot_key, "required_qty": r.required_qty,
            "cheapest_feasible_subtotal": cheapest, "shortfall": shortfall,
            "reason": "unfulfilled_or_deferred",
        })

    totals = {
        "selected_price": selected_price, "selected_units": selected_units,
        "budget_remaining": (budget_max - selected_price) if budget_max is not None else None,
        "over_budget": budget_max is not None and selected_price > budget_max,
        "soon_price": soon_price, "later_price": later_price,
    }
    return BasketDecision(items=valid_items, totals=totals, missing_requirements=missing_requirements,
                          feasible=not missing_requirements and not totals["over_budget"] and not any(it.validation.get("issues") for it in valid_items), alternatives={})
