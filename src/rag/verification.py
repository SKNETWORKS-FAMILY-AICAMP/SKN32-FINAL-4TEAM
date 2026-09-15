"""Narrow deterministic verifier for the synthetic seat eligibility contract,
plus the P3 full-catalog verification rule registry loader.

Facts are extracted from retrieved manual text, never from facts.jsonl. This
verifies only stated eligibility; it is not a complete product safety verdict.
"""

from dataclasses import replace
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
import re

import yaml

# The 15 need-area product slots the P3 execution doc requires a registry entry
# for. `clothing` is a declared data_gap in config/baby_requirement_rules.yaml —
# no catalog, no official classification, no product evidence exists for it, so it
# is deliberately excluded here rather than mapped to an unrelated category.
REQUIRED_VERIFICATION_SLOTS: frozenset[str] = frozenset({
    "bottle", "formula", "high_chair", "baby_food", "crib", "sleepwear",
    "stroller", "car_seat", "bath", "skincare", "diaper", "wipes", "mat",
    "gate", "thermometer",
})
_ALLOWED_SCOPES = {"synthetic_demo", "production"}
_ALLOWED_UNKNOWN_REASONS = {
    "missing_rule_evidence", "missing_product_identity", "evidence_provider_unavailable",
    "evidence_provider_failed", "scope_mismatch", "missing_verification_input",
}
_ALLOWED_FAIL_REASONS = {
    "active_recall", "certificate_mismatch", "condition_out_of_range", "identity_mismatch",
}
_PRODUCTION_ALLOWED_AUTHORITIES = {"official", "manufacturer"}
_DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "baby_verification_rules.yaml"

# Slots whose rule declares optional_condition_claims AND have an actually
# implemented condition-layer checker wired into verify_baby_candidate. Only
# `stroller` (this module's verify_seat, backed by real manual-text retrieval) is
# implemented — declaring a numeric age/weight threshold for any other category
# without a real regulatory or manufacturer source would be fabrication, so those
# rules carry optional_condition_claims: [] instead (P3 doc "금지 사항").
CONDITION_CHECKED_SLOTS: frozenset[str] = frozenset({"stroller"})


class BabyVerificationRuleError(ValueError):
    """Raised when config/baby_verification_rules.yaml fails schema/source/date
    validation. The registry must load correctly or not at all — a partially
    valid registry could silently under-cover a safety-relevant slot."""


def _fail(code: str, detail: str = "") -> None:
    raise BabyVerificationRuleError(f"{code}: {detail}" if detail else code)


def _validate_source(rule_id: str, scopes: list[str], source: dict, *, today: date) -> None:
    if not isinstance(source, dict):
        _fail("invalid_source", rule_id)
    authority = source.get("authority")
    url = source.get("url")
    version = source.get("version")
    retrieved_on = source.get("retrieved_on")
    if not authority or not url or not version or not retrieved_on:
        _fail("incomplete_source", rule_id)
    if isinstance(retrieved_on, date):
        retrieved_date = retrieved_on if not isinstance(retrieved_on, datetime) else retrieved_on.date()
    else:
        try:
            retrieved_date = date.fromisoformat(str(retrieved_on))
        except ValueError:
            _fail("invalid_retrieved_on", rule_id)
    if retrieved_date > today:
        _fail("future_retrieved_on", rule_id)
    if "production" in scopes:
        if authority not in _PRODUCTION_ALLOWED_AUTHORITIES:
            _fail("production_requires_official_or_manufacturer_source", rule_id)
        if not str(url).startswith("https://"):
            _fail("production_requires_https_url", rule_id)
    if "synthetic_demo" in scopes:
        if authority != "synthetic_fixture":
            _fail("synthetic_demo_requires_synthetic_fixture_source", rule_id)
        if not str(url).startswith("synthetic://"):
            _fail("synthetic_demo_requires_synthetic_url", rule_id)


