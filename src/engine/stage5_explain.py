"""[5] 설명 생성.

(a) 속성 기여도 — 계산(LLM 아님). [3-B] breakdown 을 세트 단위로 집계 → 3축(가격/성능/호환성).
(b) 문장 — LLM structured output 1회. 수치·부품명·통과여부는 코드가 확정, LLM 은 서술만.
    실패 시 규칙 템플릿 fallback.
(c) 리뷰 관측 — [3-B] 가 후보에 남긴 REVIEW_OBS flags 를 슬롯별 한 줄(review_line_by_slot)과
    근거 문장(items[].evidence)으로. 점수가 아니라 관측이고 개별 리뷰의 진위가 아니다.
    대조군 중앙값을 넘은 것은 "주의" 로도 올린다 — 검토자가 반박할 수 있게 확인 경로를 같이 준다.
"""
from __future__ import annotations

from src.clients.llm_client import call_llm
from src.dto import (BuildResult, Explanation, ExplanationDraft, ExplanationItem, RankResult,
                     VerificationResult)
from src.engine import LogFn
from src.engine.lang import L, currency_of, fmt_money, lang_of, localize_system
from src.engine.prompts import EXPLAIN_SYSTEM
from src.repo.review_repo import (OBS_LABEL, default_risk_store, default_suspect_counts,
                                 is_obs_flag, parse_obs_flag, risk_store_note)

_AXIS_MAP = {"가격": "가격", "성능": "성능", "밸런스": "호환성", "호환여유": "호환성"}

# 앞 둘: 이 모듈은 점수를 만들지 않는다. 문장에 섞이면 관측이 점수로 읽힌다 (docs/decisions/0001).
# 가운데 넷: 지시문 문구가 결과에 들어오면 모델이 프롬프트를 베낀 것이다 — 실제로 한 번 그랬다.
# 마지막 여섯: 평가·마케팅 표현 — 규칙 7 위반(실호출에서 "강력한 성능"처럼 새나온 적 있다).
# 뒤 셋: summary 실호출에서 "성능을 극대화", "원활하게 구동", "안정성이 확인된" 이 나왔다 — 입력에 없는 성능 주장.
_BANNED_IN_DRAFT = ("score", "점수", "1~2문장", "문장 한두 개", "슬롯마다", "지시문",
                    "강력", "뛰어나", "최고", "압도적", "완벽", "훌륭", "극대화", "원활", "안정성",
                    # 영어 출력(language=en)의 같은 부류
                    "excellent", "powerful", "outstanding", "perfect", "superb", "the best", "maximiz")


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


def explain_baby_candidate(service, candidate: dict, check, run_context: dict):
    """[5 baby] Per-candidate explanation — CONTRACTS P3 boundary function.

    Runs a separate recommendation-purpose RAG query from verify_baby_candidate's
    validation-purpose query; the refs returned here are the ones actually used for
    the user-facing explanation, not a copy of the verification's cited evidence
    (CONTRACTS VE05: verification refs and explanation refs may differ).
    """
    from src.dto import ExplanationWithRefs
    from src.rag.contracts import SearchRequest

    candidate_id = candidate.get("candidate_id", "")
    product_key, variant_key = candidate.get("product_key"), candidate.get("variant_key")
    if not product_key or not variant_key:
        return ExplanationWithRefs(candidate_id=candidate_id, status="failed",
                                   error_code="missing_catalog_identifier")
    request = SearchRequest(
        domain="baby", product_key=product_key, variant_key=variant_key,
        query="제품 사양과 특징 설명", market=candidate.get("market", "KR"),
        language=candidate.get("language", "ko"), corpus=candidate.get("corpus", "real"),
        purpose="recommendation", recommendation_run_id=run_context.get("recommendation_run_id"),
    )
    answer = explain_manual(service, request)
    if answer["status"] == "error":
        return ExplanationWithRefs(candidate_id=candidate_id, status="failed",
                                   error_code=answer.get("error_code"))
    if answer["status"] != "success":
        return ExplanationWithRefs(candidate_id=candidate_id, status="pending",
                                   error_code=answer.get("reason"))
    refs = [{"evidence_id": h["evidence_id"], "locator": h["locator"]} for h in answer.get("hits", [])]
    return ExplanationWithRefs(candidate_id=candidate_id, status="ready",
                               text=answer.get("answer"), refs=refs)


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


