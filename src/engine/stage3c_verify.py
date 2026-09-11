"""[3-C] 적대적 검증 — 검사AI ↔ 변호인AI + judge(규칙) + RAG.

컴퓨터: 완성 세트 1건을 대상. 유아: 품목별.
신뢰도 = 100 − Σ(쟁점 감점). CONFIDENCE_THRESHOLD 미만이면 재탐색.

데모 = 시나리오별 정답값 주입 (기획서 §10-9 B안):
  - tool 결과·신뢰도·회색축·문제 슬롯을 scenario["verify"]["rounds"][i] 에서 그대로.
  - 논증 텍스트만 LLM 으로 실제 생성 (MOCK_MODE 면 목 문장).
  - VerificationResult 스키마 / judge 집계 규칙 / evidence_search 계약은 실제 것 유지 → drop-in.
"""
from __future__ import annotations

from src.clients.llm_client import call_llm
from src.config import CONFIDENCE_THRESHOLD
from src.dto import BuildResult, Issue, VerificationResult, VerificationTarget
from src.engine import LogFn
from src.rag.evidence_search import evidence_search


def _debate_lines(axis: str, domain: str) -> tuple[str, str, list[dict]]:
    """논증 텍스트 생성 (실제 LLM 자리). + RAG 근거 조회."""
    ev = evidence_search(domain, f"{axis} 조합 이슈", filters={"axis": axis})
    pros = call_llm(f"axis={axis} 공격", system="검사AI")["text"]
    deff = call_llm(f"axis={axis} 반박", system="변호인AI")["text"]
    return pros, deff, ev


def verify_set(build: BuildResult, scenario: dict, round_index: int, log: LogFn) -> VerificationResult:
    """세트 검증 1라운드. 정답값은 scenario['verify']['rounds'][round_index]."""
    log(f"[3-C] 세트 검증 (검사AI ↔ 변호인AI + judge 규칙) ... (라운드 {round_index + 1})")
    vspec = scenario["verify"]
    rounds = vspec["rounds"]
    rspec = rounds[min(round_index, len(rounds) - 1)]
    domain = scenario["category"]

    log(f"      [MOCK] 시나리오 정답값 주입: {scenario['scenario']}  라운드 {round_index + 1}/{len(rounds)}")

    issues: list[Issue] = []
    for iss in rspec.get("issues", []):
        pros, deff, ev = _debate_lines(iss["axis"], domain)
        issues.append(Issue(
            axis=iss["axis"],
            prosecutor=iss.get("prosecutor") or pros,
            defender=iss.get("defender") or deff,
            tool_result=iss.get("tool_result", ""),
            evidence=ev,
            judge=iss.get("judge", ""),
            penalty=int(iss.get("penalty", 0)),
        ))

    confidence = int(rspec["confidence"])           # judge 집계 결과 (데모는 주입값)
    passed = confidence >= CONFIDENCE_THRESHOLD
    gray = list(rspec.get("gray_axes", []))

    for iss in issues:
        log(f"      · {iss.axis}: 감점 {iss.penalty}  ({iss.judge})  근거 {len(iss.evidence)}건")
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
