"""[3-C] 검증 — 규칙 judge + 쟁점 문장화 + RAG.

컴퓨터: 완성 세트 1건을 대상. 유아: 품목별.
신뢰도 = 100 − Σ(쟁점 감점). CONFIDENCE_THRESHOLD 미만이면 재탐색.

검사AI↔변호인AI 디베이트는 걷어냈다 (기획서 §10-12). 축마다 논증 2건을 만드는 대신
관측값·근거를 중립 서술한 쟁점 문장 1건만 만든다. 판정과 감점은 규칙이 정한다.

데모 = 시나리오별 정답값 주입 (기획서 §10-9 B안):
  - tool 결과·신뢰도·회색축·문제 슬롯을 scenario["verify"]["rounds"][i] 에서 그대로.
  - 쟁점 문장만 LLM 으로 실제 생성 (MOCK_MODE 면 목 문장).
  - VerificationResult 스키마 / judge 집계 규칙 / evidence_search 계약은 실제 것 유지 → drop-in.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.clients.llm_client import call_llm
from src.config import CONFIDENCE_THRESHOLD
from src.dto import BuildResult, Issue, VerificationResult, VerificationTarget
from src.engine import LogFn
from src.engine.prompts import verify_issue_system
from src.rag.evidence_search import evidence_search

if TYPE_CHECKING:
    from src.i18n import Locale

# 이 문장은 서술만 한다 — 판정이 섞이면 규칙이 정한 judge 와 화면에서 어긋난다.
_BANNED_KOREAN_VERDICTS = (
    "위반", "불합격", "부적합", "적합", "통과", "안전합니다", "위험합니다",
)
_BANNED_ENGLISH_VERDICT = re.compile(
    r"\b(?:violation|violates?|pass(?:es|ed)?|fail(?:s|ed)?|safe|unsafe|"
    r"suitable|unsuitable|compliant|non[- ]compliant)\b",
    re.IGNORECASE,
)
_EN_AXIS_LABELS = {
    "예산": "Budget", "가격": "Price", "성능": "Performance", "파워": "Power",
    "전원": "Power", "호환성": "Compatibility", "밸런스": "Balance",
    "호환여유": "Compatibility headroom", "리뷰 진위 (담당 팀원)": "Review authenticity",
    "RAG 근거 (담당 팀원)": "RAG evidence",
}


def _axis_label(axis: str, locale: Locale) -> str:
    return _EN_AXIS_LABELS.get(axis, axis) if locale == "en-US" else axis


def _contains_verdict(text: str) -> bool:
    return any(word in text for word in _BANNED_KOREAN_VERDICTS) or bool(
        _BANNED_ENGLISH_VERDICT.search(text)
    )


def _rule_sentence(
    axis: str,
    tool_result: str,
    *,
    locale: Locale = "ko-KR",
) -> str:
    """LLM 없이 쓰는 기본 문장. 관측값만 옮기고 해석하지 않는다."""
    if locale == "en-US":
        if tool_result:
            return f"{axis}: observed value {tool_result}"
        return f"{axis}: no observed value was recorded"
    if tool_result:
        return f"{axis}: 관측값 {tool_result}"
    return f"{axis}: 관측값이 기록되지 않았습니다"


def _issue_sentence(
    axis: str,
    tool_result: str,
    evidence: list[dict],
    *,
    locale: Locale = "ko-KR",
) -> str:
    """쟁점 1건을 중립 문장으로.

    판정어가 섞이면 1회 재생성하고, 그래도 섞이거나 호출이 실패하면 규칙 템플릿으로
    내려간다. 문장화 실패는 신뢰도 점수에 영향을 주지 않는다 (기획서 §10-11 E4).
    """
    if locale == "en-US":
        # stage4 의 link_check 값("ok (근사)")은 엔진 상수다 — 영어 문장에 한국어 토막이 섞이지 않게 입력에서만 바꾼다
        tool_result = (tool_result or "").replace("근사", "approximate")
    snippets = "\n".join(f"- {e.get('text', '')}" for e in evidence) or ("- (none)" if locale == "en-US" else "- (없음)")
    prompt = (f"Axis: {axis}\nObserved value: {tool_result or '(not recorded)'}\nEvidence:\n{snippets}"
              if locale == "en-US"
              else f"축: {axis}\n관측값: {tool_result or '(기록 없음)'}\n근거:\n{snippets}")
    for _attempt in range(2):
        try:
            text = (call_llm(prompt, system=verify_issue_system(locale)).get("text") or "").strip()
        except Exception:
            break
        if text and not _contains_verdict(text):
            return text
    return _rule_sentence(axis, tool_result, locale=locale)


def verify_set(
    build: BuildResult,
    scenario: dict,
    round_index: int,
    log: LogFn,
    *,
    locale: Locale = "ko-KR",
) -> VerificationResult:
    """세트 검증 1라운드. 정답값은 scenario['verify']['rounds'][round_index]."""
    log(f"[3-C] 세트 검증 (규칙 judge + 쟁점 문장화) ... (라운드 {round_index + 1})")
    vspec = scenario["verify"]
    rounds = vspec["rounds"]
    rspec = rounds[min(round_index, len(rounds) - 1)]
    domain = scenario["category"]

    log(f"      [MOCK] 시나리오 정답값 주입: {scenario['scenario']}  라운드 {round_index + 1}/{len(rounds)}")

    issues: list[Issue] = []
    for iss in rspec.get("issues", []):
        source_axis = iss["axis"]
        axis = _axis_label(source_axis, locale)
        tool_result = iss.get("tool_result", "")
        ev = evidence_search(domain, f"{source_axis} 조합 이슈", filters={"axis": source_axis})
        issues.append(Issue(
            axis=axis,
            text=_issue_sentence(axis, tool_result, ev, locale=locale),
            tool_result=tool_result,
            evidence=ev,
            judge=iss.get("judge", ""),
            penalty=int(iss.get("penalty", 0)),
        ))

    confidence = int(rspec["confidence"])           # judge 집계 결과 (데모는 주입값)
    passed = confidence >= CONFIDENCE_THRESHOLD
    gray = list(rspec.get("gray_axes", []))

    for iss in issues:
        log(f"      · {iss.axis}: 감점 {iss.penalty}  ({iss.judge})  근거 {len(iss.evidence)}건")
        log(f"        {iss.text}")
    if gray:
        log(f"      회색축(근거 0건 → 검증 불가): {gray}")
    log(f"      신뢰도 {confidence} → {'통과' if passed else '기준 미달 → 재탐색'}")

    tgt = VerificationTarget(
        subject="세트 전체", confidence=confidence, passed=passed,
        rounds=round_index + 1, issues=issues, gray_axes=gray,
        transcript=[{"round": round_index + 1,
                     "issues": [i.model_dump() for i in issues]}],
    )
    return VerificationResult(list_id=build.list_id, category=domain, mode="set", targets=[tgt])


def verify_build(
    build: BuildResult,
    category: str,
    log: LogFn = lambda _m: None,
    *,
    locale: Locale = "ko-KR",
) -> VerificationResult:
    """DB 경로([추천 실행])의 세트 검증 — 규칙 judge + 쟁점 문장화.

    RAG 근거 연결은 담당 팀원 자리라 여기서는 근거 없이 관측값만으로 문장을 만든다.
    link_check/예산 기반 규칙으로 confidence 를 낸다.
    """
    log("[3-C] 세트 검증 (규칙 스캐폴드) ...")
    issues: list[Issue] = []
    penalty = 0
    for axis, state in (build.link_check or {}).items():
        axis = _axis_label(axis, locale)
        s = str(state).lower()
        if "fail" in s or "미충족" in s or "over" in s:
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, [], locale=locale),
                                tool_result=state, judge="위반", penalty=20))
            penalty += 20
        elif "pending" in s or "근사" in s:
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, [], locale=locale),
                                tool_result=state, judge="확인 필요", penalty=6))
            penalty += 6

    budget = build.budget or {}
    used_pct = budget.get("used_pct")
    if used_pct is None and budget.get("max"):
        used_pct = round(budget.get("used", 0) / budget["max"] * 100, 1)
    if used_pct and used_pct > 110:
        budget_axis = _axis_label("예산", locale)
        issues.append(Issue(axis=budget_axis, text=_issue_sentence(budget_axis, f"{used_pct}%", [], locale=locale),
                            tool_result=f"{used_pct}%", judge="초과", penalty=15))
        penalty += 15

    # 회색축 = 이 경로에서 실제로 검사하지 못한 것. 화면 caveats 에 "<축> 근거는 확인되지 않았습니다" 로 나간다.
    # (전에는 "리뷰 진위 (담당 팀원)" 같은 내부 자리표시가 그대로 사용자에게 나갔다)
    if locale == "en-US":
        gray = ["manual/spec evidence (RAG not connected)",
                "detailed compatibility check (socket/power/size are approximations)"]
    else:
        gray = ["설명서·규격(RAG 미연결)",
                "호환성 정밀 검사(소켓·전력·크기는 근사값)"]
    confidence = max(0, 100 - penalty)
    passed = confidence >= CONFIDENCE_THRESHOLD
    log(f"      신뢰도 {confidence} · 회색축 {gray} · {'통과' if passed else '기준 미달'}")

    tgt = VerificationTarget(
        subject="Entire build" if locale == "en-US" else "세트 전체",
        issues=issues, gray_axes=gray,
        transcript=[{"round": 1, "issues": [i.model_dump() for i in issues]}],
    )
    return VerificationResult(list_id=build.list_id, category=category, mode="set", targets=[tgt])


def problem_slot(scenario: dict, round_index: int) -> str | None:
    """이번 라운드가 지목한 재탐색 대상 슬롯."""
    rounds = scenario["verify"]["rounds"]
    return rounds[min(round_index, len(rounds) - 1)].get("problem_slot")


def verify_baby_manual(service, request, *, age_months=None, weight_kg=None, independent_sitting=None):
    """Actual manual-backed eligibility path, independent of demo score seeds.

    Returns partial/unknown coverage and cited conditions. Consumers must not
    convert eligibility_status=pass into an overall product safety pass.
    """
    from src.rag.verification import verify_seat
    return verify_seat(service, request, age_months=age_months, weight_kg=weight_kg,
                       independent_sitting=independent_sitting)


_ACTIVE_RECALL_VALUES = {"active_synthetic_recall", "active_recall", "active"}


def _fact(candidate: dict, key: str) -> dict | None:
    return (candidate.get("facts") or {}).get(key)


def _issue(*, rule_key, status, severity, reason, candidate, requirement_id=None,
          measured=None, threshold=None, evidence_ids=None):
    return {
        "schema_version": 1, "rule_key": rule_key, "rule_version": "v1",
        "target": {
            "candidate_id": candidate.get("candidate_id"),
            "requirement_id": requirement_id or candidate.get("requirement_id"),
            "item_id": None,
        },
        "status": status, "severity": severity,
        "measured": measured or {}, "threshold": threshold or {},
        "reason": reason, "penalty": None,
        "evidence_ids": list(evidence_ids or []),
    }


def _recall_issue(candidate: dict):
    """Recall check — 'exact active recall' RULE/POLICY row: hard fail, never overridable."""
    fact = _fact(candidate, "recall_status")
    if fact and fact.get("verification_status") == "verified" and fact.get("value") in _ACTIVE_RECALL_VALUES:
        return _issue(rule_key="baby_recall_v1", status="fail", severity="critical",
                      reason="active_recall", candidate=candidate,
                      measured={"recall_status": fact.get("value")})
    return None


def _certification_issue(candidate: dict):
    """Missing/unverified required certificate — RULE/POLICY row: unknown, no auto selection."""
    fact = _fact(candidate, "kc_certification_number")
    if (candidate.get("slot_key") == "car_seat" and not fact) or (fact is not None and (fact.get("verification_status") != "verified" or not fact.get("value"))):
        return _issue(rule_key="baby_certification_v1", status="unknown", severity="critical",
                      reason="missing_certificate", candidate=candidate,
                      measured={"kc_certification_number": (fact or {}).get("value")})
    return None


def verify_baby_candidate(service, candidate: dict, conditions: dict, run_context: dict):
    """[3-C baby] Per-candidate eligibility — CONTRACTS P3 boundary function.

    candidate: BabyCandidate-shaped dict (candidate_id, requirement_id, product_key,
    variant_key, slot_key, market, language, corpus, facts). conditions: P1's
    normalize_baby_conditions() output. run_context: {"recommendation_run_id": ...}.

    Combines fact-based rules (recall/certification, apply regardless of category)
    with the manual-backed rule inventory (src.rag.verification.MANUAL_RULE_INVENTORY).
    A category with no reviewed rule at all resolves to unknown, never a silent pass.
    """
    from src.dto import CandidateCheck
    from src.rag.contracts import SearchRequest
    from src.rag.verification import MANUAL_RULE_INVENTORY, REVIEWED_NOT_APPLICABLE

    candidate_id = candidate.get("candidate_id", "")
    issues: list[dict] = []
    manual_evidence: list[dict] = []
    error_code: str | None = None
    coverage = "none"
    verification_status = "unknown"

    recall = _recall_issue(candidate)
    if recall:
        issues.append(recall)
    cert = _certification_issue(candidate)
    if cert:
        issues.append(cert)

    slot_key = candidate.get("slot_key")
    manual_eligibility: str | None = None
    if slot_key in MANUAL_RULE_INVENTORY:
        product_key, variant_key = candidate.get("product_key"), candidate.get("variant_key")
        if not product_key or not variant_key:
            manual_eligibility = "unknown"
            issues.append(_issue(rule_key=MANUAL_RULE_INVENTORY[slot_key], status="unknown",
                                 severity="critical", reason="missing_catalog_identifier",
                                 candidate=candidate))
        else:
            age_stage = conditions.get("age_stage") or {}
            context = {
                "age_months": age_stage.get("months") if age_stage.get("exact") else None,
                "weight_kg": conditions.get("weight_kg"),
                "independent_sitting": conditions.get("independent_sitting"),
            }
            request = SearchRequest(
                domain="baby", product_key=product_key, variant_key=variant_key,
                query="유아 안전 조건 검증", market=candidate.get("market", "KR"),
                language=candidate.get("language", "ko"), corpus=candidate.get("corpus", "real"),
                purpose="validation", recommendation_run_id=run_context.get("recommendation_run_id"),
                context={k: v for k, v in context.items() if v is not None},
            )
            verified = verify_baby_manual(service, request, **context)
            if verified.get("search_status") == "error":
                error_code = verified.get("error_code") or "retrieval_error"
                manual_eligibility = "unknown"
                coverage = "error"
                issues.append(_issue(rule_key=MANUAL_RULE_INVENTORY[slot_key], status="unknown",
                                     severity="critical", reason=error_code, candidate=candidate,
                                     measured=context))
            else:
                manual_eligibility = verified.get("eligibility_status", "unknown")
                verification_status = verified.get("verification_status", "unknown")
                manual_evidence = verified.get("evidence", [])
                coverage = "partial" if manual_evidence else "none"
                if manual_eligibility != "pass":
                    issues.append(_issue(
                        rule_key=MANUAL_RULE_INVENTORY[slot_key], status=manual_eligibility,
                        severity="critical", reason=verified.get("reason") or "manual_rule_not_satisfied",
                        candidate=candidate, measured=context,
                        evidence_ids=[h["evidence_id"] for h in manual_evidence],
                    ))
                else:
                    issues.append(_issue(
                        rule_key=MANUAL_RULE_INVENTORY[slot_key], status="pass", severity="info",
                        reason="documented_conditions_met", candidate=candidate, measured=context,
                        evidence_ids=[h["evidence_id"] for h in manual_evidence],
                    ))
    elif slot_key in REVIEWED_NOT_APPLICABLE:
        manual_eligibility = "pass"
        issues.append(_issue(rule_key="baby_rule_inventory_v1", status="pass", severity="info",
                             reason=REVIEWED_NOT_APPLICABLE[slot_key], candidate=candidate))
    else:
        manual_eligibility = "unknown"
        issues.append(_issue(rule_key="baby_rule_inventory_v1", status="unknown", severity="warning",
                             reason="no_reviewed_rule_for_category", candidate=candidate,
                             measured={"slot_key": slot_key}))

    statuses = [recall["status"] if recall else None, cert["status"] if cert else None, manual_eligibility]
    statuses = [s for s in statuses if s is not None]
    eligibility = (
        "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    )
    selection_allowed = eligibility == "pass"
    if verification_status == "unknown" and manual_evidence:
        verification_status = "partial"

    return CandidateCheck(
        candidate_id=candidate_id,
        requirement_id=candidate.get("requirement_id"),
        eligibility=eligibility,
        verification=verification_status,
        coverage=coverage,
        selection_allowed=selection_allowed,
        issues=issues,
        explanation_evidence=manual_evidence,
        error_code=error_code,
    )
