"""P3 Phase 1 — config/baby_verification_rules.yaml loader/validator.

Pure YAML/schema tests, no DB. Covers: full-registry load, missing slot,
duplicate rule_id, production scope with a synthetic source, empty
required_claims, and a future retrieved_on date all being rejected at load time.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from src.rag.verification import (
    CONDITION_CHECKED_SLOTS,
    REQUIRED_VERIFICATION_SLOTS,
    BabyVerificationRuleError,
    find_verification_rule,
    load_baby_verification_rules,
    manual_rule_inventory,
    reviewed_not_applicable,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / "config" / "baby_verification_rules.yaml"


def _minimal_rule(**overrides) -> dict:
    rule = {
        "rule_id": "baby.bath.evidence.v1",
        "rule_version": "v1",
        "slot_key": "bath",
        "scopes": ["synthetic_demo"],
        "applies_when": {"market": "KR"},
        "required_claims": ["product_identity", "safety_route", "manufacturer_document", "recall_status"],
        "optional_condition_claims": [],
        "pass_when": "all_required_claims_verified",
        "unknown_when": ["missing_rule_evidence", "missing_product_identity"],
        "fail_when": ["active_recall", "certificate_mismatch"],
        "source": {
            "authority": "synthetic_fixture",
            "url": "synthetic://baby-demo-v1/bath",
            "version": "baby-demo-v1",
            "retrieved_on": "2026-09-14",
        },
    }
    rule.update(overrides)
    return rule


def _write(tmp_path: Path, rules: list[dict], *, schema_version: int = 1) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump({"schema_version": schema_version, "rules": rules}, allow_unicode=True), encoding="utf-8")
    return path


def _all_slot_rules() -> list[dict]:
    """One valid rule per REQUIRED_VERIFICATION_SLOTS entry, for tests that need
    a passing full registry as a baseline to then break one field of."""
    return [_minimal_rule(rule_id=f"baby.{slot}.evidence.v1", slot_key=slot) for slot in REQUIRED_VERIFICATION_SLOTS]


# ── canonical registry actually shipped in the repo ────────────────────────

def test_canonical_registry_loads_and_covers_all_required_slots():
    rules = load_baby_verification_rules(CANONICAL_PATH)
    assert set(rules) == REQUIRED_VERIFICATION_SLOTS
    assert "clothing" not in rules


def test_canonical_registry_has_no_production_scope_rules_yet():
    """No real official/manufacturer evidence has been collected this session —
    the shipped registry must not silently claim production coverage."""
    rules = load_baby_verification_rules(CANONICAL_PATH)
    for slot, entries in rules.items():
        for rule in entries:
            assert "production" not in rule["scopes"], f"{slot} claims production without real evidence"


def test_condition_checked_slots_are_a_subset_of_the_registry():
    rules = load_baby_verification_rules(CANONICAL_PATH)
    for slot in CONDITION_CHECKED_SLOTS:
        assert slot in rules


def test_manual_rule_inventory_and_reviewed_not_applicable_are_compat_views():
    inventory = manual_rule_inventory()
    assert set(inventory) == set(CONDITION_CHECKED_SLOTS)
    rules = load_baby_verification_rules(CANONICAL_PATH)
    rule_ids = {r["rule_id"] for entries in rules.values() for r in entries}
    for rule_id in inventory.values():
        assert rule_id in rule_ids
    # Nothing has been reviewed as not_applicable yet — must stay empty, not
    # silently populated to unblock a slot without a reviewed source.
    assert reviewed_not_applicable() == {}


def test_find_verification_rule_respects_scope():
    rules = load_baby_verification_rules(CANONICAL_PATH)
    assert find_verification_rule(rules, "bath", "synthetic_demo") is not None
    assert find_verification_rule(rules, "bath", "production") is None
    assert find_verification_rule(rules, "no_such_slot", "synthetic_demo") is None


# ── rejections ───────────────────────────────────────────────────────────

def test_missing_required_slot_is_rejected(tmp_path):
    rules = [r for r in _all_slot_rules() if r["slot_key"] != "diaper"]
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="missing_required_slots"):
        load_baby_verification_rules(path)


def test_duplicate_rule_id_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules.append(_minimal_rule(rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"]))
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="duplicate_rule_id"):
        load_baby_verification_rules(path)


def test_production_scope_with_synthetic_source_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(
        rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"],
        scopes=["production"],
        source={"authority": "synthetic_fixture", "url": "synthetic://x", "version": "v1", "retrieved_on": "2026-09-14"},
    )
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="production_requires_official_or_manufacturer_source"):
        load_baby_verification_rules(path)


def test_production_scope_requires_https_url(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(
        rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"],
        scopes=["production"],
        source={"authority": "official", "url": "http://insecure.example", "version": "v1", "retrieved_on": "2026-09-14"},
    )
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="production_requires_https_url"):
        load_baby_verification_rules(path)


def test_empty_required_claims_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"], required_claims=[])
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="empty_required_claims"):
        load_baby_verification_rules(path)


def test_future_retrieved_on_is_rejected(tmp_path):
    future = (date.today() + timedelta(days=30)).isoformat()
    rules = _all_slot_rules()
    src = dict(rules[0]["source"])
    src["retrieved_on"] = future
    rules[0] = _minimal_rule(rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"], source=src)
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="future_retrieved_on"):
        load_baby_verification_rules(path)


def test_unknown_status_code_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(
        rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"],
        unknown_when=["totally_made_up_reason"],
    )
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="unknown_status_code_in_unknown_when"):
        load_baby_verification_rules(path)


def test_slot_outside_target_registry_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(rule_id="baby.clothing.evidence.v1", slot_key="clothing")
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="slot_key_not_in_target_registry"):
        load_baby_verification_rules(path)


def test_not_applicable_without_reason_is_rejected(tmp_path):
    rules = _all_slot_rules()
    rules[0] = _minimal_rule(rule_id=rules[0]["rule_id"], slot_key=rules[0]["slot_key"], not_applicable=True)
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="not_applicable_requires_reason_and_source"):
        load_baby_verification_rules(path)


def test_wrong_schema_version_is_rejected(tmp_path):
    path = _write(tmp_path, _all_slot_rules(), schema_version=2)
    with pytest.raises(BabyVerificationRuleError, match="unsupported_schema_version"):
        load_baby_verification_rules(path)


def test_ambiguous_duplicate_slot_scope_is_rejected(tmp_path):
    rules = _all_slot_rules()
    dup = _minimal_rule(rule_id="baby.bath.evidence.v2", slot_key=rules[0]["slot_key"])
    rules.append(dup)
    path = _write(tmp_path, rules)
    with pytest.raises(BabyVerificationRuleError, match="ambiguous_rule_for_slot_and_scope"):
        load_baby_verification_rules(path)
