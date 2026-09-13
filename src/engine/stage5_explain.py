"""[5] 설명 생성.

(a) 속성 기여도 — 계산(LLM 아님). [3-B] breakdown 을 세트 단위로 집계 → 3축(가격/성능/호환성).
(b) 문장 — LLM structured output 1회. 수치·부품명·통과여부는 코드가 확정, LLM 은 서술만.
    실패 시 규칙 템플릿 fallback.
(c) 리뷰 관측 — [3-B] 가 후보에 남긴 REVIEW_OBS flags 를 슬롯별 한 줄(review_line_by_slot)과
    근거 문장(items[].evidence)으로. 점수가 아니라 관측이고 개별 리뷰의 진위가 아니다.
    대조군 중앙값을 넘은 것은 "주의" 로도 올린다 — 검토자가 반박할 수 있게 확인 경로를 같이 준다.
"""
from __future__ import annotations

from src.dto import BuildResult, Explanation, ExplanationItem, RankResult, VerificationResult
from src.engine import LogFn
from src.repo.review_repo import (OBS_LABEL, default_risk_store, default_suspect_counts,
                                 is_obs_flag, parse_obs_flag, risk_store_note)

_AXIS_MAP = {"가격": "가격", "성능": "성능", "밸런스": "호환성", "호환여유": "호환성"}


def _ranked_flags(rank: RankResult | None, slot: str, product_key: str) -> list[str]:
    if rank is None:
        return []
    for c in rank.slots.get(slot, {}).get("ranked", []):
        if c.get("product_key") == product_key:
            return [f for f in c.get("flags", []) if is_obs_flag(f)]
    return []


def _review_line(product_key: str, flags: list[str]) -> tuple[str, list[dict], str | None]:
    """(슬롯 한 줄, 근거 목록, 주의 문장 또는 None). flags 가 없으면 관측 없음."""
    if not flags:
        # 왜 없는지를 원인별로 말한다 — 산출물 미탑재를 "문턱 미만" 으로 보이게 하면
        # 파일을 안 받은 사람이 그 사실을 모른다
        return f"리뷰 관측 없음 ({risk_store_note()})", [], None
    store = default_risk_store()
    facts = store.get(product_key) if store else None
    n = int(facts["n"]) if facts else 0
    over = [p for p in map(parse_obs_flag, flags) if p is not None]
    evidence = []
    if store and facts:
        ref = store.resolve(product_key)
        evidence = [{"kind": "review_observation", "text": t, "verify_url": f"https://www.amazon.com/dp/{ref}"}
                    for t in store.observations(product_key)]
        # 규칙 기반 의심 건수 — kind 를 달리 둬서 관측 사실과 구별한다(정밀도를 못 재는 값이다)
        sus = default_suspect_counts()
        line = sus.sentence(product_key) if sus else None
        if line:
            evidence.append({"kind": "review_suspect_rule", "text": line, "verify_url": None})
    if not over:
        return f"리뷰 {n}건 관측 — 대조군 중앙값 대비 특이 없음", evidence, None
    parts = [f"{OBS_LABEL.get(k, k)} {100 * v:.1f}% (부류 중앙값 {100 * m:.1f}%)" for k, v, m in over]
    line = f"리뷰 {n}건 관측 — " + " · ".join(parts) + " — 검토 권장"
    caveat = (f"리뷰 관측({', '.join(OBS_LABEL.get(k, k) for k, _, _ in over)})은 "
              f"상품 단위 신호이며 개별 리뷰의 진위가 아닙니다")
    return line, evidence, caveat


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


def run(build: BuildResult, verification: VerificationResult, log: LogFn,
        rank: RankResult | None = None) -> Explanation:
    log("[5] 설명 생성 ...")
    contrib = _contribution(build)
    tgt = verification.targets[0] if verification.targets else None
    gray = tgt.gray_axes if tgt else []
    conf = tgt.confidence if tgt else 0

    items, review_lines, review_caveats = [], {}, []
    for it in build.items:
        line, evidence, caveat = _review_line(it.product_key, _ranked_flags(rank, it.slot, it.product_key))
        review_lines[it.slot] = line
        if caveat:
            review_caveats.append(f"{it.slot} {caveat}")
        items.append(ExplanationItem(
            slot=it.slot,
            reason=f"{it.name} — 조건 충족, {it.rank_from_3b}순위, {it.price:,}원",
            basis=[f"rank{it.rank_from_3b}"],
            evidence=evidence,
        ))
    caveats = [f"{a} 근거는 확인되지 않았습니다" for a in gray] + review_caveats
    headline = (
        f"예산 {build.budget.get('max', 0):,}원 중 {build.totals.get('price', 0):,}원 사용, "
        f"세트 검증 신뢰도 {conf}점"
        + ("." if not gray else f" (회색축 {len(gray)}개).")
    )
    log(f"      기여도: 가격 {contrib['가격']}% / 성능 {contrib['성능']}% / 호환성 {contrib['호환성']}%")
    log(f"      headline: {headline}")
    n_obs = sum(1 for l in review_lines.values() if not l.startswith("리뷰 관측 없음"))
    log(f"      리뷰 관측: {n_obs}/{len(review_lines)} 슬롯" + (f", 검토 권장 {len(review_caveats)}" if review_caveats else ""))

    return Explanation(
        list_id=build.list_id,
        headline=headline,
        contribution=contrib,
        items=items,
        caveats=caveats,
        review_line_by_slot=review_lines,
    )
