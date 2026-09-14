"""P4 basket optimizer — rank_baby_candidates / optimize_baby / recalculate_basket.

Pure-function tests only (no DB/HTTP/RAG): every ACCEPTANCE FIXTURE from
docs/agent-tasks/baby/P4_basket_optimizer.md (OP01-OP08), plus a brute-force oracle
proving optimize_baby's branch-and-bound search finds the same optimum as exhaustive
enumeration on tiny generated cases (CONTRACTS ALGORITHM step 4 / VERIFY).
"""
from __future__ import annotations

from itertools import product as iproduct

import pytest

from src.dto import BabyCandidate, BabyRequirement, BasketItem, CandidateCheck
from src.engine.stage3b_rank import rank_baby_candidates
from src.engine.stage4_optimize import optimize_baby, recalculate_basket

PROFILE = {"score_method_version": "test-v1", "weights": {"price": 1.0}}


def req(rid, slot, qty=1, mandatory=True, timing="now", unit_code="each", group_key=None):
    return BabyRequirement(id=rid, revision_id="rev", slot_key=slot, group_key=group_key,
                           required_qty=qty, unit_code=unit_code, mandatory=mandatory, timing=timing)


def cand(cid, rid, slot, price, *, product_key=None, variant_key="v1", pack_quantity=1, unit_qty=1,
        unit_code="each", review_rating=None):
    return BabyCandidate(
        candidate_id=cid, requirement_id=rid, product_id="p", variant_id="v",
        product_key=cid if product_key is None else product_key, variant_key=variant_key, name=cid,
        slot_key=slot, price=price, pack_quantity=pack_quantity, unit_qty=unit_qty, unit_code=unit_code,
        review_summary={"avg_rating": review_rating} if review_rating is not None else None,
    )


def check(cid, *, selection_allowed=True, eligibility="pass", verification="verified", coverage="full"):
    return CandidateCheck(candidate_id=cid, eligibility=eligibility, verification=verification,
                          coverage=coverage, selection_allowed=selection_allowed)


def _optimize(requirements, candidates, checks, owned_items=None, budget_max=None, profile=None):
    ranked = rank_baby_candidates(requirements, candidates, checks, profile or PROFILE)
    return ranked, optimize_baby(requirements, ranked, owned_items or [], budget_max)


# ── OP01 — naive greedy fails, optimizer finds the fitting combination ─────────
def test_op01_optimizer_finds_combination_naive_first_choice_misses():
    requirements = [req("rA", "A", qty=1), req("rB", "B", qty=1)]
    candidates = [
        cand("a60", "rA", "A", 60), cand("a40", "rA", "A", 40),
        cand("b60", "rB", "B", 60),
    ]
    checks = [check("a60"), check("a40"), check("b60")]

    ranked, decision = _optimize(requirements, candidates, checks, budget_max=100)

    # naive "best score first" (a60, cheapest-price axis would rank a40 first anyway,
    # so pick a case where price-only ranking still needs the search: both A options
    # score differently but only one combination fits)
    assert decision.feasible is True
    picked_a = next(i for i in decision.items if i.requirement_id == "rA").candidate_id
    picked_b = next(i for i in decision.items if i.requirement_id == "rB").candidate_id
    assert picked_a == "a40" and picked_b == "b60"
    assert decision.totals["selected_price"] == 100


def test_op01_naive_per_slot_top1_would_have_failed():
    """Sanity check that this fixture actually requires search, not luck: a60 alone
    scores no differently from a40 in a single-slot ranking that doesn't consider B."""
    requirements = [req("rA", "A", qty=1)]
    candidates = [cand("a60", "rA", "A", 60), cand("a40", "rA", "A", 40)]
    checks = [check("a60"), check("a40")]
    ranked = rank_baby_candidates(requirements, candidates, checks, PROFILE)
    # price axis ranks a40 first regardless — so a60+b60=120 really would be the naive
    # "first pick per slot ignoring budget interaction" failure the fixture describes
    assert ranked.by_requirement["rA"][0].candidate_id == "a40"


