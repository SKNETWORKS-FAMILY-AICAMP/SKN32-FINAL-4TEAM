"""P2 — build_baby_requirements / get_baby_candidates 테스트.

순수 규칙 로직은 DB 없이, 후보 조회는 RAG_TEST_DATABASE_URL 이 있을 때만 실행한다.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
import yaml

from src.dto import BabyRequirement
from src.engine.stage2_requirement import (
    RequirementRuleError, _load_rules, build_baby_requirements,
    load_baby_rules_snapshot, load_persisted_baby_requirements, persist_baby_requirements,
)
from src.engine.stage3_0_candidates import get_baby_candidates
from src.config import DATABASE_URL

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "baby_requirement_rules.yaml"
CATEGORY_YAML = ROOT / "config" / "categories" / "baby.yaml"
DSN = os.getenv("RAG_TEST_DATABASE_URL") or DATABASE_URL
needs_db = pytest.mark.skipif(
    not DSN, reason="set RAG_TEST_DATABASE_URL to a disposable migrated pgvector database"
)


def _all_needs() -> list[str]:
    doc = yaml.safe_load(CATEGORY_YAML.read_text(encoding="utf-8"))
    needs_set = next(q for q in doc["question_sets"] if q["id"] == "q_needs")
    return needs_set["options"]


def test_every_one_of_the_nine_need_areas_has_a_rule_or_explicit_data_gap():
    rules = _load_rules()["rules"]
    covered = {}
    for r in rules:
        for need in r["needs"]:
            covered.setdefault(need, []).append(r)
    all_needs = _all_needs()
    assert len(all_needs) == 9
    for need in all_needs:
        assert need in covered, f"{need}: no rule at all"
        has_real_rule = any(not r.get("data_gap") for r in covered[need])
        has_data_gap = any(r.get("data_gap") for r in covered[need])
        assert has_real_rule or has_data_gap, f"{need}: neither a real rule nor a data_gap"


def test_rule_set_rejects_duplicate_rule_keys(tmp_path, monkeypatch):
    doc = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    doc["rules"].append(dict(doc["rules"][0]))  # duplicate rule_key
    bad = tmp_path / "dup.yaml"
    bad.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    _load_rules.cache_clear()
    with pytest.raises(RequirementRuleError):
        _load_rules(bad)
    _load_rules.cache_clear()


def _domain_snapshot(reference_date="2026-09-13") -> dict:
    return {"reference_date": reference_date}


def test_ca02_8_month_fixture_owned_stroller_fulfilled_remaining_feeding_stable():
    conditions = {
        "revision_id": "11111111-1111-1111-1111-111111111111",
        "mode": "born", "age_stage": {"months": 8, "exact": True}, "needs": ["수유", "외출"],
        "owned_items": ["유모차"], "independent_sitting": True, "budget_max": 300000,
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    by_slot = {r.slot_key: r for r in reqs if r.owned}
    assert "stroller" in by_slot
    assert by_slot["stroller"].owned == [{"label": "유모차", "qty": 1.0, "unit_code": "each"}]
    assert by_slot["stroller"].fulfilled_qty == 1.0

    feeding_slots = {r.slot_key for r in reqs if r.slot_key in {"bottle", "formula"}}
    assert feeding_slots == {"bottle", "formula"}
    bottle = next(r for r in reqs if r.slot_key == "bottle")
    assert bottle.mandatory is True
    assert bottle.timing == "now"
    assert bottle.owned == []  # not owned, must remain a real (unfulfilled) requirement
    assert bottle.fulfilled_qty == 0.0

    # Rerun with an unrelated owned item — feeding slots must stay exactly the same shape.
    conditions2 = dict(conditions, owned_items=["카시트"])
    reqs2 = build_baby_requirements(conditions2, _domain_snapshot())
    bottle2 = next(r for r in reqs2 if r.slot_key == "bottle")
    assert (bottle2.required_qty, bottle2.mandatory, bottle2.timing) == (
        bottle.required_qty, bottle.mandatory, bottle.timing)


def test_prenatal_differs_from_born_without_fabricating_age():
    conditions = {
        "revision_id": "22222222-2222-2222-2222-222222222222",
        "mode": "prenatal", "due_date": "2026-10-01", "needs": ["수유", "외출"], "owned_items": [],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot("2026-09-13"))
    assert reqs, "prenatal must still produce requirements"
    for r in reqs:
        assert "age_months" not in r.constraints
        assert r.timing in {"now", "soon", "later"}
    # Due date 18 days out → "soon" by the documented demo heuristic (<=60 days, >0).
    assert {r.timing for r in reqs} == {"soon"}


def test_born_mode_missing_age_months_raises_instead_of_fabricating_it():
    conditions = {"revision_id": "x", "mode": "born", "needs": ["수유"], "owned_items": []}
    with pytest.raises(RequirementRuleError):
        build_baby_requirements(conditions, _domain_snapshot())


def test_missing_reference_date_raises_instead_of_using_wall_clock_now():
    conditions = {"revision_id": "x", "mode": "born", "age_stage": {"months": 8, "exact": True},
                  "needs": ["수유"], "owned_items": []}
    with pytest.raises(RequirementRuleError):
        build_baby_requirements(conditions, {})


def test_requirement_ordering_is_stable_by_timing_then_mandatory_then_slot_key():
    conditions = {
        "revision_id": "33333333-3333-3333-3333-333333333333",
        "mode": "born", "age_stage": {"months": 1, "exact": True},
        "needs": ["수유", "이유식·식사", "외출", "놀이", "안전·건강"],
        "owned_items": [], "independent_sitting": False,
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    timing_rank = {"now": 0, "soon": 1, "later": 2}
    keys = [(timing_rank[r.timing], 0 if r.mandatory else 1, r.slot_key) for r in reqs]
    assert keys == sorted(keys)
    # Same input twice must give the exact same order (determinism, not just a stable sort call).
    reqs2 = build_baby_requirements(conditions, _domain_snapshot())
    assert [r.id for r in reqs] == [r2.id for r2 in reqs2]


def test_independent_sitting_unknown_is_carried_through_not_assumed():
    conditions = {
        "revision_id": "44444444-4444-4444-4444-444444444444",
        "mode": "born", "age_stage": {"months": 8, "exact": True}, "needs": ["외출"], "owned_items": [],
        # independent_sitting intentionally omitted (unanswered)
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    stroller = next(r for r in reqs if r.slot_key == "stroller")
    assert stroller.constraints["requires_independent_sitting"] is True
    assert stroller.constraints["actual_independent_sitting"] is None


# ── DB-backed candidate lookup ───────────────────────────────────────────────

@pytest.fixture
def conn():
    connection = psycopg.connect(DSN, prepare_threshold=None)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _seed_demo_catalog(conn):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from seed_baby_catalog import load_input, seed_catalog

    manifest, records = load_input(ROOT / "data" / "baby" / "catalog_demo_v1.json")
    return seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")




@needs_db
def test_ca02_candidates_present_for_feeding_and_outing_slots(conn):
    _seed_demo_catalog(conn)
    conditions = {
        "revision_id": "55555555-5555-5555-5555-555555555555",
        "mode": "born", "age_stage": {"months": 8, "exact": True}, "needs": ["수유", "외출"],
        "owned_items": ["유모차"], "independent_sitting": True,
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    candidates = get_baby_candidates(conn, reqs, corpus="synthetic")
    bottle_req = next(r for r in reqs if r.slot_key == "bottle")
    stroller_req = next(r for r in reqs if r.slot_key == "stroller")
    assert len(candidates[bottle_req.id]) > 0
    assert len(candidates[stroller_req.id]) > 0
    for c in candidates[bottle_req.id]:
        assert c.price is not None and c.price >= 0
        assert c.corpus == "synthetic"


@needs_db
def test_ca05_data_gap_need_area_stays_visible_with_no_substitution(conn):
    _seed_demo_catalog(conn)
    conditions = {
        "revision_id": "66666666-6666-6666-6666-666666666666",
        "mode": "prenatal", "due_date": "2026-10-01", "needs": ["의류"], "owned_items": [],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    clothing_req = next(r for r in reqs if r.slot_key == "clothing")
    assert clothing_req.constraints["data_gap"] is True
    candidates = get_baby_candidates(conn, reqs, corpus="synthetic")
    assert candidates[clothing_req.id] == []


@needs_db
def test_candidate_query_never_crosses_corpus(conn):
    _seed_demo_catalog(conn)
    conditions = {
        "revision_id": "77777777-7777-7777-7777-777777777777",
        "mode": "born", "age_stage": {"months": 8, "exact": True}, "needs": ["수유"],
        "owned_items": [],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    real_candidates = get_baby_candidates(conn, reqs, corpus="real")
    for r in reqs:
        assert real_candidates[r.id] == [], "no synthetic candidate may leak into corpus=real"


# ── 2026-09-13 P012 review fixes (R3/R4/R5/R6) ──────────────────────────────

@needs_db
def test_r3_consumes_real_p1_normalized_conditions_age_stage_shape(conn):
    """build_baby_requirements must read the ACTUAL P1 output shape
    (age_stage.months), not a top-level age_months this task never produces —
    the 2026-09-13 review reproduced `feeding_bottle_v1: mode=born 인데
    age_months 없음` when normalize_baby_conditions()'s real output was passed in."""
    from src.services.session_service import (
        _current_values, choose_category, create_session, handle_answer, normalize_baby_conditions,
    )
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_age", [5], principal)
    handle_answer(conn, session["list_id"], "q_needs", ["수유"], principal)
    handle_answer(conn, session["list_id"], "q_owned", ["없음"], principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])
    values, _ = _current_values(PlanRepo(conn), revision["id"])
    normalized = normalize_baby_conditions(values)
    assert "age_months" not in normalized  # the real producer never emits this key
    assert "months" in normalized["age_stage"]

    conditions = {**normalized, "revision_id": str(revision["id"])}
    reqs = build_baby_requirements(conditions, _domain_snapshot())  # must not raise
    assert any(r.slot_key == "bottle" for r in reqs)


