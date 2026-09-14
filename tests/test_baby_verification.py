"""P3 Phase 3 — verify_baby_candidate() over the rule-registry + evidence-DB path.

Needs a disposable, migrated DB with scripts/seed_baby_catalog.py and
scripts/seed_baby_synthetic_evidence.py already applied (see
tests/test_baby_recommendation_http.py's module docstring for the exact setup
commands, plus `uv run python scripts/seed_baby_synthetic_evidence.py`).
"""
from __future__ import annotations

import os

import psycopg
import pytest

from src.engine.stage3c_verify import verify_baby_candidate
from src.rag.provider import get_search_provider
from src.rag.service import RagService
from src.rag.verification import REQUIRED_VERIFICATION_SLOTS
from src.repo.material_repo import MaterialRepo

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set DATABASE_URL to a disposable migrated+baby-seeded database")

RUN_CONTEXT = {"recommendation_run_id": "11111111-1111-1111-1111-111111111111"}


@pytest.fixture
def rag_service():
    with psycopg.connect(DSN) as conn:
        yield RagService(MaterialRepo(conn), get_search_provider())
        conn.rollback()


@pytest.fixture
def evidence_manifest():
    import yaml
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "data" / "baby" / "evidence" / "synthetic-demo-v1.yaml"
    if not path.is_file():
        pytest.skip("run scripts/seed_baby_synthetic_evidence.py against DATABASE_URL first")
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_slot: dict[str, list[dict]] = {}
    for record in manifest["records"]:
        by_slot.setdefault(record["slot_key"], []).append(record)
    return by_slot


def _candidate(record: dict, *, corpus: str = "synthetic") -> dict:
    return {
        "candidate_id": "c", "requirement_id": "r", "product_key": record["product_key"],
        "variant_key": record["variant_key"], "slot_key": record["slot_key"], "corpus": corpus,
        "market": "KR_DEMO", "language": "ko",
    }


STROLLER_CONDITIONS = {"age_stage": {"months": 30, "exact": True}, "weight_kg": 12, "independent_sitting": True}


@pytest.mark.parametrize("slot", sorted(REQUIRED_VERIFICATION_SLOTS))
def test_pass_fixture_is_pass_and_selectable(rag_service, evidence_manifest, slot):
    pass_record = evidence_manifest[slot][0]
    conditions = STROLLER_CONDITIONS if slot == "stroller" else {}
    check = verify_baby_candidate(rag_service, _candidate(pass_record), conditions, RUN_CONTEXT)
    assert check.eligibility == "pass"
    assert check.selection_allowed is True
    assert check.issues[0]["reason"] == "all_required_claims_verified"


@pytest.mark.parametrize("slot", sorted(REQUIRED_VERIFICATION_SLOTS))
def test_blocked_fixture_is_never_selectable(rag_service, evidence_manifest, slot):
    blocked_record = evidence_manifest[slot][1]
    conditions = STROLLER_CONDITIONS if slot == "stroller" else {}
    check = verify_baby_candidate(rag_service, _candidate(blocked_record), conditions, RUN_CONTEXT)
    assert check.eligibility in ("unknown", "fail")
    assert check.selection_allowed is False


def test_bottle_recall_fixture_is_a_fail_not_unknown(rag_service, evidence_manifest):
    check = verify_baby_candidate(rag_service, _candidate({
        "product_key": "SYN-BOTTLE-RECALL-001", "variant_key": "SYN-BOTTLE-RECALL-001-240ML", "slot_key": "bottle",
    }), {}, RUN_CONTEXT)
    assert check.eligibility == "fail"
    assert check.issues[0]["reason"] == "active_recall"


def test_uncataloged_product_is_unknown_missing_product_identity(rag_service):
    check = verify_baby_candidate(rag_service, {
        "candidate_id": "c", "requirement_id": "r", "product_key": "SYN-DOES-NOT-EXIST",
        "variant_key": "SYN-DOES-NOT-EXIST-V1", "slot_key": "bath", "corpus": "synthetic",
    }, {}, RUN_CONTEXT)
    assert check.eligibility == "unknown"
    assert check.selection_allowed is False
    assert check.issues[0]["reason"] == "missing_product_identity"


def test_missing_candidate_identity_fields_is_unknown(rag_service):
    check = verify_baby_candidate(rag_service, {
        "candidate_id": "c", "requirement_id": "r", "slot_key": "bath", "corpus": "synthetic",
    }, {}, RUN_CONTEXT)
    assert check.eligibility == "unknown"
    assert check.issues[0]["reason"] == "missing_product_identity"


def test_production_scope_has_no_rule_yet(rag_service, evidence_manifest):
    """No real official/manufacturer evidence exists this session — a real-corpus
    candidate must resolve to unknown, never silently reuse a synthetic_demo pass."""
    pass_record = evidence_manifest["bath"][0]
    check = verify_baby_candidate(rag_service, _candidate(pass_record, corpus="real"), {}, RUN_CONTEXT)
    assert check.eligibility == "unknown"
    assert check.selection_allowed is False
    assert check.issues[0]["reason"] in ("scope_mismatch", "no_reviewed_rule_for_category", "missing_product_identity")


def test_stroller_too_young_is_condition_fail(rag_service, evidence_manifest):
    pass_record = evidence_manifest["stroller"][0]
    check = verify_baby_candidate(rag_service, _candidate(pass_record),
                                  {"age_stage": {"months": 3, "exact": True}, "weight_kg": 8, "independent_sitting": False},
                                  RUN_CONTEXT)
    assert check.eligibility == "fail"
    assert check.issues[0]["reason"] == "condition_out_of_range"


def test_stroller_without_condition_input_is_missing_verification_input(rag_service, evidence_manifest):
    pass_record = evidence_manifest["stroller"][0]
    check = verify_baby_candidate(rag_service, _candidate(pass_record), {}, RUN_CONTEXT)
    assert check.eligibility == "unknown"
    assert check.issues[0]["reason"] == "missing_verification_input"


def test_evidence_refs_are_populated_on_pass(rag_service, evidence_manifest):
    pass_record = evidence_manifest["bath"][0]
    check = verify_baby_candidate(rag_service, _candidate(pass_record), {}, RUN_CONTEXT)
    assert check.eligibility == "pass"
    assert len(check.issues[0]["evidence_refs"]) == 4  # product_identity, safety_route, manufacturer_document, recall_status
    assert all(check.issues[0]["evidence_refs"])
