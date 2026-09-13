from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import ConditionState, RecommendResultOut
from src.reduction_contracts import EvidenceRefs, ValidationIssue

ROOT = Path(__file__).resolve().parents[1]
DESTRUCTIVE = ROOT / "db/migrations/0012_schema_reduction_destructive.sql"

REMOVED_TABLES = [
    "config.domain_version", "identity.user_preference", "catalog.product_category_membership",
    "planning.plan_node", "planning.owned_item", "planning.purchase_line", "planning.fulfillment_allocation",
    "assets.material_revision", "assets.material_applicability", "evidence.source",
    "engine.candidate_evidence", "engine.validation_target", "engine.validation_evidence",
    "community.review_revision", "community.pc_build_version", "community.pc_build_component",
    "community.pc_build", "community.review",
]


def test_destructive_migration_drops_every_reduced_table_and_schema():
    sql = DESTRUCTIVE.read_text(encoding="utf-8")
    for table in REMOVED_TABLES:
        assert f"DROP TABLE {table}" in sql or f"DROP TABLE IF EXISTS {table}" in sql, table
    assert "DROP SCHEMA notification CASCADE" in sql
    assert "DROP SCHEMA dataset CASCADE" in sql
    assert "DROP SCHEMA shared CASCADE" in sql
    # SR03: fresh-install precondition guards run before any destructive DDL.
    guard_pos = sql.index("fresh_install_precondition_failed")
    first_drop_pos = min(sql.index(f"DROP TABLE {t}") if f"DROP TABLE {t}" in sql else sql.index(f"DROP TABLE IF EXISTS {t}") for t in REMOVED_TABLES[:1])
    assert guard_pos < first_drop_pos
    assert "app.set_updated_at" in sql  # timestamp function rebound into a retained namespace


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
    assert isinstance(result.progress, list)
    assert isinstance(result.conditions_summary, str)
    assert ConditionState(list_id="pc-list", category="computer").category == "computer"


def test_evidence_and_validation_json_require_v1_shape():
    refs = EvidenceRefs.model_validate({"schema_version": 1, "refs": [{
        "evidence_id": "e", "claim_key": "manual_applicability", "material_id": "m",
        "material_version": "v1", "file_sha256": "abc", "locator": {"section_code": "S07"},
    }]})
    assert refs.refs[0].claim_key == "manual_applicability"
    with pytest.raises(ValidationError):
        ValidationIssue.model_validate({"schema_version": 2})


def test_completion_migration_still_guards_v1_v2_json_shapes():
    sql = (ROOT / "db/migrations/0011_schema_reduction_completion.sql").read_text(encoding="utf-8")
    assert "recommendation_candidate_evidence_refs_v1_check" in sql
    assert "validation_result_issues_array_check" in sql
    assert "requirement_slot_key_nonempty_check" in sql
    destructive_sql = DESTRUCTIVE.read_text(encoding="utf-8")
    assert "VALIDATE CONSTRAINT recommendation_candidate_evidence_refs_v1_check" in destructive_sql
    assert "VALIDATE CONSTRAINT validation_result_issues_array_check" in destructive_sql
    seed = (ROOT / "db/seed.py").read_text(encoding="utf-8")
    assert "current_version_no" in seed and "content_hash" in seed


def test_seed_and_repos_no_longer_reference_removed_tables():
    for path in ["db/seed.py", "db/seed_catalog.py", "src/repo/plan_repo.py",
                 "src/repo/engine_repo.py", "src/repo/rag_repo.py", "src/services/list_service.py"]:
        text = (ROOT / path).read_text(encoding="utf-8")
        for needle in ("shared.unit", "config.domain_version", "evidence.source WHERE",
                       "assets.material_revision\n", "planning.plan_node", "planning.owned_item",
                       "planning.purchase_line", "planning.fulfillment_allocation"):
            assert needle not in text, f"{path} still references {needle!r}"
