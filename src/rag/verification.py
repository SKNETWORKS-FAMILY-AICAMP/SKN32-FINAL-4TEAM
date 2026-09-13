"""Narrow deterministic verifier for the synthetic seat eligibility contract.

Facts are extracted from retrieved manual text, never from facts.jsonl. This
verifies only stated eligibility; it is not a complete product safety verdict.
"""

from dataclasses import replace
import re


def verify_seat(
    service, request, *, age_months=None, weight_kg=None, independent_sitting=None
):
    result = service.search(replace(request, query="좌석 모드 월령 체중 필수 조건"))
    base = {
        "search_status": result.status,
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
    service.repo.mark_context(result.run_id, [h["evidence_id"] for h in hits])
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
