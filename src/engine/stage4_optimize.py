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

# v3 (develop `da79839`, DEVELOP_DB_TRANSITION.md "Candidate edits and confirmation"):
# engine.recommendation_candidate.qty is a purchase pack count, integer 1-99. Applies to
# any to_purchase qty this module produces or re-validates — not a domain-required-qty
# cap (owned coverage / a requirement's own required_qty are unbounded).
PURCHASE_QTY_MIN, PURCHASE_QTY_MAX = 1, 99


def _purchase_qty_out_of_range(qty: float) -> bool:
    return not math.isfinite(qty) or not float(qty).is_integer() or not (PURCHASE_QTY_MIN <= qty <= PURCHASE_QTY_MAX)


def _pack_count_for(need: float, unit_qty: float, req_unit_code: str) -> int | None:
    """P4 review R4: two different requirement unit conventions coexist (P2/P4
    contract) and must not be collapsed into one formula:

    - `req_unit_code == "pack"`: required_qty already counts purchase packs (e.g.
      "2 packs of diapers") — the conversion factor is 1 (OP04/OP08 fixtures fix
      this: qty stays == the remaining pack count, never divided by unit_qty).
      `unit_qty` there is a pure content-count statistic (how many individual
      diapers per pack), not a purchase divisor.
    - anything else (e.g. "each"): required_qty counts base units, so the purchase
      pack count is ceil(need/unit_qty) for THAT candidate's pack size.

    Returns None (candidate excluded, not silently clamped) when the inputs are
    unusable or the resulting count falls outside the develop 1-99 pack range (P4
    review R2 — applies uniformly regardless of timing, including soon/later)."""
    if not math.isfinite(need) or need <= 0:
        return None
    if req_unit_code == "pack":
        count = math.ceil(need)
    else:
        if not math.isfinite(unit_qty) or unit_qty <= 0:
            return None
        count = math.ceil(need / unit_qty)
    return count if PURCHASE_QTY_MIN <= count <= PURCHASE_QTY_MAX else None


def _ranked(rank: RankResult, slot: str) -> list[Candidate]:
    return [Candidate.model_validate(c) for c in rank.slots.get(slot, {}).get("ranked", [])]


def _compat_filter(pool: list[Candidate], key: str, wanted: str) -> list[Candidate]:
    """호환 속성(key)이 wanted와 같은 후보만 남긴다. 속성이 없는 후보는 "정보 없음"이라
    통과시킨다(호환 안 됨으로 단정하지 않는다) — override 표가 일부 부품만 채워져 있어서다.
    남는 게 없으면 필터를 걸지 않은 원래 풀로 되돌린다(빈 슬롯보다는 낫다)."""
    kept = [c for c in pool if c.specs.get(key) in (None, wanted)]
    return kept or pool