# ── OP02 — infeasible mandatory basket reports shortfall, nothing silently dropped ──
def test_op02_infeasible_reports_shortfall_not_removal_or_deferral():
    requirements = [req("rA", "A", qty=1), req("rB", "B", qty=1)]
    candidates = [cand("a", "rA", "A", 60), cand("b", "rB", "B", 50)]
    checks = [check("a"), check("b")]

    _, decision = _optimize(requirements, candidates, checks, budget_max=100)

    assert decision.feasible is False
    assert decision.totals["cheapest_feasible_subtotal"] == 110
    assert decision.totals["budget_shortfall"] == 10
    assert decision.totals["selected_price"] == 0
    ids = {m["requirement_id"] for m in decision.missing_requirements}
    assert ids == {"rA", "rB"}
    # nothing was moved to soon/later or silently excluded
    assert decision.items == []


# ── OP03 — owned/purchased items excluded from the charged total ──────────────
def test_op03_owned_and_purchased_excluded_from_charge():
    requirements = [req("r-stroller", "stroller", qty=1), req("r-bottle", "bottle", qty=1)]
    candidates = [cand("stroller-buy", "r-stroller", "stroller", 999),  # irrelevant, already owned
                 cand("bottle-buy", "r-bottle", "bottle", 20)]
    checks = [check("stroller-buy"), check("bottle-buy")]
    owned_items = [{"slot_key": "stroller", "unit_code": "each", "qty": 1}]

    _, decision = _optimize(requirements, candidates, checks, owned_items=owned_items, budget_max=100)

    assert decision.feasible is True
    assert decision.totals["selected_price"] == 20
    owned_item = next(i for i in decision.items if i.requirement_id == "r-stroller")
    assert owned_item.status == "owned" and owned_item.unit_price is None
    purchased_item = next(i for i in decision.items if i.requirement_id == "r-bottle")
    assert purchased_item.status == "to_purchase" and purchased_item.unit_price == 20


def test_op03_purchased_status_excluded_by_recalculate():
    requirements = [req("r-bottle", "bottle", qty=1)]
    items = [BasketItem(item_id="i1", requirement_id="r-bottle", status="purchased", selected=False,
                        qty=1, unit_code="each", unit_qty=1, timing="now", unit_price=20)]
    decision = recalculate_basket(items, requirements, budget_max=100, checks=[])
    assert decision.totals["selected_price"] == 0  # already purchased, not re-charged
    assert decision.feasible is True  # counts toward fulfillment


# ── OP04 — pack quantity does not get multiplied into price ────────────────────
def test_op04_pack_quantity_not_multiplied_into_price():
    requirements = [req("r-diaper", "diaper", qty=2, unit_code="pack")]
    candidates = [cand("diaper-pack", "r-diaper", "diaper", 10_000, pack_quantity=1, unit_qty=40,
                      unit_code="pack")]
    checks = [check("diaper-pack")]

    _, decision = _optimize(requirements, candidates, checks, budget_max=1_000_000)

    assert decision.feasible is True
    item = decision.items[0]
    assert item.qty == 2
    assert item.unit_price == 10_000
    assert decision.totals["selected_price"] == 20_000          # not 800,000
    assert decision.totals["selected_units"] == 80               # 2 packs * 40 pieces


# ── OP05 — recalled/unknown-safety candidates cannot be auto-selected ─────────
def test_op05_recalled_rejected_unknown_safety_not_selected_missing_review_still_eligible():
    requirements = [req("r-seat", "car_seat", qty=1)]
    candidates = [
        cand("recalled-cheap", "r-seat", "car_seat", 10),
        cand("unknown-cert", "r-seat", "car_seat", 20),
        cand("no-review", "r-seat", "car_seat", 30),   # review_summary=None, still eligible
    ]
    checks = [
        check("recalled-cheap", selection_allowed=False, eligibility="fail"),
        check("unknown-cert", selection_allowed=False, eligibility="unknown"),
        check("no-review", selection_allowed=True, eligibility="pass"),
    ]

    _, decision = _optimize(requirements, candidates, checks, budget_max=1000,
                            profile={"score_method_version": "t", "weights": {"price": 0.7, "review": 0.3}})

    assert decision.feasible is True
    picked = decision.items[0]
    assert picked.candidate_id == "no-review"
    assert picked.unit_price == 30