def _conditions_lines(conditions: dict | None) -> list[str]:
    """[5] 입력에 싣는 사용자 조건. 엔진이 읽지 않는 extra 는 그렇게 표시해 LLM 이 반영됐다고 쓰지 못하게 한다."""
    if not conditions:
        return []
    labels = {"purpose": "용도", "priority": "우선순위", "games": "게임", "resolution": "해상도",
              "noise_sensitive": "소음 민감", "brand_pref": "브랜드 선호", "assembly": "조립", "mode": "구성 방식",
              "age_months": "아이 개월", "needs": "필요 영역", "health_skin": "건강·피부", "owned_items": "보유 물품"}
    parts = [f"{label} {conditions[k]}" for k, label in labels.items() if conditions.get(k) not in (None, [], "")]
    # extra(자유 조건)는 엔진이 읽지 않는다. LLM 에 보여 주면 "반영됐다"고 쓰는 일이 있어(실호출에서
    # "케이스는 흰색으로 선택할 수 있으며") 입력에서 빼고, 안내 문장은 코드가 summary 뒤에 붙인다(_extra_note).
    return ["사용자 조건: " + (" · ".join(parts) if parts else "(없음)")]


def _extra_note(conditions: dict | None) -> str:
    extra = (conditions or {}).get("extra") or []
    if not extra:
        return ""
    quoted = ", ".join(f"'{e}'" for e in extra)
    return L(lang_of(conditions),
             f" 추가 조건 {quoted}은(는) 자동 구성에 반영되지 않았습니다 — 후보 교체나 아래 대화창에서 직접 확인해 주세요.",
             f" Extra request {quoted} was not applied automatically — check it via alternatives or the chat below.")


def _llm_draft(build: BuildResult, verification: VerificationResult,
               rank: RankResult | None, log: LogFn, conditions: dict | None = None) -> ExplanationDraft | None:
    """문장 초안 1회 생성. 검사를 통과한 것만 돌려주고 아니면 None → 규칙 템플릿 (§11-6).

    수치·부품명·통과여부는 아래 입력으로 확정해 준다. LLM 이 슬롯을 바꾸거나 다른 슬롯의
    부품을 끌어오거나 점수를 만들어내면 버린다 — 그 경우 호출자가 기존 규칙 문장을 쓴다.
    """
    tgt = verification.targets[0] if verification.targets else None
    cur = currency_of(conditions)
    lines = _conditions_lines(conditions) + [
        f"예산 상한: {fmt_money(build.budget.get('max', 0), cur)}",
        f"사용 금액: {fmt_money(build.totals.get('price', 0), cur)}",
        f"검증 신뢰도: {tgt.confidence if tgt else '없음'} (통과: {tgt.passed if tgt else '없음'})",
        f"근거가 확인되지 않은 축: {(tgt.gray_axes if tgt else []) or '없음'}",
        "구성:",
    ]
    for it in build.items:
        axes = _top_axes(rank, it.slot, it.product_key)
        lines.append(f"- {it.slot} | {it.name} | {fmt_money(it.price, cur)} | {it.rank_from_3b}순위"
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
                call_llm("\n".join(lines), system=localize_system(EXPLAIN_SYSTEM, lang_of(conditions)),
                         output_schema=schema))
        except Exception as exc:
            log(f"      [5] 문장 생성 실패 ({type(exc).__name__}) → 규칙 템플릿")
            return None
        if {i.slot for i in draft.items} != want:
            continue
        # headline·summary 에 금지어가 있으면 초안 전체를 버린다(재시도). items 는 슬롯별로 걸러 —
        # 영어 출력에서 reason 한두 개의 "excellent" 때문에 8슬롯 전부 템플릿으로 떨어지던 것.
        if any(w in (draft.headline + " " + draft.summary).lower() for w in _BANNED_IN_DRAFT):
            continue
        bad_slots = [i.slot for i in draft.items
                     if any(w in i.reason.lower() for w in _BANNED_IN_DRAFT)
                     or any(other and other in i.reason for slot, other in names.items() if slot != i.slot)]
        if bad_slots:
            log(f"      [5] 슬롯 {bad_slots} reason 은 금지어/타 슬롯 부품 → 그 슬롯만 규칙 템플릿")
            draft.items = [i for i in draft.items if i.slot not in bad_slots]
        if tgt and str(tgt.confidence) not in draft.headline:
            continue  # headline이 검증 신뢰도 숫자를 빠뜨렸다 — 규칙 4 위반
        if len({i.reason for i in draft.items}) < len(draft.items):
            # 지금 슬롯마다 후보를 1개만 저장해서 전부 "1순위" — 규칙 5의 첫 템플릿이
            # 모든 품목에 똑같이 걸리기 쉽다. 서로 다른 품목인데 문장이 겹치면(토씨만
            # 다른 것도 포함해 완전 동일한 경우만 여기서 걸러진다) 프롬프트 지시(규칙 5
            # 구분 문구)를 안 지킨 것이므로 규칙 템플릿(품목별로 원래 다른 값)으로 내린다.
            continue
        return draft
    log("      [5] 검사 불통과 → 규칙 템플릿")
    return None