@needs_db
def test_r4_pack_unit_qty_survives_seed_to_candidate(conn):
    """CA03 seed-level check alone missed this: unit_qty (pieces per pack) has no
    catalog.product_variant column and must round-trip through candidate rows,
    not silently default to 1 (review reproduced diaper unit_qty 40 -> 1)."""
    _seed_demo_catalog(conn)
    conditions = {
        "revision_id": "88888888-8888-8888-8888-888888888888",
        "mode": "born", "age_stage": {"months": 8, "exact": True}, "needs": ["기저귀·배변"],
        "owned_items": [],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    diaper_req = next(r for r in reqs if r.slot_key == "diaper")
    candidates = get_baby_candidates(conn, reqs, corpus="synthetic")
    ca03 = next(c for c in candidates[diaper_req.id] if c.product_key == "SYN-DIAPER-CA03-001")
    assert ca03.pack_quantity == 2.0
    assert ca03.unit_qty == 40.0, "unit_qty must not silently collapse to 1"


@needs_db
def test_r5_persist_baby_requirements_writes_real_uuids_and_is_idempotent(conn):
    """The pure function's label-only owned entry must gain a real
    plan_condition-backed source_condition_id, and the requirement itself a real
    planning.requirement.id, through a separate repository operation (CONTRACTS
    IMPLEMENTATION 5) — v3: no planning.item table exists in develop, ownership is
    represented directly from the revision's own plan_condition row."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    _seed_demo_catalog(conn)
    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])
    owned_condition_id = PlanRepo(conn).active_condition_id(revision["id"], "owned_items")
    assert owned_condition_id is not None

    conditions = {
        "revision_id": str(revision["id"]), "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유"], "owned_items": ["젖병"],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    persisted = persist_baby_requirements(conn, revision["id"], reqs)
    bottle = next(r for r in persisted if r.slot_key == "bottle")

    import uuid as uuid_mod
    uuid_mod.UUID(bottle.id)  # real planning.requirement.id, not a synthetic marker
    assert bottle.owned == [{"label": "젖병", "qty": 1.0, "unit_code": "each",
                             "source_condition_id": str(owned_condition_id)}]
    assert bottle.fulfilled_qty == 1.0

    req_row = PlanRepo(conn)._one(
        "SELECT quantity, unit_code, required, match_spec FROM planning.requirement WHERE id=%s",
        (bottle.id,))
    assert float(req_row["quantity"]) == 2.0
    assert req_row["unit_code"] == "each"
    assert req_row["required"] is True
    assert req_row["match_spec"]["baby_requirement"]["fulfilled_qty"] == 1.0

    # Idempotent: re-persisting the same computed requirements reuses the same
    # planning.plan_node/requirement row (no duplicate row for the same slot_key) —
    # `reqs` covers both bottle and formula (need="수유"), so 2 rows total is correct.
    count_before = PlanRepo(conn)._one(
        "SELECT count(*) AS n FROM planning.requirement WHERE revision_id=%s", (revision["id"],))["n"]
    persisted_again = persist_baby_requirements(conn, revision["id"], reqs)
    bottle_again = next(r for r in persisted_again if r.slot_key == "bottle")
    assert bottle_again.id == bottle.id
    assert bottle_again.owned == bottle.owned
    count_after = PlanRepo(conn)._one(
        "SELECT count(*) AS n FROM planning.requirement WHERE revision_id=%s", (revision["id"],))["n"]
    assert count_after == count_before == len(reqs), (
        "re-persisting must not create a second requirement row for the same slot")


@needs_db
def test_d2_total_2_owned_1_needs_1_more_to_purchase(conn):
    """D2: 총2개/보유1개→필요 구매1개."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])

    conditions = {
        "revision_id": str(revision["id"]), "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유"], "owned_items": ["젖병"],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    persisted = persist_baby_requirements(conn, revision["id"], reqs)
    bottle = next(r for r in persisted if r.slot_key == "bottle")
    assert bottle.required_qty == 2.0
    assert bottle.fulfilled_qty == 1.0
    remaining_to_purchase = bottle.required_qty - bottle.fulfilled_qty
    assert remaining_to_purchase == 1.0


@needs_db
def test_d2_unowning_reverts_to_needing_2_to_purchase(conn):
    """D2: 보유 해제→구매2개."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])

    owned_conditions = {
        "revision_id": str(revision["id"]), "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유"], "owned_items": ["젖병"],
    }
    persist_baby_requirements(conn, revision["id"],
                              build_baby_requirements(owned_conditions, _domain_snapshot()))

    # User clears owned_items — re-answer with the "없음" (none) option.
    handle_answer(conn, session["list_id"], "q_owned", ["없음"], principal)
    unowned_conditions = {**owned_conditions, "owned_items": []}
    reqs2 = build_baby_requirements(unowned_conditions, _domain_snapshot())
    persisted2 = persist_baby_requirements(conn, revision["id"], reqs2)
    bottle2 = next(r for r in persisted2 if r.slot_key == "bottle")
    assert bottle2.owned == []
    assert bottle2.fulfilled_qty == 0.0
    assert bottle2.required_qty - bottle2.fulfilled_qty == 2.0

    # Reload must also reflect the cleared ownership, not a stale cached row.
    reloaded = next(r for r in load_persisted_baby_requirements(conn, revision["id"])
                    if r.slot_key == "bottle")
    assert reloaded.owned == []
    assert reloaded.fulfilled_qty == 0.0


@needs_db
def test_d2_rejects_negative_and_non_finite_required_qty(conn):
    from src.services.session_service import create_session, choose_category
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])

    bad = BabyRequirement(id="x", revision_id=str(revision["id"]), slot_key="bottle",
                          required_qty=-1.0)
    with pytest.raises(ValueError):
        persist_baby_requirements(conn, revision["id"], [bad])

    bad_inf = BabyRequirement(id="x", revision_id=str(revision["id"]), slot_key="bottle",
                              required_qty=float("nan"))
    with pytest.raises(ValueError):
        persist_baby_requirements(conn, revision["id"], [bad_inf])


@needs_db
def test_d2_rejects_owned_unit_mismatch(conn):
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])

    mismatched = BabyRequirement(
        id="x", revision_id=str(revision["id"]), slot_key="bottle", unit_code="each",
        required_qty=2.0, owned=[{"label": "젖병", "qty": 1.0, "unit_code": "pack"}],
    )
    with pytest.raises(ValueError):
        persist_baby_requirements(conn, revision["id"], [mismatched])


@needs_db
def test_d2_rejects_owned_entry_from_a_different_revision(conn):
    """D2: 교차 revision 조건 거부."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session_a = create_session(conn, Principal(user_id=None, browser_token=None))
    principal_a = Principal(user_id=None, browser_token=session_a["browser_token"])
    choose_category(conn, session_a["list_id"], "baby", "born", principal_a)
    handle_answer(conn, session_a["list_id"], "q_owned", ["젖병"], principal_a)
    revision_a = PlanRepo(conn).get_current_revision(session_a["list_id"])
    other_condition_id = PlanRepo(conn).active_condition_id(revision_a["id"], "owned_items")

    session_b = create_session(conn, Principal(user_id=None, browser_token=None))
    principal_b = Principal(user_id=None, browser_token=session_b["browser_token"])
    choose_category(conn, session_b["list_id"], "baby", "born", principal_b)
    handle_answer(conn, session_b["list_id"], "q_owned", ["젖병"], principal_b)
    revision_b = PlanRepo(conn).get_current_revision(session_b["list_id"])

    forged = BabyRequirement(
        id="x", revision_id=str(revision_b["id"]), slot_key="bottle", unit_code="each",
        required_qty=2.0,
        owned=[{"label": "젖병", "qty": 1.0, "unit_code": "each",
               "source_condition_id": str(other_condition_id)}],
    )
    with pytest.raises(ValueError):
        persist_baby_requirements(conn, revision_b["id"], [forged])


@needs_db
def test_r1_owned_qty_capped_at_actual_condition_value_not_caller_claim(conn):
    """P2 review R1: source_condition_id matching alone must not be enough — the
    caller-claimed qty is rejected once it exceeds what the revision's real
    owned_items condition value actually reports for that label."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)  # reports exactly 1
    revision = PlanRepo(conn).get_current_revision(session["list_id"])
    owned_condition_id = PlanRepo(conn).active_condition_id(revision["id"], "owned_items")

    inflated = BabyRequirement(
        id="x", revision_id=str(revision["id"]), slot_key="bottle", unit_code="each",
        required_qty=2.0, owned=[{"label": "젖병", "qty": 2.0, "unit_code": "each",
                                  "source_condition_id": str(owned_condition_id)}],
    )
    with pytest.raises(ValueError, match="owned_qty_exceeds_reported"):
        persist_baby_requirements(conn, revision["id"], [inflated])


@needs_db
def test_r1_owned_qty_not_double_allocated_across_two_requirements(conn):
    """The same single reported item cannot fulfil two different requirement slots
    at once (P2 review R1) — even though each individual entry's qty is <= 1."""
    from src.services.session_service import create_session, choose_category, handle_answer
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    handle_answer(conn, session["list_id"], "q_owned", ["젖병"], principal)  # reports exactly 1
    revision = PlanRepo(conn).get_current_revision(session["list_id"])
    owned_condition_id = PlanRepo(conn).active_condition_id(revision["id"], "owned_items")

    entry = {"label": "젖병", "qty": 1.0, "unit_code": "each",
             "source_condition_id": str(owned_condition_id)}
    slot_a = BabyRequirement(id="a", revision_id=str(revision["id"]), slot_key="bottle",
                             unit_code="each", required_qty=2.0, owned=[entry])
    slot_b = BabyRequirement(id="b", revision_id=str(revision["id"]), slot_key="sterilizer",
                             unit_code="each", required_qty=1.0, owned=[entry])
    with pytest.raises(ValueError, match="owned_qty_exceeds_reported"):
        persist_baby_requirements(conn, revision["id"], [slot_a, slot_b])


@needs_db
def test_r3_stale_slot_excluded_then_revived_with_same_uuid(conn):
    """P2 review R3: a slot that disappears from a later calculation (needs changed)
    must not keep showing up in load_persisted_baby_requirements, and reappearing
    later must reuse the SAME requirement UUID rather than minting a new one."""
    from src.services.session_service import create_session, choose_category
    from src.repo.plan_repo import PlanRepo
    from src.auth.deps import Principal

    session = create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=session["browser_token"])
    choose_category(conn, session["list_id"], "baby", "born", principal)
    revision = PlanRepo(conn).get_current_revision(session["list_id"])

    both = {
        "revision_id": str(revision["id"]), "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유", "외출"], "owned_items": [],
    }
    persisted_both = persist_baby_requirements(
        conn, revision["id"], build_baby_requirements(both, _domain_snapshot()))
    stroller_id = next(r.id for r in persisted_both if r.slot_key == "stroller")

    feeding_only = {**both, "needs": ["수유"]}
    persist_baby_requirements(conn, revision["id"], build_baby_requirements(feeding_only, _domain_snapshot()))
    reloaded = load_persisted_baby_requirements(conn, revision["id"])
    assert not any(r.slot_key == "stroller" for r in reloaded), "사라진 슬롯은 재조회에 남으면 안 된다"
    assert PlanRepo(conn)._one(
        "SELECT status FROM planning.requirement WHERE id=%s", (stroller_id,))["status"] == "excluded"

    persist_baby_requirements(conn, revision["id"], build_baby_requirements(both, _domain_snapshot()))
    revived = next(r for r in load_persisted_baby_requirements(conn, revision["id"]) if r.slot_key == "stroller")
    assert revived.id == stroller_id, "재요청 시 같은 UUID로 되살아나야 한다"


