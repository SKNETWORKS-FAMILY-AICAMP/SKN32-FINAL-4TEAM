"""[5] 설명 생성.

(a) 속성 기여도 — 계산(LLM 아님). [3-B] breakdown 을 세트 단위로 집계 → 3축(가격/성능/호환성).
(b) 문장 — LLM structured output 1회. 수치·부품명·통과여부는 코드가 확정, LLM 은 서술만.
    실패 시 규칙 템플릿 fallback.
"""
from __future__ import annotations

from src.dto import BuildResult, Explanation, ExplanationItem, VerificationResult
from src.engine import LogFn

_AXIS_MAP = {"가격": "가격", "성능": "성능", "밸런스": "호환성", "호환여유": "호환성"}


def explain_manual(service, request):
    """Actual source-only explanation; does not invent a procedure or safety score."""
    from dataclasses import replace
    return service.answer(replace(request, purpose="recommendation"))


def _contribution(build: BuildResult) -> dict[str, int]:
    # TODO: RankResult 의 slot별 breakdown 을 전달받아
    #   contribution[축] = Σ(slot_weight · breakdown[축]) / total 로 집계.
    #   현재는 데모 고정값 (목업 A5: 가격 41 / 성능 33 / 호환성 26).
    acc = {"가격": 41.0, "성능": 33.0, "호환성": 26.0}
    total = sum(acc.values()) or 1
    return {k: round(v / total * 100) for k, v in acc.items()}


def run(build: BuildResult, verification: VerificationResult, log: LogFn) -> Explanation:
    log("[5] 설명 생성 ...")
    contrib = _contribution(build)
    tgt = verification.targets[0] if verification.targets else None
    gray = tgt.gray_axes if tgt else []
    conf = tgt.confidence if tgt else 0

    items = [
        ExplanationItem(
            slot=it.slot,
            reason=f"{it.name} — 조건 충족, {it.rank_from_3b}순위, {it.price:,}원",
            basis=[f"rank{it.rank_from_3b}"],
        )
        for it in build.items
    ]
    caveats = [f"{a} 근거는 확인되지 않았습니다" for a in gray]
    headline = (
        f"예산 {build.budget.get('max', 0):,}원 중 {build.totals.get('price', 0):,}원 사용, "
        f"세트 검증 신뢰도 {conf}점"
        + ("." if not gray else f" (회색축 {len(gray)}개).")
    )
    log(f"      기여도: 가격 {contrib['가격']}% / 성능 {contrib['성능']}% / 호환성 {contrib['호환성']}%")
    log(f"      headline: {headline}")

    return Explanation(
        list_id=build.list_id,
        headline=headline,
        contribution=contrib,
        items=items,
        caveats=caveats,
    )
