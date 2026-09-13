"""P4 real end-to-end integration probe (real PostgreSQL/pgvector, no mocks).

Drives the actual upstream boundary functions in sequence against a genuine seeded
database and a real conversation/plan/revision/run row set — not a synthetic
run id string, not a hand-built requirement/candidate dict:

  P1  src.services.session_service.normalize_baby_conditions
  P2  src.engine.stage2_requirement.build_baby_requirements / persist_baby_requirements
      src.engine.stage3_0_candidates.get_baby_candidates
  P3  src.engine.stage3c_verify.verify_baby_candidate (real RagService, real ingested
      synthetic stroller manual)
  P4  src.pipeline.run_baby_optimizer (rank_baby_candidates + optimize_baby — this task)

Usage:
  export DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/<disposable db>?sslmode=disable
  uv run python docs/agent-tasks/baby/reports/artifacts/p4-integration-probe.py \
      [--report path/to/output.json]
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
sys.path.insert(0, str(ROOT / "scripts"))

from src.engine.stage2_requirement import build_baby_requirements, load_baby_rules_snapshot, persist_baby_requirements
from src.engine.stage3_0_candidates import get_baby_candidates
from src.engine.stage3c_verify import verify_baby_candidate
from src.engine.stage3b_rank import load_baby_optimizer_profile
from src.pipeline import run_baby_optimizer
from src.rag.embedding import LocalHashEmbedder
from src.rag.ingestion import ingest_manual, read_manual
from src.rag.service import RagService
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.repo.rag_repo import RagRepo
from src.services.session_service import normalize_baby_conditions

CATALOG = ROOT / "data/baby/catalog_demo_v1.json"
MANUAL_BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"


def main(report_path: Path | None, budget_max: int = 200_000) -> dict:
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn, prepare_threshold=None)
    try:
        from seed_baby_catalog import load_input, seed_catalog

        manifest, records = load_input(CATALOG)
        seed_catalog(conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic")

        repo, embedder = RagRepo(conn), LocalHashEmbedder()
        doc = read_manual(MANUAL_BUNDLE)
        ingest_manual(MANUAL_BUNDLE, repo, embedder)
        repo.publish_manual(doc, embedder.embed([c.text for c in doc.chunks]), embedder, reviewed=True)
        service = RagService(repo, embedder)

        plan_repo, engine_repo = PlanRepo(conn), EngineRepo(conn)
        conversation = plan_repo._one(
            "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
            (f"p4-integration-probe-{uuid4()}",),
        )["id"]
        plan_id = plan_repo.create_plan(conversation, "P4 integration probe", None)
        domain = plan_repo.published_domain("baby")
        revision_id = plan_repo.new_revision(plan_id, domain["id"], "P4 integration probe")
        plan_repo.set_current_revision(plan_id, revision_id)
        revision = plan_repo.get_revision(revision_id)
        run_id = engine_repo.start_run(
            revision_id, revision["domain_id"], input_snapshot={}, input_hash="p4-integration-probe",
            draft_lock_version=revision["lock_version"], engine_versions={"pipeline": "baby-p4-probe"},
        )

        raw_values = {
            "mode": "born", "age_months": 8, "needs": ["외출", "기저귀·배변"],
            "owned_items": ["유모차"], "weight_kg": 8.5, "independent_sitting": True,
            "budget_max": budget_max,
        }
        conditions = normalize_baby_conditions(raw_values)
        conditions["revision_id"] = str(revision_id)

        domain_snapshot = {
            "reference_date": "2026-09-13",
            "baby_rules_snapshot": load_baby_rules_snapshot(),
        }
        pure_requirements = build_baby_requirements(conditions, domain_snapshot)
        requirements = persist_baby_requirements(conn, revision_id, pure_requirements)

        candidates_by_req = get_baby_candidates(conn, requirements, corpus="synthetic")
        all_candidates = [c for cs in candidates_by_req.values() for c in cs]

        run_context = {"recommendation_run_id": str(run_id)}
        checks = []
        for cand in all_candidates:
            check = verify_baby_candidate(service, cand.model_dump(), conditions, run_context)
            checks.append(check)

        profile = load_baby_optimizer_profile()
        ranked, decision = run_baby_optimizer(
            requirements=requirements, candidates=all_candidates, checks=checks,
            owned_items=[], budget_max=conditions["budget_max"], profile=profile,
        )

        result = {
            "revision_id": str(revision_id), "run_id": str(run_id),
            "requirements": [{"id": r.id, "slot_key": r.slot_key, "required_qty": r.required_qty,
                             "mandatory": r.mandatory, "timing": r.timing,
                             "fulfilled_by_item_id": r.fulfilled_by_item_id} for r in requirements],
            "candidates_per_requirement": {rid: len(cs) for rid, cs in candidates_by_req.items()},
            "checks": [{"candidate_id": c.candidate_id, "eligibility": c.eligibility,
                       "selection_allowed": c.selection_allowed, "coverage": c.coverage} for c in checks],
            "ranked_excluded": ranked.excluded,
            "decision": json.loads(decision.model_dump_json()),
        }
        conn.rollback()  # never leaves probe rows behind in a shared DB
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--budget", type=int, default=200_000)
    args = parser.parse_args()
    out = main(args.report, budget_max=args.budget)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
