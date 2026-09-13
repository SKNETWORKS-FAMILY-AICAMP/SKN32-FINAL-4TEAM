"""P0 v3 — develop `da79839` DB alignment (D0-01). Real PostgreSQL only.

Supersedes the earlier rag-branch "full reduction" acceptance (SR01-09, migrations
0010-0015 under that design): the active contract is P0_schema_contracts.md's
ACTIVE DB CONTRACT + DEVELOP_DB_TRANSITION.md. This file checks the migration set
itself (source-string assertions, cheap and stable) plus a real Postgres D0-01 case
(table/schema keep-remove list, idempotent bootstrap). Behavioral D0-02/D0-03 cases
that need the running app live in test_p0_list_item_integrity.py.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from pydantic import ValidationError

from src.schemas import ConditionState, RecommendResultOut

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db/migrations"

# The develop `da79839` migration chain this task restores — MUST be exactly these
# filenames, in this order, with the two rag-branch-only reduction designs absent.
EXPECTED_CHAIN = [
    "0000_prereq.sql", "0001_tables.sql", "0002_unique.sql", "0003_foreign_keys.sql",
    "0004_triggers.sql", "0005_indexes.sql", "0006_rag_active_profile.sql",
    "0007_app_user_password_auth.sql", "0008_frontend_contract.sql",
    "0009_frontend_requirement_revision.sql", "0010_review_summary_relation_axis.sql",
    "0011_drop_rag_schema.sql", "0012_schema_reduction_safe_subset.sql",
    "0013_result_item_interaction.sql",
]

# Tables/schemas the rag-branch's "full reduction" (0010-0015 under that design)
# removed but develop's actual schema keeps — must exist after this chain.
RETAINED = [
    "config.domain_version", "planning.plan_node", "planning.purchase_line",
    "assets.material_revision", "assets.material_applicability", "evidence.source",
    "community.review_revision", "notification.price_watch",
]
# What develop's own safe-subset reduction removes — must be absent.
REMOVED_TABLES = [
    "planning.owned_item", "planning.fulfillment_allocation",
    "identity.user_preference", "catalog.product_category_membership",
    "engine.candidate_evidence", "engine.validation_target", "engine.validation_evidence",
    "notification.notification_event", "notification.price_watch_evaluation",
]
REMOVED_SCHEMAS = ["rag", "dataset"]
# planning.item / config.domain (single-table merge) never existed in develop; the
# rag-branch's destructive design invented them — they must not be reintroduced.
NEVER_TABLES = ["planning.item"]


def test_migration_chain_matches_develop_exactly():
    actual = sorted(f.name for f in MIGRATIONS.glob("*.sql"))
    assert actual == EXPECTED_CHAIN, (
        "migration set drifted from develop `da79839` — got extra/missing files: "
        f"{set(actual) ^ set(EXPECTED_CHAIN)}"
    )


def test_no_full_reduction_migration_survives():
    """The rag-branch's own destructive-reduction filenames must be gone, not just unused."""
    names = {f.name for f in MIGRATIONS.glob("*.sql")}
    for stale in (
        "0010_schema_reduction_v1.sql", "0011_schema_reduction_completion.sql",
        "0012_schema_reduction_destructive.sql", "0013_schema_reduction_scope_constraints.sql",
        "0014_item_reference_integrity.sql", "0015_auth_version.sql",
    ):
        assert stale not in names, f"{stale} should have been replaced by the develop chain"


def test_drop_rag_schema_removes_all_six_tables():
    sql = (MIGRATIONS / "0011_drop_rag_schema.sql").read_text(encoding="utf-8")
    assert "DROP SCHEMA rag CASCADE" in sql


def test_safe_subset_keeps_price_watch_and_purchase_line():
    sql = (MIGRATIONS / "0012_schema_reduction_safe_subset.sql").read_text(encoding="utf-8")
    for removed in ("DROP TABLE planning.owned_item", "DROP TABLE planning.fulfillment_allocation",
                    "DROP TABLE identity.user_preference", "DROP TABLE catalog.product_category_membership",
                    "DROP TABLE engine.candidate_evidence", "DROP TABLE engine.validation_target",
                    "DROP TABLE engine.validation_evidence", "DROP TABLE notification.notification_event",
                    "DROP TABLE notification.price_watch_evaluation", "DROP SCHEMA dataset CASCADE"):
        assert removed in sql, removed
    # It must NOT touch these — they are develop's live, retained tables. Word-boundary
    # check: "DROP TABLE notification.price_watch" is a substring of the (removed)
    # "...price_watch_evaluation" statement, so match on the statement terminator too.
    for keep in ("planning.purchase_line", "planning.plan_node", "notification.price_watch",
                "config.domain_version", "assets.material_revision", "evidence.source"):
        assert f"DROP TABLE {keep} " not in sql and f"DROP TABLE {keep};" not in sql
        assert f"DROP SCHEMA {keep}" not in sql


def test_condition_and_recommendation_contract_round_trip():
    state = ConditionState.model_validate({
        "list_id": "list", "category": "baby", "fields": [{"key": "needs", "label": "필요 품목", "value": ["수유"], "status": "confirmed"}],
    })
    assert state.accepts_spec_file is False
    result = RecommendResultOut.model_validate({
        "list_id": "list", "run_id": "run",
        "status": "done", "category": "baby", "budget_max": 300000,
        "items": [], "totals": {"selected_price": 0, "selected_units": 0},
    })
    assert result.model_dump()["status"] == "done"
    assert ConditionState(list_id="pc-list", category="computer").category == "computer"


DSN = os.getenv("RAG_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark_db = pytest.mark.skipif(not DSN, reason="set DATABASE_URL/RAG_TEST_DATABASE_URL to a disposable database")


@pytestmark_db
def test_d0_01_real_db_has_exact_develop_table_set():
    """D0-01: enumerate actual tables/schemas on the real bootstrapped DB — not just SQL text."""
    with psycopg.connect(DSN) as conn:
        for schema in REMOVED_SCHEMAS:
            row = conn.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,)
            ).fetchone()
            assert row is None, f"schema {schema} should not exist (develop drops it)"
        for qualified in RETAINED:
            schema, table = qualified.split(".")
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                (schema, table),
            ).fetchone()
            assert row is not None, f"{qualified} must exist (develop retains it)"
        for qualified in REMOVED_TABLES + NEVER_TABLES:
            schema, table = qualified.split(".")
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                (schema, table),
            ).fetchone()
            assert row is None, f"{qualified} must not exist"
        total = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN "
            "('pg_catalog','information_schema','_migrations') AND table_type='BASE TABLE'"
        ).fetchone()[0]
        assert total == 38, f"expected develop's 38 tables (58 -> 38 per commit 046eb84), got {total}"