# ── OP06 — reorder invariance, optional cannot displace mandatory, soon/later free ──
def test_op06_reorder_invariance_and_optional_cannot_displace_mandatory():
    def build(order_requirements, order_candidates):
        requirements = order_requirements
        candidates = order_candidates
        checks = [check("mand"), check("opt")]
        return _optimize(requirements, candidates, checks, budget_max=60)

    r_mand = req("r-mand", "seat", qty=1, mandatory=True)
    r_opt = req("r-opt", "toy", qty=1, mandatory=False)
    c_mand = cand("mand", "r-mand", "seat", 60)
    c_opt = cand("opt", "r-opt", "toy", 10)

    _, d1 = build([r_mand, r_opt], [c_mand, c_opt])
    _, d2 = build([r_opt, r_mand], [c_opt, c_mand])

    assert d1.totals == d2.totals
    ids1 = {i.candidate_id for i in d1.items if i.selected}
    ids2 = {i.candidate_id for i in d2.items if i.selected}
    assert ids1 == ids2 == {"mand"}  # mandatory consumes the whole budget; optional gets nothing
    assert d1.feasible is True


def test_op06_soon_later_do_not_consume_now_budget():
    requirements = [req("r-now", "seat", qty=1, timing="now"),
                   req("r-later", "gate", qty=1, mandatory=False, timing="later")]
    candidates = [cand("now-c", "r-now", "seat", 90), cand("later-c", "r-later", "gate", 90)]
    checks = [check("now-c"), check("later-c")]

    _, decision = _optimize(requirements, candidates, checks, budget_max=100)

    assert decision.feasible is True
    assert decision.totals["selected_price"] == 90
    assert decision.totals["later_price"] == 90
    later_item = next(i for i in decision.items if i.requirement_id == "r-later")
    assert later_item.selected is False and later_item.status == "to_purchase"


# ── OP07 — qty edit/swap recomputes totals; invalid price/qty rejected ────────
def test_op07_qty_edit_recomputes_total_and_over_budget():
    requirements = [req("r-diaper", "diaper", qty=2, unit_code="pack")]
    items = [BasketItem(item_id="i1", requirement_id="r-diaper", candidate_id="c1", status="to_purchase",
                        selected=True, qty=3, unit_code="pack", unit_qty=40, timing="now", unit_price=10_000)]
    checks = [check("c1")]

    decision = recalculate_basket(items, requirements, budget_max=25_000, checks=checks)

    assert decision.totals["selected_price"] == 30_000
    assert decision.totals["over_budget"] is True
    assert decision.feasible is False  # demand covered, but the basket exceeds budget


def test_op07_negative_or_missing_price_rejected():
    requirements = [req("r-a", "a", qty=1)]
    items = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c1", status="to_purchase",
                        selected=True, qty=1, unit_code="each", unit_qty=1, timing="now", unit_price=-5)]
    decision = recalculate_basket(items, requirements, budget_max=100, checks=[check("c1")])
    assert decision.items[0].selected is False
    assert "invalid_price" in decision.items[0].validation["issues"]
    assert decision.feasible is False  # mandatory requirement now unfulfilled


def test_op07_zero_qty_rejected():
    requirements = [req("r-a", "a", qty=1)]
    items = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c1", status="to_purchase",
                        selected=True, qty=0, unit_code="each", unit_qty=1, timing="now", unit_price=10)]
    decision = recalculate_basket(items, requirements, budget_max=100, checks=[check("c1")])
    assert decision.items[0].selected is False
    assert "invalid_qty" in decision.items[0].validation["issues"]


def test_op07_swap_to_unallowed_candidate_blocks_selection():
    requirements = [req("r-a", "a", qty=1)]
    items = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c-bad", status="to_purchase",
                        selected=True, qty=1, unit_code="each", unit_qty=1, timing="now", unit_price=10)]
    checks = [check("c-bad", selection_allowed=False, eligibility="fail")]
    decision = recalculate_basket(items, requirements, budget_max=100, checks=checks)
    assert decision.items[0].selected is False
    assert "selection_not_allowed" in decision.items[0].validation["issues"]
    assert decision.feasible is False


