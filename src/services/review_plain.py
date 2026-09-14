"""리뷰 관측 → 유저가 읽을 문장 (docs/리뷰관측_문장_초안.md).

숫자는 산출물(ProductRiskStore · SuspectCountFile)의 값 그대로, 말은 템플릿. LLM 은 안 쓴다.
점수도 판정도 아니고 관측이다(docs/decisions/0001) — 조작·가짜 같은 판정어를 쓰지 않는다.
두 언어 다 수치에서 렌더한다 — 한국어 문장을 정규식으로 번역하던 자리(stage5·logs.js)를 대신한다.

3층: headline(한 줄) → points(중앙값을 넘어 뽑힌 것만) → details(나머지 지표) + sources(산출물 원문).
관측이 없으면 headline 이 사유 한 줄이고 reason 에 사유 코드가 실린다.

템플릿 규칙(초안 문서 "템플릿 규칙"): 값은 %로 통일하고 건수는 괄호로 · 비교문은 주어·서술어를 다시 써서
독립문으로 · "만/only" 는 중앙값을 넘어 뽑힌 지표에만 · 짧게 줄여도 "왜" 는 지우지 않는다 · 느낌표·"주의" 없음.
"""
from __future__ import annotations

import re

from src.config import REVIEW_AXIS_EXCESS
from src.engine.lang import L
from src.repo.review_repo import (ProductRiskStore, SuspectCountFile, default_risk_store,
                                 default_suspect_counts)

# 규칙 집계 지표(SuspectCountFile.method.indicators 의 키) → 유저용 이름
_TRAIT = {
    "burst": ("같은 일주일에 몰림", "posted within the same week"),
    "prolific": ("리뷰를 30건 넘게 쓴 계정", "account with 30+ reviews"),
    "one_off": ("이 리뷰 하나만 남긴 계정", "account with this one review only"),
    "short_span": ("계정 활동이 짧음", "short-lived account"),
    "unverified": ("구매 확인 없음", "no verified-purchase mark"),
}

# 규칙 집계 비율에 "참고만 하세요" 를 붙이는 리뷰 수. n=37 의 21.6% 는 95% CI 가 [9.8, 38.2] 다 —
# 신뢰구간을 유저에게 보이는 대신 이 한 문장으로 같은 뜻을 전한다.
SMALL_N = 100

REASON_UNAVAILABLE = "unavailable"   # 산출물을 못 읽었다 (파일 없음 · 형식 · 대조군 범위 불일치)

_MONTH_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


def _pct(v: float) -> str:
    return f"{100 * float(v):.0f}"


def _n(v) -> str:
    return f"{int(v):,}"


# ── 지표별 문장 ─────────────────────────────────────────────────────────────
def _burst(f: dict, m: float, lang: str, *, flagged: bool, launch: bool) -> str:
    s = L(lang,
          f"리뷰 {_n(f['burst7_count'])}건(약 {_pct(f['burst7'])}%)이 같은 일주일에 몰려 올라왔어요. "
          f"비슷한 부품은 보통 리뷰의 {_pct(m)}% 정도{'만' if flagged else '가'} 같은 일주일에 몰려요.",
          f"{_n(f['burst7_count'])} reviews (about {_pct(f['burst7'])}%) were posted within the same week. "
          f"For similar parts, usually {'only ' if flagged else ''}about {_pct(m)}% of reviews land in the same week.")
    if launch:
        s += L(lang, " 출시 직후 일주일이라 자연스럽게 리뷰가 몰린 것 같아요.",
               " That week was right after launch, so the bunching looks natural.")
    return s


def _prolific(v: float, m: float, lang: str, *, flagged: bool) -> str:
    return L(lang,
             f"리뷰어 중 {_pct(v)}%가 리뷰를 30건 넘게 쓴 계정이에요. "
             f"비슷한 부품은 보통 리뷰어 중 {_pct(m)}%{'만' if flagged else '가'} 30건 넘게 리뷰를 썼어요.",
             f"{_pct(v)}% of the reviewers are accounts with more than 30 reviews. "
             f"For similar parts, usually {'only ' if flagged else ''}{_pct(m)}% of reviewers have written that many.")


