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
from src.engine.prompts import VERIFY_ISSUE_SYSTEM
from src.rag.evidence_search import evidence_search

# 이 문장은 서술만 한다 — 판정이 섞이면 규칙이 정한 judge 와 화면에서 어긋난다.
_BANNED_VERDICT_WORDS = ("위반", "불합격", "부적합", "적합", "통과", "안전합니다", "위험합니다")


def _rule_sentence(axis: str, tool_result: str) -> str:
    """LLM 없이 쓰는 기본 문장. 관측값만 옮기고 해석하지 않는다."""
    if tool_result:
        return f"{axis}: 관측값 {tool_result}"
    return f"{axis}: 관측값이 기록되지 않았습니다"


def _issue_sentence(axis: str, tool_result: str, evidence: list[dict]) -> str:
    """쟁점 1건을 중립 문장으로.

    판정어가 섞이면 1회 재생성하고, 그래도 섞이거나 호출이 실패하면 규칙 템플릿으로
    내려간다. 문장화 실패는 신뢰도 점수에 영향을 주지 않는다 (기획서 §10-11 E4).
    """
    snippets = "\n".join(f"- {e.get('text', '')}" for e in evidence) or "- (없음)"
    prompt = f"축: {axis}\n관측값: {tool_result or '(기록 없음)'}\n근거:\n{snippets}"
    for _attempt in range(2):
        try:
            text = (call_llm(prompt, system=VERIFY_ISSUE_SYSTEM).get("text") or "").strip()
        except Exception:
            break
        if text and not any(w in text for w in _BANNED_VERDICT_WORDS):
            return text
    return _rule_sentence(axis, tool_result)


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


def verify_build(build: BuildResult, category: str, log: LogFn = lambda _m: None) -> VerificationResult:
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
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, []),
                                tool_result=state, judge="위반", penalty=20))
            penalty += 20
        elif "pending" in s or "근사" in s:
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, []),
                                tool_result=state, judge="확인 필요", penalty=6))
            penalty += 6

    budget = build.budget or {}
    used_pct = budget.get("used_pct")
    if used_pct is None and budget.get("max"):
        used_pct = round(budget.get("used", 0) / budget["max"] * 100, 1)
    if used_pct and used_pct > 110:
        issues.append(Issue(axis="예산", text=_issue_sentence("예산", f"{used_pct}%", []),
                            tool_result=f"{used_pct}%", judge="초과", penalty=15))
        penalty += 15

    # 회색축 = 이 경로에서 실제로 검사하지 못한 것. 화면 caveats 에 "<축> 근거는 확인되지 않았습니다" 로 나간다.
    # (전에는 "리뷰 진위 (담당 팀원)" 같은 내부 자리표시가 그대로 사용자에게 나갔다)
    gray = ["설명서·규격(RAG 미연결)", "호환성 정밀 검사(소켓·전력·크기는 근사값)"]
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