def test_op07_explicit_timing_change_of_mandatory_now_blocks_confirmation_even_if_budget_fits():
    requirements = [req("r-a", "a", qty=1, mandatory=True, timing="now")]
    items = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c1", status="to_purchase",
                        selected=True, qty=1, unit_code="each", unit_qty=1, timing="later", unit_price=10)]
    decision = recalculate_basket(items, requirements, budget_max=1000, checks=[check("c1")])
    assert decision.feasible is False
    assert decision.missing_requirements[0]["requirement_id"] == "r-a"


# ── OP08 — owned + purchase fill a multi-unit requirement once, unit mismatch fails ──
def test_op08_owned_plus_purchase_fills_required_quantity_once():
    requirements = [req("r-bottle", "bottle", qty=4, unit_code="each")]
    candidates = [cand("bottle-buy", "r-bottle", "bottle", 10)]
    checks = [check("bottle-buy")]
    owned_items = [{"slot_key": "bottle", "unit_code": "each", "qty": 2}]

    _, decision = _optimize(requirements, candidates, checks, owned_items=owned_items, budget_max=100)

    assert decision.feasible is True
    owned_item = next(i for i in decision.items if i.status == "owned")
    purchase_item = next(i for i in decision.items if i.status == "to_purchase")
    assert owned_item.qty == 2
    assert purchase_item.qty == 2  # remaining 4 - 2 owned
    assert decision.totals["selected_price"] == 20


def test_op08_unit_mismatch_cannot_count_fulfillment():
    requirements = [req("r-diaper", "diaper", qty=2, unit_code="pack")]
    candidates = [cand("diaper-pack", "r-diaper", "diaper", 10_000, unit_qty=40, unit_code="pack")]
    checks = [check("diaper-pack")]
    # owned "each" cannot fulfil a "pack" requirement
    owned_items = [{"slot_key": "diaper", "unit_code": "each", "qty": 5}]

    _, decision = _optimize(requirements, candidates, checks, owned_items=owned_items, budget_max=100_000)

    assert not any(i.status == "owned" for i in decision.items)
    purchase_item = next(i for i in decision.items if i.status == "to_purchase")
    assert purchase_item.qty == 2  # full required qty, owned mismatch ignored


# ── Rank axis: absent review is a typed null, not a fabricated neutral value ───
def test_rank_absent_review_excluded_from_weighted_average_not_fabricated():
    requirements = [req("r-a", "a", qty=1)]
    candidates = [cand("with-review", "r-a", "a", 100, review_rating=5.0),
                 cand("no-review", "r-a", "a", 100, review_rating=None)]
    checks = [check("with-review"), check("no-review")]
    profile = {"score_method_version": "t", "weights": {"price": 0.5, "review": 0.5}}

    ranked = rank_baby_candidates(requirements, candidates, checks, profile)
    scored = {s.candidate_id: s for s in ranked.by_requirement["r-a"]}

    assert "review" not in scored["no-review"].score_breakdown
    assert scored["no-review"].score == pytest.approx(scored["with-review"].score_breakdown["price"] * 0.5 / 0.5)
    assert scored["with-review"].score == pytest.approx(1.0)  # both axes maxed


def test_rank_structurally_invalid_candidates_tracked_not_dropped_silently():
    requirements = [req("r-a", "a", qty=1)]
    candidates = [cand("bad-price", "r-a", "a", -5), cand("ok", "r-a", "a", 10)]
    checks = [check("bad-price"), check("ok")]
    ranked = rank_baby_candidates(requirements, candidates, checks, PROFILE)
    assert any(e["candidate_id"] == "bad-price" and e["reason"] == "invalid_price" for e in ranked.excluded)
    assert [s.candidate_id for s in ranked.by_requirement["r-a"]] == ["ok"]


