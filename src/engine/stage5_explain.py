"""[5] 설명 생성.

(a) 속성 기여도 — 계산(LLM 아님). [3-B] breakdown 을 세트 단위로 집계 → 3축(가격/성능/호환성).
(b) 문장 — LLM structured output 1회. 수치·부품명·통과여부는 코드가 확정, LLM 은 서술만.
    실패 시 규칙 템플릿 fallback.
(c) 리뷰 관측 — [3-B] 가 후보에 남긴 REVIEW_OBS flags 를 슬롯별 한 줄(review_line_by_slot)과
    근거 문장(items[].evidence)으로. 점수가 아니라 관측이고 개별 리뷰의 진위가 아니다.
    대조군 중앙값을 넘은 것은 "주의" 로도 올린다 — 검토자가 반박할 수 있게 확인 경로를 같이 준다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.clients.llm_client import call_llm
from src.dto import (BuildResult, Explanation, ExplanationDraft, ExplanationItem, RankResult,
                     VerificationResult)
from src.engine import LogFn
from src.engine.prompts import explain_system
from src.repo.review_repo import (OBS_LABEL, default_risk_store, default_suspect_counts,
                                 is_obs_flag, parse_obs_flag, risk_store_note)

if TYPE_CHECKING:
    from src.i18n import Locale

_AXIS_MAP = {"가격": "가격", "성능": "성능", "밸런스": "호환성", "호환여유": "호환성"}
_EN_LABELS = {
    "가격": "price",
    "성능": "performance",
    "밸런스": "balance",
    "호환성": "compatibility",
    "호환여유": "compatibility headroom",
    "예산": "budget",
    "리뷰 진위 (담당 팀원)": "review authenticity",
    "RAG 근거 (담당 팀원)": "RAG evidence",
    "메인보드": "Motherboard",
    "저장장치": "Storage",
    "파워": "Power supply",
    "케이스": "Case",
    "쿨러": "Cooler",
}
_OBS_LABEL_EN = {
    "burst7": "7-day concentration",
    "one_off_rate": "single-review account rate",
    "prolific_rate": "prolific reviewer rate",
}

# 앞 넷: 지시문 문구가 결과에 들어오면 모델이 프롬프트를 베낀 것이다 — 실제로 한 번 그랬다.
# 마지막 여섯: 평가·마케팅 표현 — 규칙 7 위반(실호출에서 "강력한 성능"처럼 새나온 적 있다).
_BANNED_IN_DRAFT = (
    "1~2문장", "문장 한두 개", "슬롯마다", "지시문",
    "강력", "뛰어나", "최고", "압도적", "완벽", "훌륭",
    "powerful", "excellent", "best", "perfect", "outstanding", "unmatched",
)


def _ranked_flags(rank: RankResult | None, slot: str, product_key: str) -> list[str]:
    if rank is None:
        return []
    for c in rank.slots.get(slot, {}).get("ranked", []):
        if c.get("product_key") == product_key:
            return [f for f in c.get("flags", []) if is_obs_flag(f)]
    return []


def _english_label(value: str) -> str:
    return _EN_LABELS.get(value, value)


def _risk_store_note_en(note: str) -> str:
    if note == "리뷰 수 문턱 미만이거나 데이터 기간 밖":
        return "below the review-count threshold or outside the data period"
    if note.startswith("산출물 미탑재 — "):
        return "risk artifact unavailable — " + note.split(" — ", 1)[1]
    if note.startswith("대조군 범위 불일치 — "):
        return "comparison-group scope mismatch — " + note.split(" — ", 1)[1]
    if note.startswith("산출물을 읽지 못함 — "):
        return "could not read the risk artifact — " + note.split(" — ", 1)[1]
    return note


def _review_line(
    product_key: str,
    flags: list[str],
    *,
    locale: Locale = "ko-KR",
) -> tuple[str, list[dict], str | None]:
    """(슬롯 한 줄, 근거 목록, 주의 문장 또는 None). flags 가 없으면 관측 없음."""
    if not flags:
        # 왜 없는지를 원인별로 말한다 — 산출물 미탑재를 "문턱 미만" 으로 보이게 하면
        # 파일을 안 받은 사람이 그 사실을 모른다
        if locale == "en-US":
            return f"No review observations ({_risk_store_note_en(risk_store_note())})", [], None
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
        if locale == "en-US":
            return f"Observed {n} reviews — no values above the comparison-group median", evidence, None
        return f"리뷰 {n}건 관측 — 대조군 중앙값 대비 특이 없음", evidence, None
    if locale == "en-US":
        parts = [
            f"{_OBS_LABEL_EN.get(k, k)} {100 * v:.1f}% "
            f"(comparison-group median {100 * m:.1f}%)"
            for k, v, m in over
        ]
        line = f"Observed {n} reviews — " + " · ".join(parts) + " — review recommended"
        labels = ", ".join(_OBS_LABEL_EN.get(k, k) for k, _, _ in over)
        caveat = (
            f"Review observations ({labels}) are product-level signals, not judgments "
            "about individual review authenticity."
        )
        return line, evidence, caveat
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


def _top_axes(rank: RankResult | None, slot: str, product_key: str) -> str:
    """그 후보에서 기여가 큰 축 둘 — 이유 문장의 방향 힌트 (기획서 §11-3)."""
    if rank is None:
        return ""
    for c in rank.slots.get(slot, {}).get("ranked", []):
        if c.get("product_key") == product_key:
            bd = c.get("breakdown") or {}
            top = sorted(bd.items(), key=lambda kv: kv[1], reverse=True)[:2]
            return ", ".join(k for k, _ in top)
    return ""


def _llm_draft(build: BuildResult, verification: VerificationResult,
               rank: RankResult | None, log: LogFn, *,
               locale: Locale = "ko-KR") -> ExplanationDraft | None:
    """문장 초안 1회 생성. 검사를 통과한 것만 돌려주고 아니면 None → 규칙 템플릿 (§11-6).

    수치·부품명·통과여부는 아래 입력으로 확정해 준다. LLM 이 슬롯을 바꾸거나 다른 슬롯의
    부품을 끌어오거나 점수를 만들어내면 버린다 — 그 경우 호출자가 기존 규칙 문장을 쓴다.
    """
    tgt = verification.targets[0] if verification.targets else None
    lines = [
        f"예산 상한: {build.budget.get('max', 0)}원",
        f"사용 금액: {build.totals.get('price', 0)}원",
        f"검증 신뢰도: {tgt.confidence if tgt else '없음'} (통과: {tgt.passed if tgt else '없음'})",
        f"근거가 확인되지 않은 축: {(tgt.gray_axes if tgt else []) or '없음'}",
        "구성:",
    ]
    for it in build.items:
        axes = _top_axes(rank, it.slot, it.product_key)
        lines.append(f"- {it.slot} | {it.name} | {it.price}원 | {it.rank_from_3b}순위"
                     + (f" | 기여가 큰 축: {axes}" if axes else ""))
    if tgt and tgt.issues:
        lines.append("검증 쟁점:")
        lines += [f"- {i.axis}: {i.text or i.tool_result}" for i in tgt.issues]

    want = {it.slot for it in build.items}
    names = {it.slot: it.name for it in build.items}
    schema = ExplanationDraft.model_json_schema()
    for _attempt in range(2):
        try:
            draft = ExplanationDraft.model_validate(
                call_llm("\n".join(lines), system=explain_system(locale), output_schema=schema))
        except Exception as exc:
            log(f"      [5] 문장 생성 실패 ({type(exc).__name__}) → 규칙 템플릿")
            return None
        if {i.slot for i in draft.items} != want:
            continue
        draft_text = draft.model_dump_json().casefold()
        if any(w.casefold() in draft_text for w in _BANNED_IN_DRAFT):
            continue
        if any(other and other in i.reason
               for i in draft.items
               for slot, other in names.items() if slot != i.slot):
            continue
        if tgt and str(tgt.confidence) not in draft.headline:
            continue  # headline이 검증 신뢰도 숫자를 빠뜨렸다 — 규칙 4 위반
        return draft
    log("      [5] 검사 불통과 → 규칙 템플릿")
    return None


def _fallback_reason(item, locale: Locale) -> str:
    if locale == "en-US":
        return (f"{item.name} — meets the requirements, ranked #{item.rank_from_3b}, "
                f"₩{item.price:,}")
    return f"{item.name} — 조건 충족, {item.rank_from_3b}순위, {item.price:,}원"


def _gray_axis_caveat(axis: str, locale: Locale) -> str:
    if locale == "en-US":
        return f"Evidence for {_english_label(axis)} could not be verified."
    return f"{axis} 근거는 확인되지 않았습니다"


def _fallback_headline(build: BuildResult, confidence: int, gray: list[str],
                       locale: Locale) -> str:
    budget = build.budget.get("max", 0)
    used = build.totals.get("price", 0)
    if locale == "en-US":
        gap_label = "evidence gap" if len(gray) == 1 else "evidence gaps"
        suffix = "." if not gray else f" ({len(gray)} {gap_label})."
        return (f"Used ₩{used:,} of the ₩{budget:,} budget; build verification confidence "
                f"is {confidence}/100{suffix}")
    return (f"예산 {budget:,}원 중 {used:,}원 사용, 세트 검증 신뢰도 {confidence}점"
            + ("." if not gray else f" (회색축 {len(gray)}개)."))


def run(build: BuildResult, verification: VerificationResult, log: LogFn,
        rank: RankResult | None = None, *, locale: Locale = "ko-KR") -> Explanation:
    log("[5] 설명 생성 ...")
    contrib = _contribution(build)
    tgt = verification.targets[0] if verification.targets else None
    gray = tgt.gray_axes if tgt else []
    conf = tgt.confidence if tgt else 0

    # 리뷰 관측(review_line_by_slot·evidence)은 규칙이 만든 것을 그대로 둔다 — LLM 은 건드리지 않는다.
    draft = _llm_draft(build, verification, rank, log, locale=locale)
    reason_by_slot = {i.slot: i.reason for i in draft.items} if draft else {}

    items, review_lines, review_caveats = [], {}, []
    for it in build.items:
        line, evidence, caveat = _review_line(
            it.product_key,
            _ranked_flags(rank, it.slot, it.product_key),
            locale=locale,
        )
        review_lines[it.slot] = line
        if caveat:
            slot_label = _english_label(it.slot) if locale == "en-US" else it.slot
            review_caveats.append(f"{slot_label} {caveat}")
        items.append(ExplanationItem(
            slot=it.slot,
            reason=(reason_by_slot.get(it.slot) or _fallback_reason(it, locale)),
            basis=[f"rank{it.rank_from_3b}"],
            evidence=evidence,
        ))
    # caveats 는 규칙이 소유한다 — 회색축과 리뷰 관측 둘 다 코드가 정확히 알고 있어서,
    # LLM 이 같은 내용을 다른 표현으로 또 쓰면 화면에 중복으로 나간다.
    caveats = [_gray_axis_caveat(a, locale) for a in gray] + review_caveats
    headline = (draft.headline if draft and draft.headline
                else _fallback_headline(build, conf, gray, locale))
    log(f"      기여도: 가격 {contrib['가격']}% / 성능 {contrib['성능']}% / 호환성 {contrib['호환성']}%")
    log(f"      문장: {'LLM' if draft else '규칙 템플릿'}")
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
