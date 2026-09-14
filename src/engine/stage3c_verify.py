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

from src.clients.llm_client import call_llm
from src.config import CONFIDENCE_THRESHOLD
from src.dto import BuildResult, Issue, VerificationResult, VerificationTarget
from src.engine import LogFn
from src.engine.lang import L, localize_system
from src.engine.prompts import VERIFY_ISSUE_SYSTEM
from src.rag.evidence_search import evidence_search

# 이 문장은 서술만 한다 — 판정이 섞이면 규칙이 정한 judge 와 화면에서 어긋난다.
_BANNED_VERDICT_WORDS = ("위반", "불합격", "부적합", "적합", "통과", "안전합니다", "위험합니다")


def _rule_sentence(axis: str, tool_result: str, lang: str = "ko") -> str:
    """LLM 없이 쓰는 기본 문장. 관측값만 옮기고 해석하지 않는다."""
    if tool_result:
        return L(lang, f"{axis}: 관측값 {tool_result}", f"{axis}: observed {tool_result}")
    return L(lang, f"{axis}: 관측값이 기록되지 않았습니다", f"{axis}: no observation recorded")


def _issue_sentence(axis: str, tool_result: str, evidence: list[dict], lang: str = "ko") -> str:
    """쟁점 1건을 중립 문장으로.

    판정어가 섞이면 1회 재생성하고, 그래도 섞이거나 호출이 실패하면 규칙 템플릿으로
    내려간다. 문장화 실패는 신뢰도 점수에 영향을 주지 않는다 (기획서 §10-11 E4).
    """
    if lang == "en":
        # stage4 의 link_check 값("ok (근사)")은 엔진 상수다 — 영어 문장에 한국어 토막이 섞이지 않게 입력에서만 바꾼다
        tool_result = (tool_result or "").replace("근사", "approximate")
    snippets = "\n".join(f"- {e.get('text', '')}" for e in evidence) or "- (없음)"
    prompt = f"축: {axis}\n관측값: {tool_result or '(기록 없음)'}\n근거:\n{snippets}"
    for _attempt in range(2):
        try:
            text = (call_llm(prompt, system=localize_system(VERIFY_ISSUE_SYSTEM, lang)).get("text") or "").strip()
        except Exception:
            break
        if text and not any(w in text for w in _BANNED_VERDICT_WORDS):
            return text
    return _rule_sentence(axis, tool_result, lang)


def verify_set(build: BuildResult, scenario: dict, round_index: int, log: LogFn) -> VerificationResult:
    """세트 검증 1라운드. 정답값은 scenario['verify']['rounds'][round_index]."""
    log(f"[3-C] 세트 검증 (규칙 judge + 쟁점 문장화) ... (라운드 {round_index + 1})")
    vspec = scenario["verify"]
    rounds = vspec["rounds"]
    rspec = rounds[min(round_index, len(rounds) - 1)]
    domain = scenario["category"]

    log(f"      [MOCK] 시나리오 정답값 주입: {scenario['scenario']}  라운드 {round_index + 1}/{len(rounds)}")

    issues: list[Issue] = []
    for iss in rspec.get("issues", []):
        axis = iss["axis"]
        tool_result = iss.get("tool_result", "")
        ev = evidence_search(domain, f"{axis} 조합 이슈", filters={"axis": axis})
        issues.append(Issue(
            axis=axis,
            text=_issue_sentence(axis, tool_result, ev),
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


def verify_build(build: BuildResult, category: str, log: LogFn = lambda _m: None, lang: str = "ko") -> VerificationResult:
    """DB 경로([추천 실행])의 세트 검증 — 규칙 judge + 쟁점 문장화.

    RAG 근거 연결은 담당 팀원 자리라 여기서는 근거 없이 관측값만으로 문장을 만든다.
    link_check/예산 기반 규칙으로 confidence 를 낸다.
    """
    log("[3-C] 세트 검증 (규칙 스캐폴드) ...")
    issues: list[Issue] = []
    penalty = 0
    for axis, state in (build.link_check or {}).items():
        s = str(state).lower()
        if "fail" in s or "미충족" in s or "over" in s:
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, [], lang),
                                tool_result=state, judge="위반", penalty=20))
            penalty += 20
        elif "pending" in s or "근사" in s:
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, [], lang),
                                tool_result=state, judge="확인 필요", penalty=6))
            penalty += 6

    budget = build.budget or {}
    used_pct = budget.get("used_pct")
    if used_pct is None and budget.get("max"):
        used_pct = round(budget.get("used", 0) / budget["max"] * 100, 1)
    if used_pct and used_pct > 110:
        issues.append(Issue(axis="예산", text=_issue_sentence("예산", f"{used_pct}%", [], lang),
                            tool_result=f"{used_pct}%", judge="초과", penalty=15))
        penalty += 15

    # 회색축 = 이 경로에서 실제로 검사하지 못한 것. 화면 caveats 에 "<축> 근거는 확인되지 않았습니다" 로 나간다.
    # (전에는 "리뷰 진위 (담당 팀원)" 같은 내부 자리표시가 그대로 사용자에게 나갔다)
    gray = [L(lang, "설명서·규격(RAG 미연결)", "manual/spec evidence (RAG not connected)"),
            L(lang, "호환성 정밀 검사(소켓·전력·크기는 근사값)", "detailed compatibility check (socket/power/size are approximations)")]
    confidence = max(0, 100 - penalty)
    passed = confidence >= CONFIDENCE_THRESHOLD
    log(f"      신뢰도 {confidence} · 회색축 {gray} · {'통과' if passed else '기준 미달'}")

    tgt = VerificationTarget(
        subject="세트 전체", confidence=confidence, passed=passed, rounds=1,
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


def _issue(*, rule_key, status, severity, reason, candidate, requirement_id=None,
          measured=None, threshold=None, evidence_refs=None):
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
        "evidence_refs": list(evidence_refs or []),
    }