# ── Brute-force oracle: branch-and-bound == exhaustive enumeration on tiny cases ──
def _brute_force_best(requirements, ranked, budget_max):
    """Exhaustively enumerate every combination of one candidate per mandatory-now
    requirement and return the best feasible (max score, then price/key tie-break),
    or None if infeasible. Mirrors optimize_baby's own objective so we can assert
    the two agree without re-deriving optimize_baby's internal state."""
    mandatory_now = [r for r in requirements if r.mandatory and r.timing == "now"]
    pools = []
    for r in mandatory_now:
        allowed = [s for s in ranked.by_requirement.get(r.id, []) if s.selection_allowed and s.price is not None]
        if not allowed:
            return None
        pools.append([(r, s) for s in allowed])

    best = None
    for combo in iproduct(*pools):
        total = sum(int(s.price * r.required_qty) for r, s in combo)
        if budget_max is not None and total > budget_max:
            continue
        score = sum((s.score or 0.0) for _, s in combo)
        tie = (total, tuple(s.tie_break for _, s in combo))
        key = (-score, tie)
        if best is None or key < best[0]:
            best = (key, total)
    return best[1] if best else None


# ── D4 — develop `da79839` DB alignment (P4_basket_optimizer.md ACTIVE DB CONTRACT) ──
# Pure-function level only: real DB round-trip for the same owned/fulfilled_qty shape
# is covered by tests/test_p1234_review_fixes.py::test_partial_owned_survives_storage_and_recalculation
# (persist_baby_requirements -> load_persisted_baby_requirements -> optimize_baby).
def test_d4_total2_owned1_purchases_only_remaining1():
    r = req("r-bottle", "bottle", qty=2).model_copy(update={
        "owned": [{"source_condition_id": "cond-1", "label": "젖병", "qty": 1, "unit_code": "each"}],
        "fulfilled_qty": 1,
    })
    candidates = [cand("bottle-buy", "r-bottle", "bottle", 10)]
    checks = [check("bottle-buy")]

    _, decision = _optimize([r], candidates, checks, budget_max=100)

    assert decision.feasible is True
    owned_item = next(i for i in decision.items if i.status == "owned")
    purchase_item = next(i for i in decision.items if i.status == "to_purchase")
    assert owned_item.qty == 1
    assert purchase_item.qty == 1          # 2 required - 1 owned, not 2
    assert decision.totals["selected_price"] == 10


def test_d4_owned_alone_does_not_wrongly_satisfy_full_requirement():
    """owned=1 of required=2 with NO purchasable candidate must stay infeasible —
    a requirement.owned entry existing must never be misread as 'fully covered'."""
    r = req("r-bottle", "bottle", qty=2).model_copy(update={
        "owned": [{"source_condition_id": "cond-1", "label": "젖병", "qty": 1, "unit_code": "each"}],
        "fulfilled_qty": 1,
    })
    ranked = rank_baby_candidates([r], [], [], PROFILE)
    decision = optimize_baby([r], ranked, [], 100)

    assert decision.feasible is False
    assert sum(i.qty for i in decision.items if i.status == "owned") == 1
    assert any(m["requirement_id"] == "r-bottle" for m in decision.missing_requirements)


def test_d4_invalid_fulfilled_qty_rejected():
    bad = req("r-a", "a", qty=1).model_copy(update={
        "owned": [{"source_condition_id": "c", "label": "x", "qty": 5, "unit_code": "each"}],
        "fulfilled_qty": 5,   # exceeds required_qty=1 — must never be silently clamped/trusted
    })
    ranked = rank_baby_candidates([bad], [], [], PROFILE)
    with pytest.raises(ValueError, match="invalid_fulfilled_qty"):
        optimize_baby([bad], ranked, [], 100)


def test_d4_duplicate_requirement_id_rejected():
    r1 = req("dup", "a", qty=1)
    r2 = req("dup", "b", qty=1)
    ranked = rank_baby_candidates([r1, r2], [], [], PROFILE)
    with pytest.raises(ValueError, match="duplicate_requirement_id"):
        optimize_baby([r1, r2], ranked, [], 100)


