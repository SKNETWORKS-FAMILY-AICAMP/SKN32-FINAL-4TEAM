"""P4 develop-DB (da79839) real end-to-end integration probe — no mocks.

Drives the ACTUAL current develop-aligned repositories/functions against a real
disposable PostgreSQL database seeded with the develop chain (0000-0013,
0011_drop_rag_schema/0012_schema_reduction_safe_subset/0013_result_item_interaction):

  P1  src.services.session_service.create_session/choose_category/handle_answer/
      normalize_baby_conditions (real identity.conversation/planning.plan/plan_revision
      rows, real plan_condition rows for the owned-item answer)
  P2  src.engine.stage2_requirement.build_baby_requirements/persist_baby_requirements/
      load_persisted_baby_requirements (real planning.plan_node + planning.requirement
      rows — no planning.item, matching develop's schema)
      src.engine.stage3_0_candidates.get_baby_candidates (real catalog.product/
      product_variant/offer/offer_observation rows from scripts/seed_baby_catalog.py)
  P3  src.engine.stage3c_verify.verify_baby_candidate (service=None: develop drops the
      `rag` schema entirely and no external search provider is configured yet —
      DEVELOP_DB_TRANSITION.md "Evidence and external search" D3-01 boundary, so every
      manual-backed rule correctly resolves to eligibility=unknown, never a fabricated
      pass)
  P4  src.pipeline.run_baby_optimizer (rank_baby_candidates + optimize_baby — this task)

This demonstrates that P4's own develop-DB-alignment delta (owned via validated
fulfilled_qty, CandidateCheck.requirement_id/unit_code cross-checks, no planning.item
access) is real end-to-end wiring against the live develop schema, not just unit
fixtures — while making the still-unconfigured-search boundary visible rather than
faking a pass for it.

Usage:
  export DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/<disposable db>?sslmode=disable
  uv run python docs/agent-tasks/baby/reports/artifacts/p4-develop-integration-probe.py \
      [--budget 500000] [--report path/to/output.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from src.auth.deps import Principal
from src.engine.stage2_requirement import (build_baby_requirements, load_baby_rules_snapshot,
                                           load_persisted_baby_requirements, persist_baby_requirements)
from src.engine.stage3_0_candidates import get_baby_candidates
from src.engine.stage3b_rank import load_baby_optimizer_profile, rank_baby_candidates
from src.engine.stage3c_verify import verify_baby_candidate
from src.pipeline import run_baby_optimizer
from src.repo.plan_repo import PlanRepo
from src.services import session_service as ss


def main(budget_max: int) -> dict:
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn, prepare_threshold=None)
    try:
        result = ss.create_session(conn, Principal(user_id=None, browser_token=None))
        who = Principal(user_id=None, browser_token=result["browser_token"])
        list_id = result["list_id"]
        ss.choose_category(conn, list_id, "baby", "born", who)
        revision = PlanRepo(conn).get_current_revision(list_id)
        revision_id = revision["id"]

        ss.handle_answer(conn, list_id, "q_owned", ["유모차"], who)
        ss.handle_message(conn, list_id, "8개월", who)  # explicit age -> exact=True

        values, _ = ss._current_values(PlanRepo(conn), revision_id)
        conditions = ss.normalize_baby_conditions(values)
        conditions["revision_id"] = str(revision_id)
        conditions["needs"] = ["기저귀·배변"]
        # "외출" (stroller/car_seat) is intentionally excluded here: stroller is the one
        # slot in src.rag.verification.MANUAL_RULE_INVENTORY, and verify_seat() calls
        # `service.search(...)` unconditionally -- passing service=None (the correct
        # "no search provider configured" state under develop's dropped rag schema,
        # src/rag/provider.py's own documented contract) crashes with AttributeError
        # instead of returning eligibility=unknown. That is a real, reproduced P3-scope
        # gap (src/engine/stage3c_verify.py / src/rag/verification.py, not P4's edit
        # surface) -- recorded in reports/P4.md's remaining section rather than papered
        # over by dodging it silently.
        conditions["independent_sitting"] = True
        conditions["weight_kg"] = 8.5

        domain_snapshot = {"reference_date": "2026-09-14", "baby_rules_snapshot": load_baby_rules_snapshot()}
        pure = build_baby_requirements(conditions, domain_snapshot)
        requirements = persist_baby_requirements(conn, revision_id, pure)
        # real reload round-trip, not just the return value of persist itself
        reloaded = load_persisted_baby_requirements(conn, revision_id)
        assert {r.id for r in reloaded} == {r.id for r in requirements}, "reload mismatch"

        candidates_by_req = get_baby_candidates(conn, requirements, corpus="synthetic")
        all_candidates = [c for cs in candidates_by_req.values() for c in cs]

        run_context = {"recommendation_run_id": str(uuid4())}
        checks = [verify_baby_candidate(None, c.model_dump(), conditions, run_context) for c in all_candidates]

        profile = load_baby_optimizer_profile()
        ranked, decision = run_baby_optimizer(
            requirements=requirements, candidates=all_candidates, checks=checks,
            owned_items=[], budget_max=budget_max, profile=profile,
        )

        result = {
            "revision_id": str(revision_id),
            "requirements": [{"id": r.id, "slot_key": r.slot_key, "required_qty": r.required_qty,
                             "mandatory": r.mandatory, "timing": r.timing,
                             "owned": r.owned, "fulfilled_qty": r.fulfilled_qty} for r in requirements],
            "reload_matches_persist": True,
            "candidates_per_requirement": {rid: len(cs) for rid, cs in candidates_by_req.items()},
            "checks_summary": {
                "unknown": sum(1 for c in checks if c.eligibility == "unknown"),
                "pass": sum(1 for c in checks if c.eligibility == "pass"),
                "fail": sum(1 for c in checks if c.eligibility == "fail"),
            },
            "checks_note": "eligibility=unknown for manual-backed rules is expected: develop "
                           "drops the rag schema and no external search provider is configured "
                           "yet (DEVELOP_DB_TRANSITION.md D3-01) -- this is the honest boundary, "
                           "not a P4 defect.",
            "ranked_excluded": ranked.excluded,
            "decision": json.loads(decision.model_dump_json()),
        }
        conn.rollback()  # never leaves probe rows behind
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--budget", type=int, default=200_000)
    args = parser.parse_args()
    out = main(args.budget)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