def _one_off(v: float, m: float, lang: str) -> str:
    return L(lang,
             f"리뷰어 중 {_pct(v)}%가 이 리뷰 하나만 남긴 계정이에요. 비슷한 부품은 보통 {_pct(m)}%예요.",
             f"{_pct(v)}% of the reviewers are accounts with this one review only. For similar parts it is usually {_pct(m)}%.")


def _short_span(v: float, m: float, lang: str) -> str:
    return L(lang,
             f"리뷰어 중 {_pct(v)}%가 활동 기간이 30일 이하인 계정이에요. 비슷한 부품은 보통 {_pct(m)}%예요.",
             f"{_pct(v)}% of the reviewers are accounts active for 30 days or less. For similar parts it is usually {_pct(m)}%.")


def _verified(v: float, m: float, lang: str) -> str:
    return L(lang,
             f"리뷰 중 {_pct(v)}%에 구매 확인 표시가 있어요. 비슷한 부품은 보통 {_pct(m)}%에 구매 확인 표시가 있어요. "
             "(체험단·증정 리뷰는 표시가 없을 수 있어요)",
             f"{_pct(v)}% of the reviews carry a verified-purchase mark. For similar parts, usually {_pct(m)}% of reviews carry it. "
             "(Reviews from free-sample or gift programs may not carry the mark.)")


def _p5(v: float, m: float, lang: str) -> str:
    return L(lang,
             f"리뷰 중 {_pct(v)}%가 5점 리뷰예요. 비슷한 부품은 보통 {_pct(m)}%가 5점 리뷰예요.",
             f"{_pct(v)}% of the reviews are 5-star. For similar parts, usually {_pct(m)}% are 5-star.")


def _suspect(v: dict, lang: str) -> str:
    n, k = int(v["n"]), int(v["ge2"])
    flags = v.get("flags") or {}
    top = sorted((key for key in flags if key in _TRAIT), key=lambda key: -int(flags[key]))[:2]
    names = " · ".join(_TRAIT[key][1 if lang == "en" else 0] for key in top) or L(lang, "여러 지표", "several traits")
    s = L(lang,
          f"리뷰 {_n(n)}건 중 {_n(k)}건(약 {_pct(k / n)}%)은 '{names}' 같은 특징이 둘 이상 겹쳐요.",
          f"{_n(k)} of {_n(n)} reviews (about {_pct(k / n)}%) share two or more traits such as '{names}'.")
    if n < SMALL_N:
        s += L(lang, f" 리뷰가 {_n(n)}건뿐이라 이 숫자는 참고만 하세요.",
               f" With only {_n(n)} reviews, treat this number as a rough guide.")
    return s


def _suspect_stands_out(v: dict, sus: SuspectCountFile) -> bool:
    """SuspectCountFile.sentence() 의 "기준선 초과" 와 같은 판정 — CI 하한이 전체 기준선을 넘는가."""
    base = sus.baseline.get("rate_pct")
    lo = (v.get("ci2") or [0.0])[0]
    return base is not None and lo > base


# ── 관측 없음 ───────────────────────────────────────────────────────────────
def _no_data(store: ProductRiskStore | None, keys: list[str], lang: str) -> dict:
    if store is None:
        return _plain(L(lang, "리뷰 분석을 불러오지 못했어요.", "Could not load the review analysis."),
                      reason=REASON_UNAVAILABLE)
    # 받은 키와 슬러그 중 매핑 표에 있는 쪽의 사유를 쓴다
    cov, note = store.COVERAGE_UNMAPPED, ""
    for key in keys:
        cov, note = store.coverage(key)
        if cov != store.COVERAGE_UNMAPPED:
            break
    if cov == store.COVERAGE_BELOW_THRESHOLD:
        floor = int(store.meta.get("min_reviews", 30))
        return _plain(L(lang, f"리뷰가 충분하지 않아요. ({floor}건보다 적어요.)", f"Not enough reviews. (Fewer than {floor}.)"),
                      reason=cov)
    if cov == store.COVERAGE_OUT_OF_PERIOD:
        m = re.search(r"~(\d{4})-(\d{2})", note)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            return _plain(L(lang, f"리뷰 데이터가 없어요. ({y}년 {mo}월 이후 출시)",
                            f"No review data. (Released after {_MONTH_EN[mo - 1]} {y}.)"), reason=cov)
    return _plain(L(lang, "리뷰 데이터가 없어요.", "No review data."), reason=cov)


