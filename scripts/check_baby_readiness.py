#!/usr/bin/env python3
"""Read-only operational readiness checks for the develop ``da79839`` baby DB.

This tool deliberately does not run migrations, seed data, recommendations, or a
search query.  It reports the state it observed as JSON and never includes the
connection string.  A configured external search provider is reported separately:
its absence is an honest ``blocked`` search gate, not a reason to revive the
removed PostgreSQL ``rag`` schema.

    DATABASE_URL=postgresql://... uv run python scripts/check_baby_readiness.py \
      --corpus synthetic --provider auto --output generated/operations/readiness.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MIGRATIONS = ROOT / "db" / "migrations"
BABY_RULES = ROOT / "config" / "baby_requirement_rules.yaml"
BABY_CONFIG = ROOT / "config" / "categories" / "baby.yaml"
EXPECTED_MIGRATIONS = tuple(path.stem for path in sorted(MIGRATIONS.glob("*.sql")))
REQUIRED_TABLES = (
    "config.domain_version", "planning.plan_node", "planning.purchase_line",
    "assets.material_revision", "assets.material_applicability", "evidence.source",
    "community.review_revision", "notification.price_watch",
)
FORBIDDEN = (("schema", "rag"), ("schema", "dataset"), ("table", "planning.item"))
VALID_UNITS = {"each", "pack", "g", "mL", "kg"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "stale"}


@dataclass(frozen=True)
class Check:
    id: str
    status: str  # pass | warn | blocked | fail
    reason: str
    observed: dict[str, Any]


def _check(identifier: str, outcome: str, reason: str, **observed: Any) -> Check:
    return Check(identifier, outcome, reason, observed)


def _hash_definition(definition: Any) -> str:
    # Match db/seed.py's deterministic JSON serialization exactly.
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _expected_slots() -> dict[str, list[str]]:
    rules = yaml.safe_load(BABY_RULES.read_text(encoding="utf-8"))
    by_need: dict[str, list[str]] = {}
    for rule in rules["rules"]:
        # Explicit data gaps are valid coverage results; never invent a category.
        if rule.get("data_gap") or rule.get("category_code") is None:
            continue
        for need in rule["needs"]:
            by_need.setdefault(need, []).append(rule["category_code"])
    return {need: sorted(set(slots)) for need, slots in by_need.items()}


def _table_exists(conn: psycopg.Connection, qualified: str) -> bool:
    schema, table = qualified.split(".")
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s)", (schema, table)
    ).fetchone()[0]


def _provider_check(requested: str, corpus: str) -> Check:
    """Inspect configuration only.  Do not instantiate a provider: constructors may mkdir."""
    configured = os.getenv("BABY_SEARCH_PROVIDER")
    if requested not in {"auto", "unconfigured"} and configured != requested:
        return _check("search_provider", "fail", "provider_argument_mismatch",
                      requested=requested, configured=configured or None, corpus=corpus)
    if requested == "unconfigured" or not configured:
        return _check("search_provider", "blocked", "search_provider_unconfigured",
                      configured=None, corpus=corpus)
    if configured != "local-file":
        return _check("search_provider", "blocked", "unsupported_provider_configuration",
                      configured=configured, corpus=corpus)
    root = Path(os.getenv("BABY_SEARCH_STORAGE_ROOT", ".baby-search-index"))
    # Merely enumerate an existing root.  Never create the directory from a health check.
    documents = len(list(root.glob("*.json"))) if root.is_dir() else 0
    return _check("search_provider", "pass", "configured_external_file_provider",
                  configured=configured, corpus=corpus, index_present=root.is_dir(), documents=documents)


def collect_readiness(*, dsn: str | None, corpus: str, provider: str) -> dict[str, Any]:
    checks: list[Check] = []
    provider_result = _provider_check(provider, corpus)
    checks.append(provider_result)
    if not dsn:
        checks.append(_check("database", "fail", "database_url_not_configured"))
        return _report(checks, provider_result, corpus)

    try:
        conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True)
    except psycopg.Error as exc:
        checks.append(_check("database", "fail", "database_connection_failed", error_type=type(exc).__name__))
        return _report(checks, provider_result, corpus)

    try:
        checks.append(_check("database", "pass", "database_connection_ok"))
        applied = {r[0]: r[1] for r in conn.execute(
            "SELECT version, checksum FROM _migrations.schema_migrations"
        ).fetchall()}
        missing = [name for name in EXPECTED_MIGRATIONS if name not in applied]
        unexpected = sorted(set(applied) - set(EXPECTED_MIGRATIONS))
        checks.append(_check(
            "migration_chain", "pass" if not missing and not unexpected else "fail",
            "develop_migration_chain_applied" if not missing and not unexpected else "migration_chain_mismatch",
            applied=sorted(applied), missing=missing, unexpected=unexpected,
        ))

        missing_tables = [name for name in REQUIRED_TABLES if not _table_exists(conn, name)]
        present_forbidden: list[str] = []
        for kind, name in FORBIDDEN:
            if kind == "schema":
                exists = conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name=%s)", (name,)
                ).fetchone()[0]
            else:
                exists = _table_exists(conn, name)
            if exists:
                present_forbidden.append(name)
        checks.append(_check(
            "target_schema", "pass" if not missing_tables and not present_forbidden else "fail",
            "develop_schema_matches_v3" if not missing_tables and not present_forbidden else "target_schema_mismatch",
            missing_tables=missing_tables, forbidden_present=present_forbidden,
        ))

        row = conn.execute(
            """SELECT dv.id, dv.version_no, dv.definition, dv.content_hash, d.status
               FROM config.domain d JOIN config.domain_version dv ON dv.domain_id=d.id
               WHERE d.code='baby' ORDER BY dv.version_no DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            checks.append(_check("baby_domain", "fail", "baby_domain_version_missing"))
        else:
            actual_hash = _hash_definition(row[2])
            checks.append(_check(
                "baby_domain", "pass" if actual_hash == row[3] else "fail",
                "baby_domain_hash_matches" if actual_hash == row[3] else "baby_domain_hash_mismatch",
                domain_version_id=str(row[0]), version_no=row[1], status=row[4], content_hash=row[3],
            ))

        slots = _expected_slots()
        coverage: dict[str, dict[str, int]] = {}
        for need, required_slots in slots.items():
            coverage[need] = {}
            for slot in required_slots:
                value = conn.execute(
                    """SELECT count(*) FROM catalog.product p
                       JOIN catalog.product_variant v ON v.product_id=p.id
                       JOIN catalog.offer o ON o.variant_id=v.id AND o.status='active'
                       JOIN LATERAL (
                           SELECT price, stock_status, quality_status FROM catalog.offer_observation
                           WHERE offer_id=o.id ORDER BY observed_at DESC LIMIT 1
                       ) obs ON true
                       WHERE p.product_type=%s AND p.attributes->>'corpus'=%s
                         AND obs.price IS NOT NULL AND obs.price >= 0
                         AND obs.stock_status <> 'sold_out' AND obs.quality_status='valid'""",
                    (slot, corpus),
                ).fetchone()[0]
                coverage[need][slot] = value
        missing_coverage = {need: [slot for slot, count in found.items() if count == 0]
                            for need, found in coverage.items() if any(count == 0 for count in found.values())}
        checks.append(_check(
            "candidate_coverage", "pass" if not missing_coverage else "fail",
            "all_need_slots_have_candidates" if not missing_coverage else "missing_candidate_coverage",
            coverage=coverage, missing=missing_coverage,
        ))

        invalid_units = conn.execute(
            """SELECT count(*) FROM catalog.product p JOIN catalog.product_variant v ON v.product_id=p.id
               WHERE p.attributes->>'corpus'=%s
                 AND (v.unit_code <> ALL(%s) OR v.pack_quantity <= 0
                      OR COALESCE((v.attributes->>'unit_qty')::numeric, 0) <= 0)""",
            (corpus, list(VALID_UNITS)),
        ).fetchone()[0]
        checks.append(_check(
            "pricing_units", "pass" if invalid_units == 0 else "fail",
            "catalog_price_and_unit_shape_valid" if invalid_units == 0 else "invalid_catalog_unit_shape",
            invalid_variant_count=invalid_units,
        ))

        manual_rows = conn.execute(
            """SELECT count(*) FROM assets.material_revision mr
               JOIN assets.material_applicability ma ON ma.revision_id=mr.id
               JOIN assets.file_object fo ON fo.id=mr.file_object_id
               WHERE mr.status='published' AND fo.storage_status='available'
                 AND ma.conditions->>'domain'='baby' AND ma.conditions->>'corpus'=%s""", (corpus,)
        ).fetchone()[0]
        manual_status = "pass" if manual_rows else "blocked"
        checks.append(_check("manual_mapping", manual_status,
                             "published_manual_mapping_present" if manual_rows else "no_published_manual_mapping",
                             published_mappings=manual_rows, corpus=corpus))

        route_paths = set(__import__("src.api", fromlist=["app"]).app.openapi()["paths"])
        required_routes = {"/health", "/session", "/session/{list_id}/recommend", "/session/{list_id}/result"}
        missing_routes = sorted(required_routes - route_paths)
        status_rows = conn.execute(
            "SELECT status, count(*) FROM engine.recommendation_run GROUP BY status ORDER BY status"
        ).fetchall()
        observed_statuses = {status: count for status, count in status_rows}
        unknown_statuses = sorted(set(observed_statuses) - {"running", *TERMINAL_RUN_STATUSES})
        checks.append(_check(
            "api_and_runs", "pass" if not missing_routes and not unknown_statuses else "fail",
            "required_api_and_run_statuses_present" if not missing_routes and not unknown_statuses else "api_or_run_status_mismatch",
            missing_routes=missing_routes, run_statuses=observed_statuses,
            terminal_statuses=sorted(TERMINAL_RUN_STATUSES), unknown_statuses=unknown_statuses,
        ))
    except psycopg.Error as exc:
        checks.append(_check("database_query", "fail", "readiness_query_failed", error_type=type(exc).__name__))
    finally:
        conn.close()
    return _report(checks, provider_result, corpus)


def _report(checks: list[Check], provider: Check, corpus: str) -> dict[str, Any]:
    required_failures = [c.id for c in checks if c.status == "fail"]
    blocked = [c.id for c in checks if c.status == "blocked"]
    status = "failed" if required_failures else ("partial" if blocked else "ready")
    return {
        "status": status,
        "checks": [asdict(check) for check in checks],
        "provider": provider.observed.get("configured"),
        "corpus": corpus,
        "versions": {"contract": 3, "target_db_commit": "da798393850c03866374b05c01eed568fbc84f71"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("synthetic", "real"), default="synthetic")
    parser.add_argument("--provider", choices=("auto", "unconfigured", "local-file"), default="auto")
    parser.add_argument("--output", type=Path, help="JSON artifact path (created after all read-only checks)")
    args = parser.parse_args(argv)
    report = collect_readiness(dsn=os.getenv("DATABASE_URL"), corpus=args.corpus, provider=args.provider)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
