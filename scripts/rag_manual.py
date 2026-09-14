#!/usr/bin/env python3
"""Admin CLI: publish a synthetic manual to the search provider, search it, evaluate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.contracts import SearchRequest
from src.rag.ingestion import ingest_manual, read_manual
from src.rag.provider import get_search_provider
from src.rag.service import RagService
from src.repo.material_repo import MaterialRepo


def create_test_run(conn) -> str:
    """Explicit synthetic evaluation context, never an implicit production identity."""
    import hashlib
    import json as _json

    from psycopg.rows import tuple_row
    from psycopg.types.json import Jsonb

    # domain.status='disabled': a runtime session can never select this domain as its
    # category. develop schema: config.domain has no version/definition columns of its
    # own — those live on config.domain_version, and plan_revision/recommendation_run
    # carry domain_version_id (no domain_snapshot column to fill).
    definition = {"category": "rag-evaluation-baby", "purpose": "rag_evaluation",
                  "corpus": "synthetic", "slot_schema": {}}
    content_hash = hashlib.sha256(
        _json.dumps(definition, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    cur = conn.cursor(row_factory=tuple_row)
    domain = cur.execute(
        """INSERT INTO config.domain(code,name,status) VALUES ('rag-evaluation-baby','가상 설명서 RAG 평가','disabled')
        ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, status='disabled' RETURNING id""",
    ).fetchone()[0]
    domain_version = cur.execute(
        """INSERT INTO config.domain_version(domain_id,version_no,definition,attribute_schema,content_hash)
        SELECT %s, COALESCE(MAX(version_no),0)+1, %s, '{}', %s FROM config.domain_version WHERE domain_id=%s
        RETURNING id""",
        (domain, Jsonb(definition), content_hash, domain),
    ).fetchone()[0]
    conversation = cur.execute(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        ("synthetic-evaluation-" + str(uuid4()),),
    ).fetchone()[0]
    plan = cur.execute(
        "INSERT INTO planning.plan(conversation_id,name) VALUES (%s,'RAG synthetic evaluation') RETURNING id",
        (conversation,),
    ).fetchone()[0]
    revision = cur.execute(
        """INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot)
        VALUES (%s,1,%s,'RAG synthetic evaluation') RETURNING id""",
        (plan, domain_version),
    ).fetchone()[0]
    cur.execute(
        "UPDATE planning.plan SET current_revision_id=%s WHERE id=%s", (revision, plan)
    )
    run = cur.execute(
        """INSERT INTO engine.recommendation_run
        (revision_id,domain_version_id,input_snapshot,input_hash,draft_lock_version,engine_versions,status)
        VALUES (%s,%s,%s,%s,0,%s,'running') RETURNING id""",
        (
            revision, domain_version,
            Jsonb({"is_synthetic": True, "purpose": "rag_evaluation"}),
            "0" * 64,
            Jsonb({"search": "manual-markdown-v2-external-provider"}),
        ),
    ).fetchone()[0]
    conn.commit()
    return str(run)


def evaluate(service, request, cases_path, document):
    # This file is read ONLY by the evaluator, after ingestion is complete.
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        current = replace(request, query=case["query"], **case.get("filters", {}))
        answer = service.answer(current)
        expected = case.get("expected_text", [])
        hits = answer["hits"]
        joined = "\n".join(h["text"] for h in hits)
        citation_valid = all(
            document.text[h["locator"]["char_start"] : h["locator"]["char_end"]] == h["text"]
            for h in hits
        )
        passed = (
            answer["status"] == case["status"]
            and all(t in joined for t in expected)
            and citation_valid
        )
        results.append({
            "id": case["id"], "query": case["query"], "passed": passed,
            "expected_status": case["status"], "actual_status": answer["status"],
            "citation_valid": citation_valid, "answer": answer["answer"], "evidence": hits,
        })
    return {
        "is_synthetic": True,
        "search_provider": service.provider.name if service.provider else None,
        "manual_sha256": document.sha256,
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "results": results,
        "limitations": [
            "One partial synthetic stroller manual; not real product safety validation.",
            "local-file provider does lexical token-overlap scoring, not semantic search.",
            "No third-party search backend is configured/available in this environment (D3-02 blocked).",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "query", "evaluate"])
    parser.add_argument("--bundle", default="generated/synthetic_manuals/stroller_example")
    parser.add_argument("--provider", choices=["local-file"], default="local-file",
                        help="external search backend (see src/rag/provider.py); "
                             "no third-party backend is configured in this environment")
    parser.add_argument("--query")
    parser.add_argument("--run-id")
    parser.add_argument("--new-test-run", action="store_true")
    parser.add_argument("--reviewed", action="store_true",
                        help="Administrator attests review; never inferred from generator validation")
    parser.add_argument("--cases", default="tests/fixtures/rag/stroller_cases.json")
    parser.add_argument("--report", default="generated/rag/stroller_evaluation.json")
    args = parser.parse_args()
    import psycopg
    from src.config import DATABASE_URL

    dsn = os.getenv("RAG_TEST_DATABASE_URL") or DATABASE_URL
    document = read_manual(args.bundle)
    os.environ.setdefault("BABY_SEARCH_PROVIDER", args.provider)
    provider = get_search_provider()
    if provider is None:
        parser.error("BABY_SEARCH_PROVIDER must be set (e.g. local-file); no backend configured")
    with psycopg.connect(dsn, connect_timeout=5, prepare_threshold=None) as conn:
        material_repo = MaterialRepo(conn)
        if args.command == "ingest":
            output = ingest_manual(args.bundle, material_repo, provider, reviewed=args.reviewed)
        else:
            run_id = args.run_id
            if args.new_test_run:
                if run_id:
                    parser.error("choose --run-id or --new-test-run")
                run_id = create_test_run(conn)
            if not run_id:
                parser.error("--run-id or --new-test-run is required")
            request = SearchRequest(
                domain="baby", query=args.query or "사용 조건", product_key=document.product_key,
                variant_key=document.variant_key, corpus="synthetic", market=document.market,
                recommendation_run_id=run_id,
            )
            service = RagService(material_repo, provider)
            if args.command == "query":
                if not args.query:
                    parser.error("--query is required")
                output = service.answer(request)
            else:
                output = evaluate(service, request, args.cases, document)
            if args.new_test_run:
                conn.execute(
                    "UPDATE engine.recommendation_run SET status='completed',completed_at=now() WHERE id=%s",
                    (run_id,),
                )
    if args.command == "evaluate":
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"cases": output["cases"], "passed": output["passed"], "report": str(report)},
                         ensure_ascii=False))
        return 0 if output["passed"] == output["cases"] else 1
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 1 if output.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