def _plain(headline: str, *, points=None, details=None, sources=None, verify_url=None, reason=None) -> dict:
    return {"headline": headline, "points": points or [], "details": details or [], "sources": sources or [],
            "verify_url": verify_url, "reason": reason}


# ── 진입점 ──────────────────────────────────────────────────────────────────
def render(product_key: str, lang: str = "ko") -> dict:
    """ReviewPlainOut 모양의 dict. 산출물이 없거나 상품이 없으면 headline 이 사유 한 줄, reason 에 코드."""
    from src.services.review_service import candidate_keys   # 순환 import 회피

    store = default_risk_store()
    keys = candidate_keys(product_key)
    if store is None:
        return _no_data(None, keys, lang)
    key = f = None
    for cand in keys:
        found = store.get(cand)
        if found is not None:
            key, f = cand, found
            break
    if f is None:
        return _no_data(store, keys, lang)

    m = store.controls
    n = int(f["n"])
    # 랭킹([3-B])과 같은 규칙으로 "살펴볼 점" 을 고른다 — excess() 는 출시 첫 주 몰림과 중앙값 0 을 이미 뺐다
    flagged = {k for k, v, med in store.excess(key) if v >= REVIEW_AXIS_EXCESS * med}
    launch = store.is_launch_burst(f)
    points: list[str] = []
    details: list[str] = []

    if f.get("burst7_count") is not None and m.get("burst7"):
        s = _burst(f, m["burst7"], lang, flagged="burst7" in flagged, launch=launch)
        (points if "burst7" in flagged else details).append(s)
    if f.get("prolific_rate") is not None and m.get("prolific_rate"):
        s = _prolific(f["prolific_rate"], m["prolific_rate"], lang, flagged="prolific_rate" in flagged)
        (points if "prolific_rate" in flagged else details).append(s)

    sus = default_suspect_counts()
    v = sus.get(key) if sus else None
    sources: list[str] = store.observations(key, lang)
    if v and v.get("n"):
        s = _suspect(v, lang)
        (points if _suspect_stands_out(v, sus) else details).append(s)
        line = sus.sentence(key, lang)
        if line:
            sources.append(line)

    # 양방향 지표 — 방향을 해석하지 않으므로 항상 3층
    for fk, fn in (("one_off_rate", _one_off), ("short_span_rate", _short_span),
                   ("verified_rate", _verified), ("p5", _p5)):
        if f.get(fk) is not None and m.get(fk) is not None:
            details.append(fn(f[fk], m[fk], lang))
    # shared_reviewers 는 절대수라 리뷰가 많으면 무조건 중앙값을 넘는다 — 비율로 바꾸기 전엔 문장으로 내지
    # 않는다(초안 문서 "먼저 결정할 것 1"). 원문(sources)에는 그대로 있다.

    k = len(points)
    if k:
        headline = L(lang, f"리뷰 {_n(n)}건 · 사기 전에 살펴볼 점 {k}가지",
                     f"{_n(n)} reviews · {k} thing{'s' if k > 1 else ''} worth a look before you buy")
    else:
        headline = L(lang, f"리뷰 {_n(n)}건 · 비슷한 부품들과 다른 점 없음",
                     f"{_n(n)} reviews · nothing stands out compared with similar parts")
    return _plain(headline, points=points, details=details, sources=sources,
                  verify_url=f"https://www.amazon.com/dp/{store.resolve(key)}")