def _validate_rule(rule: dict, *, today: date) -> dict:
    rule_id = rule.get("rule_id")
    if not rule_id or not isinstance(rule_id, str):
        _fail("missing_rule_id")
    rule_version = rule.get("rule_version")
    if not rule_version:
        _fail("missing_rule_version", rule_id)
    slot_key = rule.get("slot_key")
    if slot_key not in REQUIRED_VERIFICATION_SLOTS:
        _fail("slot_key_not_in_target_registry", f"{rule_id}:{slot_key}")
    scopes = rule.get("scopes")
    if not scopes or not isinstance(scopes, list) or any(s not in _ALLOWED_SCOPES for s in scopes):
        _fail("invalid_scopes", rule_id)
    required_claims = rule.get("required_claims")
    if not required_claims or not isinstance(required_claims, list):
        _fail("empty_required_claims", rule_id)
    optional_condition_claims = rule.get("optional_condition_claims", [])
    if not isinstance(optional_condition_claims, list):
        _fail("invalid_optional_condition_claims", rule_id)
    unknown_when = rule.get("unknown_when")
    if not unknown_when or any(r not in _ALLOWED_UNKNOWN_REASONS for r in unknown_when):
        _fail("unknown_status_code_in_unknown_when", rule_id)
    fail_when = rule.get("fail_when")
    if not fail_when or any(r not in _ALLOWED_FAIL_REASONS for r in fail_when):
        _fail("unknown_status_code_in_fail_when", rule_id)
    if rule.get("pass_when") != "all_required_claims_verified":
        _fail("unsupported_pass_when", rule_id)
    not_applicable_reason = rule.get("not_applicable_reason")
    if rule.get("not_applicable") and not not_applicable_reason:
        _fail("not_applicable_requires_reason_and_source", rule_id)
    _validate_source(rule_id, scopes, rule.get("source") or {}, today=today)
    return {
        "rule_id": rule_id, "rule_version": rule_version, "slot_key": slot_key,
        "scopes": list(scopes), "applies_when": rule.get("applies_when") or {},
        "required_claims": list(required_claims),
        "optional_condition_claims": list(optional_condition_claims),
        "pass_when": rule["pass_when"], "unknown_when": list(unknown_when),
        "fail_when": list(fail_when), "source": dict(rule["source"]),
        "not_applicable_reason": not_applicable_reason,
    }


def _load_baby_verification_rules_uncached(path: Path, *, today: date | None = None) -> dict[str, list[dict]]:
    """Load + validate config/baby_verification_rules.yaml.

    Returns slot_key -> list[rule] (normally one rule per slot). Raises
    BabyVerificationRuleError on any schema/source/date/duplicate violation —
    callers must not catch this to silently fall back to an empty registry.
    """
    today = today or date.today()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        _fail("unsupported_schema_version")
    rules = raw.get("rules")
    if not rules or not isinstance(rules, list):
        _fail("empty_rule_list")

    by_id: dict[str, dict] = {}
    by_slot: dict[str, list[dict]] = {}
    seen_slot_scope: set[tuple[str, str]] = set()
    for entry in rules:
        validated = _validate_rule(entry, today=today)
        if validated["rule_id"] in by_id:
            _fail("duplicate_rule_id", validated["rule_id"])
        by_id[validated["rule_id"]] = validated
        for scope in validated["scopes"]:
            key = (validated["slot_key"], scope)
            if key in seen_slot_scope:
                _fail("ambiguous_rule_for_slot_and_scope", f"{key[0]}:{key[1]}")
            seen_slot_scope.add(key)
        by_slot.setdefault(validated["slot_key"], []).append(validated)

    missing = REQUIRED_VERIFICATION_SLOTS - set(by_slot)
    if missing:
        _fail("missing_required_slots", ",".join(sorted(missing)))
    return by_slot


@lru_cache(maxsize=8)
def _load_cached(path_str: str, today_iso: str) -> dict[str, list[dict]]:
    return _load_baby_verification_rules_uncached(Path(path_str), today=date.fromisoformat(today_iso))


def load_baby_verification_rules(path: Path | str | None = None) -> dict[str, list[dict]]:
    """Public loader. Cached per (path, today) — a rule with a future
    retrieved_on must start failing the day it becomes "future" again, so the
    cache key includes today's date rather than caching forever."""
    resolved = Path(path) if path is not None else _DEFAULT_RULES_PATH
    return _load_cached(str(resolved), date.today().isoformat())


def find_verification_rule(rules_by_slot: dict[str, list[dict]], slot_key: str, scope: str) -> dict | None:
    for rule in rules_by_slot.get(slot_key, []):
        if scope in rule["scopes"]:
            return rule
    return None