def run(build: BuildResult, verification: VerificationResult, log: LogFn,
        rank: RankResult | None = None, conditions: dict | None = None) -> Explanation:
    log("[5] 설명 생성 ...")
    contrib = _contribution(build)
    tgt = verification.targets[0] if verification.targets else None
    gray = tgt.gray_axes if tgt else []
    conf = tgt.confidence if tgt else 0

    # 리뷰 관측(review_line_by_slot·evidence)은 규칙이 만든 것을 그대로 둔다 — LLM 은 건드리지 않는다.
    draft = _llm_draft(build, verification, rank, log, conditions=conditions)
    reason_by_slot = {i.slot: i.reason for i in draft.items} if draft else {}

    lang = lang_of(conditions)
    cur = currency_of(conditions)
    m = lambda n: fmt_money(n, cur)  # noqa: E731
    items, review_lines, review_caveats = [], {}, []
    for it in build.items:
        line, evidence, caveat = _review_line(it.product_key, _ranked_flags(rank, it.slot, it.product_key))
        review_lines[it.slot] = line
        if caveat:
            review_caveats.append(f"{it.slot} {caveat}")
        items.append(ExplanationItem(
            slot=it.slot,
            reason=(reason_by_slot.get(it.slot)
                    or L(lang, f"{it.name} — 조건 충족, {it.rank_from_3b}순위, {m(it.price)}",
                         f"{it.name} — meets the requirements, rank {it.rank_from_3b}, {m(it.price)}")),
            basis=[f"rank{it.rank_from_3b}"],
            evidence=evidence,
        ))
    # caveats 는 규칙이 소유한다 — 회색축과 리뷰 관측 둘 다 코드가 정확히 알고 있어서,
    # LLM 이 같은 내용을 다른 표현으로 또 쓰면 화면에 중복으로 나간다.
    caveats = [L(lang, f"{a} 근거는 확인되지 않았습니다", f"{a}: not verified") for a in gray] + review_caveats
    headline = (draft.headline if draft and draft.headline else L(lang,
        f"예산 {m(build.budget.get('max', 0))} 중 {m(build.totals.get('price', 0))} 사용, "
        f"세트 검증 신뢰도 {conf}점" + ("." if not gray else f" (회색축 {len(gray)}개)."),
        f"{m(build.totals.get('price', 0))} of the {m(build.budget.get('max', 0))} budget used, "
        f"set verification confidence {conf}" + ("." if not gray else f" ({len(gray)} unverified axes)."),
    ))
    # summary 폴백 — 코드가 아는 사실만. 슬롯별 이유는 items 에 있으니 여기서 반복하지 않는다.
    biggest = max(build.items, key=lambda i: i.price, default=None)
    summary = (draft.summary if draft and draft.summary else L(lang,
        f"{len(build.items)}개 부품, 예산 {m(build.budget.get('max', 0))} 중 {m(build.totals.get('price', 0))}을 썼습니다."
        + (f" 비중이 가장 큰 슬롯은 {biggest.slot}({m(biggest.price)})입니다." if biggest else "")
        + f" 세트 검증 신뢰도는 {conf}점이며, 부품별 선택 이유는 각 항목에서 볼 수 있습니다.",
        f"{len(build.items)} parts, {m(build.totals.get('price', 0))} of the {m(build.budget.get('max', 0))} budget."
        + (f" The largest share is {biggest.slot} ({m(biggest.price)})." if biggest else "")
        + f" Set verification confidence is {conf}; per-part reasons are on each item.",
    ))
    summary += _extra_note(conditions)
    log(f"      기여도: 가격 {contrib['가격']}% / 성능 {contrib['성능']}% / 호환성 {contrib['호환성']}%")
    log(f"      문장: {'LLM' if draft else '규칙 템플릿'}")
    log(f"      headline: {headline}")
    n_obs = sum(1 for l in review_lines.values() if not l.startswith("리뷰 관측 없음"))
    log(f"      리뷰 관측: {n_obs}/{len(review_lines)} 슬롯" + (f", 검토 권장 {len(review_caveats)}" if review_caveats else ""))

    return Explanation(
        list_id=build.list_id,
        headline=headline,
        summary=summary,
        contribution=contrib,
        items=items,
        caveats=caveats,
        review_line_by_slot=review_lines,
    )
