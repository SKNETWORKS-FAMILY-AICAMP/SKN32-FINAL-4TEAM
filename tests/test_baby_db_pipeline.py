"""src.pipeline.run_baby_optimizer() — P4 baby computation boundary.

Replaces the old run_baby_db_pipeline greedy adapter (candidate-id-as-item-id,
qty=1/timing=now/price=0 shortcuts) with the real BabyRequirement/BabyCandidate/
CandidateCheck -> BasketDecision path, composed purely from rank_baby_candidates()
and optimize_baby() (no DB/HTTP/RAG).
"""
from src.dto import BabyCandidate, BabyRequirement, CandidateCheck
from src.pipeline import run_baby_optimizer

PROFILE = {"score_method_version": "test-v1", "weights": {"price": 1.0}}


def _req(rid, slot, qty=1, mandatory=True, timing="now", unit_code="each"):
    return BabyRequirement(id=rid, revision_id="rev", slot_key=slot, required_qty=qty,
                           unit_code=unit_code, mandatory=mandatory, timing=timing)


def _cand(cid, rid, slot, price, product_key=..., variant_key="v1"):
    return BabyCandidate(candidate_id=cid, requirement_id=rid, product_id="p", variant_id="v",
                         product_key=cid if product_key is ... else product_key, variant_key=variant_key,
                         name=cid, slot_key=slot, price=price)


def _check(cid, selection_allowed=True, eligibility="pass"):
    return CandidateCheck(candidate_id=cid, eligibility=eligibility, verification="verified",
                          coverage="full", selection_allowed=selection_allowed)


def test_run_baby_optimizer_selects_real_requirement_and_price_not_candidate_id_as_item_id():
    requirements = [_req("r-seat", "car_seat", qty=1)]
    candidates = [_cand("c1", "r-seat", "car_seat", 80)]
    checks = [_check("c1")]

    ranked, decision = run_baby_optimizer(requirements=requirements, candidates=candidates,
                                          checks=checks, budget_max=100, profile=PROFILE)

    assert decision.feasible is True
    assert len(decision.items) == 1
    item = decision.items[0]
    # the old adapter used the candidate id as the item id; the real boundary mints
    # its own stable item_id and keeps requirement_id/candidate_id separate
    assert item.item_id != "c1"
    assert item.requirement_id == "r-seat"
    assert item.candidate_id == "c1"
    assert item.unit_price == 80
    assert item.timing == "now"
    assert decision.totals["selected_price"] == 80
    assert ranked.by_requirement["r-seat"][0].candidate_id == "c1"


def test_run_baby_optimizer_excludes_missing_identifier_and_unallowed_candidates():
    requirements = [_req("r-bottle", "bottle", qty=1, mandatory=False)]
    candidates = [
        _cand("c-bad", "r-bottle", "bottle", 1, product_key=""),   # missing stable identity
        _cand("c-fail", "r-bottle", "bottle", 5),                  # recalled -> not selectable
    ]
    checks = [_check("c-fail", selection_allowed=False, eligibility="fail")]

    ranked, decision = run_baby_optimizer(requirements=requirements, candidates=candidates,
                                          checks=checks, budget_max=100, profile=PROFILE)

    assert any(e["candidate_id"] == "c-bad" and e["reason"] == "missing_product_key"
              for e in ranked.excluded)
    assert ranked.by_requirement["r-bottle"][0].selection_allowed is False
    # optional requirement with no selectable candidate simply has nothing purchased,
    # never fabricated
    assert not any(i.requirement_id == "r-bottle" and i.selected for i in decision.items)
    assert decision.feasible is True


def test_run_baby_optimizer_infeasible_reports_shortfall_not_silent_removal():
    requirements = [_req("r-a", "seat", qty=1), _req("r-b", "gate", qty=1)]
    candidates = [_cand("ca", "r-a", "seat", 60), _cand("cb", "r-b", "gate", 60)]
    checks = [_check("ca"), _check("cb")]

    ranked, decision = run_baby_optimizer(requirements=requirements, candidates=candidates,
                                          checks=checks, budget_max=100, profile=PROFILE)

    assert decision.feasible is False
    assert decision.totals["cheapest_feasible_subtotal"] == 120
    assert decision.totals["budget_shortfall"] == 20
    assert {m["requirement_id"] for m in decision.missing_requirements} == {"r-a", "r-b"}