def test_r6_pinned_rule_snapshot_is_immune_to_a_later_live_file_change(monkeypatch):
    """A revision computed against a pinned rules snapshot must keep giving the
    SAME result even if config/baby_requirement_rules.yaml changes afterwards —
    the review reproduced that two consecutive calls only looked identical because
    both read the same still-unchanged file, never proving the snapshot was pinned."""
    snapshot = load_baby_rules_snapshot()
    conditions = {
        "revision_id": "99999999-9999-9999-9999-999999999999", "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유"], "owned_items": [],
    }
    domain_snapshot = {"reference_date": "2026-09-13", "baby_rules_snapshot": snapshot}
    before = build_baby_requirements(conditions, domain_snapshot)

    import src.engine.stage2_requirement as stage2

    def poisoned(*_a, **_kw):
        raise AssertionError("pinned snapshot path must never call the live loader")

    monkeypatch.setattr(stage2, "_load_rules", poisoned)
    after = build_baby_requirements(conditions, domain_snapshot)
    assert [r.id for r in before] == [r.id for r in after]
    for r in after:
        assert r.constraints["rule_set_pinned"] is True
        assert r.constraints["rule_set_hash"] == snapshot["rule_set_hash"]


def test_unpinned_snapshot_is_labeled_not_pinned():
    conditions = {
        "revision_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "mode": "born",
        "age_stage": {"months": 8, "exact": True}, "needs": ["수유"], "owned_items": [],
    }
    reqs = build_baby_requirements(conditions, _domain_snapshot())
    assert all(r.constraints["rule_set_pinned"] is False for r in reqs)