def manual_rule_inventory() -> dict[str, str]:
    """Compat view over the YAML registry: slot_key -> rule_id, restricted to
    CONDITION_CHECKED_SLOTS (slots with an implemented manual-backed condition
    checker). Replaces the old hardcoded MANUAL_RULE_INVENTORY dict — this can
    never name a rule_id absent from config/baby_verification_rules.yaml."""
    rules = load_baby_verification_rules()
    out = {}
    for slot in CONDITION_CHECKED_SLOTS:
        for rule in rules.get(slot, []):
            out[slot] = rule["rule_id"]
            break
    return out


def reviewed_not_applicable() -> dict[str, str]:
    """Compat view over the YAML registry: slot_key -> reviewed not-applicable
    reason. Empty until a rule with a reviewed, source-backed not_applicable
    determination is actually added to the YAML (P3 doc: never populate this
    without a reviewed source — see module docstring)."""
    rules = load_baby_verification_rules()
    out = {}
    for slot, entries in rules.items():
        for rule in entries:
            if rule.get("not_applicable_reason"):
                out[slot] = rule["not_applicable_reason"]
    return out


# Backward-compatible module attributes for existing callers (src.engine.stage3c_verify
# still imports these two names directly). Computed once at import time from the
# validated YAML registry — if the registry is broken, import fails loudly instead
# of the app silently running with an empty/wrong inventory.
MANUAL_RULE_INVENTORY: dict[str, str] = manual_rule_inventory()
REVIEWED_NOT_APPLICABLE: dict[str, str] = reviewed_not_applicable()


def verify_seat(
    service, request, *, age_months=None, weight_kg=None, independent_sitting=None
):
    result = service.search(replace(request, query="좌석 모드 월령 체중 필수 조건"))
    base = {
        "search_status": result.status,
        "error_code": result.error_code,
        "rule_score": None,
        "evidence_coverage": 0.0,
        "verification_status": "unknown",
        "eligibility_status": "unknown",
        "checks": [],
        "evidence": [],
    }
    if result.status != "success":
        return base
    hits = [
        h
        for h in result.hits
        if h["locator"].get("section_code") == "S01"
        and h["review_status"] == "verified"
    ]
    if not hits:
        return base
    patterns = {
        "age_months": r"좌석 모드 월령: (\d+(?:\.\d+)?) 개월 이상\.",
        "weight_kg": r"좌석 모드 체중: (\d+(?:\.\d+)?) kg 이하\.",
        "independent_sitting": r"좌석 모드 필수 조건: (혼자 앉을 수 있음)\.",
    }
    values = {
        key: {match for h in hits for match in re.findall(pattern, h["text"])}
        for key, pattern in patterns.items()
    }
    if any(len(v) != 1 for v in values.values()):
        return {**base, "reason": "missing_or_conflicting_conditions", "evidence": hits}
    # Reject other eligibility statements instead of ignoring additional conditions.
    for h in hits:
        statements = [
            line for line in h["text"].splitlines() if line.startswith("좌석 모드 ")
        ]
        if any(
            not any(re.fullmatch(pattern, line) for pattern in patterns.values())
            for line in statements
        ):
            return {
                **base,
                "reason": "unsupported_eligibility_condition",
                "evidence": hits,
            }
    minimum = float(next(iter(values["age_months"])))
    maximum = float(next(iter(values["weight_kg"])))

    def numeric(value):
        import math

        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    checks = [
        {
            "axis": "age_months",
            "status": "unknown"
            if not numeric(age_months)
            else "pass"
            if age_months >= minimum
            else "fail",
        },
        {
            "axis": "weight_kg",
            "status": "unknown"
            if not numeric(weight_kg)
            else "pass"
            if weight_kg <= maximum
            else "fail",
        },
        {
            "axis": "independent_sitting",
            "status": "unknown"
            if type(independent_sitting) is not bool
            else "pass"
            if independent_sitting
            else "fail",
        },
    ]
    verdict = (
        "fail"
        if any(c["status"] == "fail" for c in checks)
        else "unknown"
        if any(c["status"] == "unknown" for c in checks)
        else "pass"
    )
    return {
        **base,
        "checks": checks,
        "evidence": hits,
        "evidence_coverage": 1.0,
        "eligibility_status": verdict,
        "verification_status": "partial",
        "rule_score": None,
        "scope": "stated_seat_eligibility_only",
        "is_synthetic": request.corpus == "synthetic",
    }