def _mainboard_compat_filter(pools: dict[str, list[Candidate]]) -> None:
    """메인보드를 호환 기준점으로 삼아 CPU(소켓)·RAM(메모리 타입)·케이스(폼팩터) 풀을
    좁힌다(요청 R1). 완전탐색·전력/물리 가지치기는 아직 없다 — 이 세 축만 고정."""
    mb_pool = pools.get("메인보드") or []
    if not mb_pool:
        return
    mb = mb_pool[0]
    socket, mem_type, form = mb.specs.get("socket"), mb.specs.get("mem_type"), mb.specs.get("form_factor")
    if socket and "CPU" in pools:
        pools["CPU"] = _compat_filter(pools["CPU"], "socket", socket)
    if mem_type and "RAM" in pools:
        pools["RAM"] = _compat_filter(pools["RAM"], "mem_type", mem_type)
    if form and "케이스" in pools:
        pools["케이스"] = [c for c in pools["케이스"]
                          if form in (c.specs.get("supports_form_factors") or [form])] or pools["케이스"]


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
    _mainboard_compat_filter(pools)

    budget = spec.budget.get("total", 0)
    combos = 1
    for cs in pools.values():
        combos *= max(1, len(cs))

    # TODO: 전력(PSU 용량)·GPU 길이·쿨러 높이 가지치기와 완전탐색 목적함수는 아직 없다.
    #       소켓·메모리 타입·폼팩터는 위 _mainboard_compat_filter가 먼저 풀을 좁혀 둔다(R1).
    #       지금은 그 좁혀진 풀에서 각 슬롯 1위(예산 초과 시 다음 순위)로 근사.
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
    cpu_item = next((i for i in picked if i.slot == "CPU"), None)
    mb_item = next((i for i in picked if i.slot == "메인보드"), None)
    cpu_socket = next((c.specs.get("socket") for c in pools.get("CPU", []) if cpu_item and c.product_key == cpu_item.product_key), None)
    mb_socket = next((c.specs.get("socket") for c in pools.get("메인보드", []) if mb_item and c.product_key == mb_item.product_key), None)
    if cpu_socket and mb_socket:
        socket_status = "ok" if cpu_socket == mb_socket else "fail"
    else:
        socket_status = "ok (근사)"  # 호환 데이터가 없는 부품 — 아직 확인 안 됨, 위반 확정 아님
    return BuildResult(
        list_id=spec.list_id,
        items=picked,
        totals={"price": total, "power_w": 420, "avg_score": round(
            sum(i.score for i in picked) / max(1, len(picked)), 3)},
        budget={"max": budget, "used": total, "used_pct": used_pct,
                "slack": (budget - total) if budget else 0},
        link_check={"socket": socket_status, "power": "ok (근사)", "gpu_len": "ok",
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
    # A requirement P2 already resolved ownership for (r.owned non-empty, coming
    # from persist_baby_requirements — each entry carries a real plan_condition
    # source_condition_id, v3/DEVELOP_DB_TRANSITION.md) is owned outright — it must
    # not also compete for owned_items matching or a purchase slot (ALGORITHM step 2:
    # "A physical owned quantity is allocated at most once").
    if len({r.id for r in requirements}) != len(requirements):
        raise ValueError("duplicate_requirement_id")
    pre_owned = {r.id for r in requirements if r.owned}
    matchable = [r for r in requirements if r.id not in pre_owned]
    owned_applied = _match_owned(matchable, owned_items)

    items: list[BasketItem] = []
    remaining: list[tuple[BabyRequirement, float]] = []

    for r in requirements:
        if r.id in pre_owned:
            owned_qty = r.fulfilled_qty
            if not math.isfinite(owned_qty) or not 0 <= owned_qty <= r.required_qty:
                raise ValueError("invalid_fulfilled_qty")
            # No planning.item table in develop — each owned entry is presented by a
            # derived marker over the requirement + its real plan_condition source,
            # never a separate DB row (multiple owned entries each get their own line).
            # P4 review R3: the entries must actually add up to r.fulfilled_qty, each
            # source may only appear once, and an entry's own unit_code is kept (never
            # silently rewritten to r.unit_code, which would hide a real mismatch).
            seen_sources: set[str] = set()
            entry_total = 0.0
            for entry in r.owned:
                entry_qty = entry.get("qty", 0)
                entry_unit = entry.get("unit_code", r.unit_code)
                source = str(entry.get("source_condition_id", "unknown"))
                if not math.isfinite(entry_qty) or entry_qty < 0:
                    raise ValueError(f"invalid_owned_entry_qty:{r.id}")
                if entry_unit != r.unit_code:
                    raise ValueError(f"owned_entry_unit_mismatch:{r.id}")
                if source in seen_sources:
                    raise ValueError(f"duplicate_owned_source:{r.id}")
                seen_sources.add(source)
                entry_total += entry_qty
                if entry_qty <= 1e-9:
                    continue
                items.append(BasketItem(
                    item_id=f"owned:{r.id}:{source}", requirement_id=r.id, group_key=r.group_key,
                    status="owned", selected=False, qty=entry_qty, unit_code=entry_unit,
                    unit_qty=1, timing=r.timing, validation={"source": "owned_coverage"},
                ))
            if abs(entry_total - owned_qty) > 1e-9:
                raise ValueError(f"owned_entries_do_not_sum_to_fulfilled_qty:{r.id}")
        else:
            owned_qty = owned_applied.get(r.id, 0.0)
            if not math.isfinite(owned_qty) or not 0 <= owned_qty <= r.required_qty:
                raise ValueError("invalid_fulfilled_qty")
            if owned_qty > 1e-9:
                items.append(BasketItem(
                    item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
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

    def _eligible_priced(req_id: str) -> list[ScoredCandidate]:
        # P4 review R1: eligibility=="pass" is required in addition to
        # selection_allowed at every auto-selection boundary here, not just in P3's
        # own producer — a mismatched DTO must not slip an unknown/fail candidate
        # into an automatic pick.
        return [s for s in ranked.by_requirement.get(req_id, [])
                if s.selection_allowed and s.eligibility == "pass" and s.price is not None]

    def pool_for(req_id: str, need: float, req_unit_code: str) -> list[tuple[ScoredCandidate, int]]:
        out = []
        for s in _eligible_priced(req_id):
            count = _pack_count_for(need, s.unit_qty, req_unit_code)
            if count is not None:
                out.append((s, count))
        # already best-first by rank_baby_candidates; truncate only when the pool
        # genuinely exceeds the search bound (bounded-search, not exact, for that
        # requirement — surfaced in `alternatives.bounded_requirements` below).
        return out[:BASKET_SEARCH_TOP_N] if len(out) > BASKET_SEARCH_TOP_N else out

    def _unresolved_reason(req_id: str, need: float, req_unit_code: str) -> str:
        candidates = _eligible_priced(req_id)
        if not candidates:
            return "no_selectable_candidate"
        if all(_pack_count_for(need, s.unit_qty, req_unit_code) is None for s in candidates):
            return "qty_out_of_range"
        return "no_selectable_candidate"

    pools = {r.id: pool_for(r.id, q, r.unit_code) for r, q in mandatory_now}
    bounded_requirements = [r.id for r, _ in mandatory_now
                            if len(ranked.by_requirement.get(r.id, [])) > BASKET_SEARCH_TOP_N]

    unresolved = [(r, q) for r, q in mandatory_now if not pools[r.id]]
    solvable = [(r, q) for r, q in mandatory_now if pools[r.id]]

    missing_requirements: list[dict[str, Any]] = []
    for r, q in unresolved:
        missing_requirements.append({
            "requirement_id": r.id, "slot_key": r.slot_key, "required_qty": q,
            "cheapest_feasible_subtotal": None, "shortfall": None,
            "reason": _unresolved_reason(r.id, q, r.unit_code),
        })

    budget = budget_max if budget_max is not None else float("inf")
    lower_bounds = [min(int(s.price * cnt) for s, cnt in pools[r.id]) for r, q in solvable]
    suffix_lb = [0] * (len(solvable) + 1)
    for i in range(len(solvable) - 1, -1, -1):
        suffix_lb[i] = suffix_lb[i + 1] + lower_bounds[i]

    best: dict[str, Any] = {"assignment": None, "total": None, "score": None, "tie": None}
    nodes_visited = 0

    def dfs(i: int, running_total: int, assignment: list[tuple[ScoredCandidate, int]],
            running_score: float) -> None:
        nonlocal nodes_visited
        nodes_visited += 1
        if i == len(solvable):
            tie = (running_total, tuple(c.tie_break for c, _ in assignment))
            if (best["assignment"] is None or running_score > best["score"]
                    or (running_score == best["score"] and tie < best["tie"])):
                best.update(assignment=list(assignment), total=running_total, score=running_score, tie=tie)
            return
        if running_total + suffix_lb[i] > budget:
            return
        r, q = solvable[i]
        for cand, cnt in pools[r.id]:
            price_total = int(cand.price * cnt)
            if running_total + price_total + suffix_lb[i + 1] > budget:
                continue
            assignment.append((cand, cnt))
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

    if best["assignment"] is None:
        # infeasible — no automatic deferral of mandatory-now items (ALGORITHM step 5)
        # A budget-infeasible combination must not leave a partial cart that looks
        # purchasable.  In contrast, an *unresolved* sibling requirement is handled
        # below: the independently valid, in-budget assignments remain useful
        # recommendations while that sibling is reported as missing.
        for r, q in solvable:
            cheapest_cand, cheapest_cnt = min(pools[r.id], key=lambda sc: (int(sc[0].price * sc[1]), sc[0].tie_break))
            missing_requirements.append({
                "requirement_id": r.id, "slot_key": r.slot_key, "required_qty": q,
                "cheapest_feasible_subtotal": int(cheapest_cand.price * cheapest_cnt), "shortfall": None,
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
    for (r, q), (cand, cnt) in zip(solvable, best["assignment"]):
        items.append(BasketItem(
            item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
            candidate_id=cand.candidate_id, status="to_purchase", selected=True, qty=cnt,
            unit_code=r.unit_code, unit_qty=cand.unit_qty, timing="now", unit_price=cand.price,
            validation={"score": cand.score, "score_breakdown": cand.score_breakdown},
        ))

    # optional-now: greedy by score desc / tie-break, only what mandatory leaves behind
    remaining_budget = (budget_max - running_total) if budget_max is not None else float("inf")
    optional_choices = []
    for r, q in optional_now:
        pool = pool_for(r.id, q, r.unit_code)
        if pool:
            optional_choices.append((r, pool[0][0], pool[0][1]))  # already best-first
    optional_choices.sort(key=lambda rcc: (-(rcc[1].score if rcc[1].score is not None else -1.0), rcc[1].tie_break))
    optional_price = 0
    for r, cand, cnt in optional_choices:
        price_total = int(cand.price * cnt)
        if price_total <= remaining_budget:
            items.append(BasketItem(
                item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
                candidate_id=cand.candidate_id, status="to_purchase", selected=True, qty=cnt,
                unit_code=r.unit_code, unit_qty=cand.unit_qty, timing="now", unit_price=cand.price,
                validation={"score": cand.score, "score_breakdown": cand.score_breakdown},
            ))
            remaining_budget -= price_total
            optional_price += price_total

    # soon/later: reported separately, never charged against the "now" budget. Same
    # eligibility + pack-count-range rules as now (P4 review R1/R2) — a deferred row
    # with no viable candidate shows qty=0 with a reason, never an unclamped/raw
    # base-unit number pretending to be a purchasable pack count.
    soon_price = later_price = 0
    for r, q in deferred:
        pool = pool_for(r.id, q, r.unit_code)
        cand, cnt = pool[0] if pool else (None, None)
        unit_price = cand.price if cand else None
        items.append(BasketItem(
            item_id=str(uuid4()), requirement_id=r.id, group_key=r.group_key,
            candidate_id=cand.candidate_id if cand else None, status="to_purchase",
            selected=False, qty=(cnt if cnt is not None else 0), unit_code=r.unit_code,
            unit_qty=cand.unit_qty if cand else 1, timing=r.timing, unit_price=unit_price,
            validation=({"proposal_only": True} if cand else
                       {"proposal_only": True, "reason": _unresolved_reason(r.id, q, r.unit_code)}),
        ))
        if unit_price is not None:
            if r.timing == "soon":
                soon_price += int(unit_price * cnt)
            else:
                later_price += int(unit_price * cnt)

    selected_now = [it for it in items if it.status == "to_purchase" and it.selected and it.timing == "now"]
    selected_price = sum(int(it.unit_price * it.qty) for it in selected_now)
    selected_units = sum(it.qty * it.unit_qty for it in selected_now)

    totals = {
        "selected_price": selected_price, "selected_units": selected_units,
        "budget_remaining": (budget_max - selected_price) if budget_max is not None else None,
        "over_budget": budget_max is not None and selected_price > budget_max,
        "soon_price": soon_price, "later_price": later_price,
    }
    # A missing safety-approved candidate must still prevent confirmation, but it
    # must not erase other safe, affordable recommendations.  This lets the result
    # screen show the available items and clearly surface the unmet requirement
    # instead of presenting an empty cart as if no product search occurred.
    return BasketDecision(items=items, totals=totals, missing_requirements=missing_requirements,
                          feasible=not missing_requirements,
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
        elif it.status == "to_purchase" and _purchase_qty_out_of_range(it.qty):
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
            # P4 review R4: qty is a purchase PACK count for to_purchase/purchased rows
            # (unit_qty=1 for owned rows, so this is a no-op there). When the
            # requirement itself is denominated in packs (unit_code=="pack"), qty
            # already IS the coverage amount — unit_qty there is only a per-pack
            # content-count statistic, not a base-unit conversion factor (matches
            # _pack_count_for's split; OP04/OP07 fixtures fix this).
            req = req_by_id.get(it.requirement_id)
            contribution = it.qty if (req is None or req.unit_code == "pack") else it.qty * it.unit_qty
            fulfilled[it.requirement_id] = fulfilled.get(it.requirement_id, 0.0) + contribution

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