def verify_baby_candidate(service, candidate: dict, conditions: dict, run_context: dict):
    """[3-C baby] Per-candidate eligibility — P3 full-catalog verification (2026-09-14).

    candidate: BabyCandidate-shaped dict (candidate_id, requirement_id, product_key,
    variant_key, slot_key, market, language, corpus). conditions: P1's
    normalize_baby_conditions() output. run_context: {"recommendation_run_id": ...}.
    `service` is a src.rag.service.RagService — its `.material_repo.conn` is reused
    to read catalog.product_fact/evidence.evidence (docs/agent-tasks/baby/
    P3_full_catalog_verification_execution.md — replaces the old candidate["facts"]
    embedded-JSON shortcut and the stroller-only MANUAL_RULE_INVENTORY special case
    with one rule-registry-driven path for all 15 slots).

    Order (matches the P3 doc's verify_baby_candidate() step list):
      1. resolve a verification rule for (slot_key, scope) — scope is derived from
         candidate.corpus (synthetic -> synthetic_demo, real -> production).
      2. resolve product/variant identity and look up this candidate's verified
         product_fact rows, scoped to that same scope.
      3. re-check the manufacturer_document claim's publication status if it cites
         a material_revision (a since-revoked/unpublished document no longer counts).
      4. recall_status: any "active*" verified value is an unconditional fail.
      5. required_claims completeness: any missing verified claim is unknown.
      6. the condition layer (age/weight/independent_sitting) — implemented only for
         CONDITION_CHECKED_SLOTS (stroller today), reusing verify_seat's real
         manual-text retrieval; other slots have no condition claims to check.
      7. all required checks passed -> eligibility=pass, selection_allowed=True.
    """
    from uuid import UUID

    from src.dto import CandidateCheck
    from src.rag.verification import CONDITION_CHECKED_SLOTS, find_verification_rule, load_baby_verification_rules
    from src.repo.product_repo import ProductRepo

    candidate_id = candidate.get("candidate_id", "")
    requirement_id = candidate.get("requirement_id")
    slot_key = candidate.get("slot_key")
    corpus = candidate.get("corpus", "real")
    scope = "synthetic_demo" if corpus == "synthetic" else "production"

    def _unknown(reason, *, rule_key="baby_rule_inventory_v1", severity="critical",
                measured=None, evidence_refs=None, error_code=None):
        return CandidateCheck(
            candidate_id=candidate_id, requirement_id=requirement_id, eligibility="unknown",
            verification="unknown", coverage="none", selection_allowed=False,
            issues=[_issue(rule_key=rule_key, status="unknown", severity=severity, reason=reason,
                           candidate=candidate, measured=measured or {}, evidence_refs=evidence_refs or [])],
            explanation_evidence=[], error_code=error_code,
        )

    def _fail(reason, rule_key, *, measured=None, evidence_refs=None):
        return CandidateCheck(
            candidate_id=candidate_id, requirement_id=requirement_id, eligibility="fail",
            verification="partial", coverage="partial", selection_allowed=False,
            issues=[_issue(rule_key=rule_key, status="fail", severity="critical", reason=reason,
                           candidate=candidate, measured=measured or {}, evidence_refs=evidence_refs or [])],
            explanation_evidence=[], error_code=None,
        )

    # step 1
    rules = load_baby_verification_rules()
    rule = find_verification_rule(rules, slot_key, scope)
    if rule is None:
        reason = "scope_mismatch" if slot_key in rules else "no_reviewed_rule_for_category"
        return _unknown(reason, severity="warning", measured={"slot_key": slot_key, "scope": scope})

    product_key, variant_key = candidate.get("product_key"), candidate.get("variant_key")
    if not product_key or not variant_key:
        return _unknown("missing_product_identity", rule_key=rule["rule_id"])

    # step 2
    product_repo = ProductRepo(service.material_repo.conn)
    resolved = product_repo.resolve_ids(product_key, variant_key, corpus=corpus)
    if resolved is None:
        return _unknown("missing_product_identity", rule_key=rule["rule_id"])
    product_id, variant_id = resolved
    try:
        facts = product_repo.verified_facts(product_id, variant_id, scope=scope)
    except Exception:
        return _unknown("evidence_provider_failed", rule_key=rule["rule_id"])

    if "product_identity" not in facts:
        return _unknown("missing_product_identity", rule_key=rule["rule_id"])

    # step 3 — a manufacturer_document claim backed by a material_revision must
    # still be published/active/available; treat a revoked/unpublished one as
    # absent. Deliberately NOT MaterialRepo.is_currently_published() — that also
    # requires access_scope='public' + use_policy.allow_rag, which are RAG
    # chunk-search gates (only meaningful for CONDITION_CHECKED_SLOTS' full
    # ingest_manual path); a plain document-exists re-check must not fail just
    # because a slot was never chunk-indexed for search.
    doc_fact = facts.get("manufacturer_document")
    if doc_fact is not None:
        revision_id = (doc_fact.get("citation_snapshot") or {}).get("material_revision_id")
        if revision_id:
            revision = service.material_repo.get_revision(UUID(revision_id))
            still_valid = (
                revision is not None and revision["revision_status"] == "published"
                and revision["material_status"] == "active" and revision["storage_status"] == "available"
            )
            if not still_valid:
                del facts["manufacturer_document"]

    # step 4
    recall_fact = facts.get("recall_status")
    if recall_fact is not None:
        recall_value = (recall_fact.get("value") or {}).get("status", "")
        if str(recall_value).startswith("active"):
            return _fail("active_recall", rule["rule_id"], measured={"recall_status": recall_value},
                        evidence_refs=[str(recall_fact["evidence_id"])])

    # step 5
    missing_claims = [c for c in rule["required_claims"] if c not in facts]
    if missing_claims:
        return _unknown("missing_rule_evidence", rule_key=rule["rule_id"],
                        measured={"missing_claims": missing_claims})

    evidence_refs = [str(f["evidence_id"]) for f in facts.values()]

    # step 6 — condition layer (stroller only; see CONDITION_CHECKED_SLOTS docstring)
    manual_evidence: list[dict] = []
    verification_status = "verified" if scope == "production" else "partial"
    if rule["optional_condition_claims"] and slot_key in CONDITION_CHECKED_SLOTS:
        from src.rag.contracts import SearchRequest

        age_stage = conditions.get("age_stage") or {}
        context = {
            "age_months": age_stage.get("months") if age_stage.get("exact") else None,
            "weight_kg": conditions.get("weight_kg"),
            "independent_sitting": conditions.get("independent_sitting"),
        }
        if all(v is None for v in context.values()):
            return _unknown("missing_verification_input", rule_key=rule["rule_id"])
        request = SearchRequest(
            domain="baby", product_key=product_key, variant_key=variant_key,
            query="유아 안전 조건 검증", market=candidate.get("market", "KR"),
            language=candidate.get("language", "ko"), corpus=corpus, purpose="validation",
            recommendation_run_id=run_context.get("recommendation_run_id"),
            context={k: v for k, v in context.items() if v is not None},
        )
        verified = verify_baby_manual(service, request, **context)
        if verified.get("search_status") == "error":
            return _unknown(verified.get("error_code") or "evidence_provider_unavailable",
                            rule_key=rule["rule_id"], measured=context)
        manual_evidence = verified.get("evidence", [])
        evidence_refs += [h["evidence_id"] for h in manual_evidence]
        condition_eligibility = verified.get("eligibility_status", "unknown")
        if manual_evidence:
            verification_status = "partial"
        if condition_eligibility == "fail":
            return _fail("condition_out_of_range", rule["rule_id"], measured=context, evidence_refs=evidence_refs)
        if condition_eligibility != "pass":
            return _unknown(verified.get("reason") or "missing_verification_input",
                            rule_key=rule["rule_id"], measured=context, evidence_refs=evidence_refs)

    # step 7
    return CandidateCheck(
        candidate_id=candidate_id, requirement_id=requirement_id, eligibility="pass",
        verification=verification_status, coverage="full", selection_allowed=True,
        issues=[_issue(rule_key=rule["rule_id"], status="pass", severity="info",
                       reason="all_required_claims_verified", candidate=candidate,
                       evidence_refs=evidence_refs)],
        explanation_evidence=manual_evidence, error_code=None,
    )
