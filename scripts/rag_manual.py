#!/usr/bin/env python3
"""Admin CLI: ingest a synthetic manual, search it, and evaluate held-out queries."""

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
from src.rag.embedding import BedrockEmbedder, LocalHashEmbedder
from src.rag.ingestion import ingest_manual, read_manual
from src.rag.service import RagService
from src.repo.rag_repo import RagRepo


def create_test_run(conn) -> str:
    """Explicit synthetic evaluation context, never an implicit production identity."""
    from psycopg.types.json import Jsonb

    domain = conn.execute("""INSERT INTO config.domain(code,name,status)
        VALUES ('rag-evaluation-baby','가상 설명서 RAG 평가','active')
        ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name RETURNING id""").fetchone()[
        0
    ]
    version = conn.execute(
        """INSERT INTO config.domain_version
        (domain_id,version_no,definition,attribute_schema,content_hash)
        VALUES (%s,1,'{}','{}',%s) ON CONFLICT (domain_id,version_no)
        DO UPDATE SET content_hash=EXCLUDED.content_hash RETURNING id""",
        (domain, "0" * 64),
    ).fetchone()[0]
    conversation = conn.execute(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        ("synthetic-evaluation-" + str(uuid4()),),
    ).fetchone()[0]
    plan = conn.execute(
        "INSERT INTO planning.plan(conversation_id,name) VALUES (%s,'RAG synthetic evaluation') RETURNING id",
        (conversation,),
    ).fetchone()[0]
    revision = conn.execute(
        """INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot)
        VALUES (%s,1,%s,'RAG synthetic evaluation') RETURNING id""",
        (plan, version),
    ).fetchone()[0]
    conn.execute(
        "UPDATE planning.plan SET current_revision_id=%s WHERE id=%s", (revision, plan)
    )
    run = conn.execute(
        """INSERT INTO engine.recommendation_run
        (revision_id,domain_version_id,input_snapshot,input_hash,draft_lock_version,engine_versions,status)
        VALUES (%s,%s,%s,%s,0,%s,'running') RETURNING id""",
        (
            revision,
            version,
            Jsonb({"is_synthetic": True, "purpose": "rag_evaluation"}),
            "0" * 64,
            Jsonb({"rag": "manual-markdown-v1"}),
        ),
    ).fetchone()[0]
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
            document.text[h["locator"]["char_start"] : h["locator"]["char_end"]]
            == h["text"]
            for h in hits
        )
        passed = (
            answer["status"] == case["status"]
            and all(t in joined for t in expected)
            and citation_valid
        )
        results.append(
            {
                "id": case["id"],
                "query": case["query"],
                "passed": passed,
                "expected_status": case["status"],
                "actual_status": answer["status"],
                "citation_valid": citation_valid,
                "answer": answer["answer"],
                "evidence": hits,
            }
        )
    return {
        "is_synthetic": True,
        "embedding_provider": service.embedder.provider,
        "profile_key": service.embedder.profile_key,
        "manual_sha256": document.sha256,
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "results": results,
        "limitations": [
            "One partial synthetic stroller manual; not real product safety validation.",
            "Local-test embeddings are lexical hashing, not Titan semantic quality.",
            "Evaluation queries and answer ledgers are not indexed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "query", "evaluate"])
    parser.add_argument(
        "--bundle", default="generated/synthetic_manuals/stroller_example"
    )
    parser.add_argument(
        "--provider", choices=["bedrock", "local-test"], default="bedrock"
    )
    parser.add_argument("--query")
    parser.add_argument("--run-id")
    parser.add_argument("--new-test-run", action="store_true")
    parser.add_argument(
        "--reviewed",
        action="store_true",
        help="Administrator attests review; never inferred from generator validation",
    )
    parser.add_argument("--cases", default="tests/fixtures/rag/stroller_cases.json")
    parser.add_argument("--report", default="generated/rag/stroller_evaluation.json")
    args = parser.parse_args()
    import psycopg
    from src.config import DATABASE_URL

    dsn = os.getenv("RAG_TEST_DATABASE_URL") or DATABASE_URL
    document = read_manual(args.bundle)
    embedder = (
        LocalHashEmbedder() if args.provider == "local-test" else BedrockEmbedder()
    )
    with psycopg.connect(dsn, connect_timeout=5, prepare_threshold=None) as conn:
        repo = RagRepo(conn)
        if args.command == "ingest":
            output = ingest_manual(args.bundle, repo, embedder, reviewed=args.reviewed)
        else:
            run_id = args.run_id
            if args.new_test_run:
                if run_id:
                    parser.error("choose --run-id or --new-test-run")
                run_id = create_test_run(conn)
            if not run_id:
                parser.error("--run-id or --new-test-run is required")
            request = SearchRequest(
                domain="baby",
                query=args.query or "사용 조건",
                product_key=document.product_key,
                variant_key=document.variant_key,
                corpus="synthetic",
                market=document.market,
                recommendation_run_id=run_id,
            )
            service = RagService(repo, embedder)
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
        report.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "cases": output["cases"],
                    "passed": output["passed"],
                    "report": str(report),
                },
                ensure_ascii=False,
            )
        )
        return 0 if output["passed"] == output["cases"] else 1
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 1 if output.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