def test_d4_candidate_check_requirement_mismatch_excluded_from_ranking():
    """A CandidateCheck whose own requirement_id names a DIFFERENT requirement than
    the candidate's must never be trusted for that candidate (DEVELOP_DB_TRANSITION.md
    'Candidate edits and confirmation' / P4 DELTA: verify CandidateCheck.requirement_id
    match before using it)."""
    requirements = [req("r-a", "a", qty=1)]
    candidates = [cand("c1", "r-a", "a", 10)]
    checks = [CandidateCheck(candidate_id="c1", requirement_id="r-other", eligibility="pass",
                            verification="verified", coverage="full", selection_allowed=True)]

    ranked = rank_baby_candidates(requirements, candidates, checks, PROFILE)

    assert ranked.by_requirement["r-a"] == []
    assert any(e["candidate_id"] == "c1" and e["reason"] == "requirement_mismatch" for e in ranked.excluded)


def test_d4_candidate_unit_code_mismatch_excluded_from_ranking():
    """A candidate whose unit_code doesn't match its requirement's unit_code (a stale
    swap or data bug) is excluded from ranking, not silently scored and selected."""
    requirements = [req("r-diaper", "diaper", qty=2, unit_code="pack")]
    candidates = [cand("wrong-unit", "r-diaper", "diaper", 10, unit_code="each")]
    checks = [check("wrong-unit")]

    ranked = rank_baby_candidates(requirements, candidates, checks, PROFILE)

    assert ranked.by_requirement["r-diaper"] == []
    assert any(e["candidate_id"] == "wrong-unit" and e["reason"] == "unit_mismatch" for e in ranked.excluded)


def test_d4_unconfigured_search_unknown_candidate_not_selected():
    """A candidate whose safety check is 'unknown' because no search/manual was
    configured (P3-D3-01 boundary) must not be auto-selected even when it is the
    cheapest option and no other candidate exists."""
    requirements = [req("r-seat", "car_seat", qty=1)]
    candidates = [cand("only-option", "r-seat", "car_seat", 5)]
    checks = [check("only-option", selection_allowed=False, eligibility="unknown")]

    _, decision = _optimize(requirements, candidates, checks, budget_max=1000)

    assert decision.feasible is False
    assert not any(i.selected for i in decision.items)


def test_d4_purchase_qty_99_allowed_100_rejected():
    requirements = [req("r-a", "a", qty=1)]
    checks = [check("c1")]

    ok_item = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c1", status="to_purchase",
                          selected=True, qty=99, unit_code="each", unit_qty=1, timing="now", unit_price=1)]
    ok = recalculate_basket(ok_item, requirements, budget_max=1000, checks=checks)
    assert ok.items[0].selected is True
    assert "issues" not in ok.items[0].validation

    bad_item = [BasketItem(item_id="i1", requirement_id="r-a", candidate_id="c1", status="to_purchase",
                           selected=True, qty=100, unit_code="each", unit_qty=1, timing="now", unit_price=1)]
    bad = recalculate_basket(bad_item, requirements, budget_max=1000, checks=checks)
    assert bad.items[0].selected is False
    assert "invalid_qty" in bad.items[0].validation["issues"]


@pytest.mark.parametrize("seed", range(8))
def test_branch_and_bound_matches_brute_force_oracle_on_tiny_random_cases(seed):
    import random
    rng = random.Random(seed)
    n_req = rng.randint(1, 3)
    requirements = [req(f"r{i}", f"slot{i}", qty=1) for i in range(n_req)]
    candidates, checks = [], []
    for i in range(n_req):
        n_cand = rng.randint(1, 3)
        for j in range(n_cand):
            price = rng.randint(1, 50)
            cid = f"c{i}_{j}"
            candidates.append(cand(cid, f"r{i}", f"slot{i}", price))
            checks.append(check(cid, selection_allowed=rng.random() > 0.2))
    budget_max = rng.randint(10, 120)

    ranked = rank_baby_candidates(requirements, candidates, checks, PROFILE)
    decision = optimize_baby(requirements, ranked, [], budget_max)
    oracle_total = _brute_force_best(requirements, ranked, budget_max)

    if oracle_total is None:
        assert decision.feasible is False
    else:
        assert decision.feasible is True
        assert decision.totals["selected_price"] == oracle_total
