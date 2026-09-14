"""리뷰 관측 → 유저용 문장 (src/services/review_plain.py · docs/리뷰관측_문장_초안.md).

경로 6개(관측 없음 3종 / 다른 점 없음 / 초과 / 출시 첫 주 / 소표본) × 언어 2개. 확인하는 것:
(a) 숫자가 문장에 그대로 있다 (b) 유저용 문장에 판정어·통계 용어가 없다 (c) 영어 문장에 한글이 없다.
"""
from __future__ import annotations

import json
import re

import pytest

from src.repo import review_repo
from src.repo.review_repo import ProductRiskStore, SuspectCountFile
from src.services import review_plain, review_service

# 유저용 문장(headline·points·details)에 나오면 안 되는 말. sources(원문)에는 있어도 된다.
BANNED_KO = ("조작", "가짜", "의심", "중앙값", "신뢰구간", "산출물", "기준선", "!")
BANNED_EN = ("fake", "suspicious", "manipulat", "median", " CI", "baseline", "!")

CONTROLS = {"burst7": 0.0549, "one_off_rate": 0.10, "short_span_rate": 0.075, "prolific_rate": 0.112,
            "verified_rate": 0.953, "p5": 0.667, "shared_reviewers": 60, "deg": 903}


def _product(n, *, burst7, burst7_count, first_day=100, burst_start=300, prolific=0.05, one_off=0.1,
             short_span=0.07, verified=0.95, p5=0.7):
    return {"n": n, "mean_rating": 4.5, "p5": p5, "burst7": burst7, "burst7_count": burst7_count,
            "burst7_start_day": burst_start, "first_day": first_day, "one_off_rate": one_off,
            "short_span_rate": short_span, "prolific_rate": prolific, "verified_rate": verified,
            "shared_reviewers": 30, "deg": 300}


@pytest.fixture
def stores(tmp_path, monkeypatch):
    risk = {
        "meta": {"min_reviews": 30, "labels": None, "control_scope": "test", "source": "test"},
        "controls": CONTROLS,
        "products": {
            "ASIN-FLAG": _product(37, burst7=0.135, burst7_count=5, one_off=0.297, short_span=0.216, verified=0.811, p5=0.486),
            "ASIN-PLAIN": _product(748, burst7=0.02, burst7_count=15, prolific=0.107, p5=0.87),
            "ASIN-LAUNCH": _product(120, burst7=0.30, burst7_count=36, first_day=100, burst_start=103),
        },
        "cards": {},
    }
    p = tmp_path / "risk.json"; p.write_text(json.dumps(risk), encoding="utf-8")
    store = ProductRiskStore(p)
    store.alias.update({"flag-part": "ASIN-FLAG", "plain-part": "ASIN-PLAIN", "launch-part": "ASIN-LAUNCH",
                        "thin-part": "ASIN-THIN"})                      # ASIN 은 있는데 산출물에 없다
    store.map_notes.update({"new-part": "데이터 기간(~2023-09) 밖: 2024-01 출시", "lost-part": "후보 없음"})
    suspect = {
        "method": {}, "limits": [], "baseline": {"n": 7054, "ge2": 220, "rate_pct": 3.1},
        "products": {
            "flag-part": {"n": 37, "ge2": 8, "ci2": [9.8, 38.2],
                          "flags": {"burst": 5, "prolific": 3, "one_off": 11, "short_span": 8, "unverified": 7}},
            "plain-part": {"n": 748, "ge2": 10, "ci2": [0.6, 2.4],
                           "flags": {"burst": 2, "prolific": 9, "one_off": 3, "short_span": 6, "unverified": 1}},
        },
    }
    q = tmp_path / "suspect.json"; q.write_text(json.dumps(suspect), encoding="utf-8")
    monkeypatch.setattr(review_repo, "_default_store", store)
    monkeypatch.setattr(review_repo, "_default_store_tried", True)
    monkeypatch.setattr(review_repo, "_default_store_reason", review_repo.RISK_STORE_OK)
    monkeypatch.setattr(review_repo, "_suspect_file", SuspectCountFile(q))
    monkeypatch.setattr(review_repo, "_suspect_tried", True)
    return store


def _user_text(plain: dict) -> list[str]:
    return [plain["headline"], *plain["points"], *plain["details"]]


def _assert_clean(plain: dict, lang: str):
    banned = BANNED_EN if lang == "en" else BANNED_KO
    for s in _user_text(plain):
        for word in banned:
            assert word not in s, f"{word!r} in {s!r}"
        if lang == "en":
            assert not re.search(r"[가-힣]", s), s


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_flagged_part_headline_points_and_small_n(stores, lang):
    p = review_plain.render("flag-part", lang)
    assert p["reason"] is None and p["verify_url"] == "https://www.amazon.com/dp/ASIN-FLAG"
    # 몰림(13.5% ≥ 2×5.5%) + 규칙 집계(CI 하한 9.8 > 3.1) = 2가지. 다작(5%)은 중앙값 미만이라 3층
    assert p["headline"] == ("리뷰 37건 · 사기 전에 살펴볼 점 2가지" if lang == "ko"
                             else "37 reviews · 2 things worth a look before you buy")
    assert len(p["points"]) == 2
    burst, suspect = p["points"]
    assert ("5건(약 14%)" in burst and "5% 정도만" in burst) if lang == "ko" else ("5 reviews (about 14%)" in burst and "only about 5%" in burst)
    # 규칙 집계 — 건수·비율, 가장 많이 걸린 지표 둘(one_off 11 · short_span 8), 소표본 문장
    assert ("8건(약 22%)" in suspect and "이 리뷰 하나만 남긴 계정 · 계정 활동이 짧음" in suspect and "37건뿐이라" in suspect) if lang == "ko" \
        else ("8 of 37 reviews (about 22%)" in suspect and "account with this one review only · short-lived account" in suspect and "With only 37 reviews" in suspect)
    # 3층 — 다작은 "만/only" 없이, 양방향 지표 넷
    assert any(("11%가 30건" in d) if lang == "ko" else ("usually 11% of reviewers" in d) for d in p["details"])
    assert len(p["details"]) == 5
    assert not any(("만 30건" in d) if lang == "ko" else ("only 11%" in d) for d in p["details"])
    _assert_clean(p, lang)
    # 원문은 그대로 남는다 — 검토자용
    assert p["sources"] and any("중앙값" in s or "median" in s for s in p["sources"])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_plain_part_has_no_points(stores, lang):
    p = review_plain.render("plain-part", lang)
    assert p["headline"] == ("리뷰 748건 · 비슷한 부품들과 다른 점 없음" if lang == "ko"
                             else "748 reviews · nothing stands out compared with similar parts")
    assert p["points"] == []
    # 규칙 집계는 CI 하한 0.6 < 3.1 이라 3층으로, n≥100 이라 소표본 문장 없음
    sus = [d for d in p["details"] if ("둘 이상 겹쳐요" in d if lang == "ko" else "two or more traits" in d)]
    assert len(sus) == 1 and ("참고만" not in sus[0] and "rough guide" not in sus[0])
    assert len(p["details"]) == 7
    _assert_clean(p, lang)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_launch_week_burst_is_explained_not_flagged(stores, lang):
    p = review_plain.render("launch-part", lang)
    assert p["points"] == [] and ("다른 점 없음" in p["headline"] or "nothing stands out" in p["headline"])
    burst = p["details"][0]
    assert ("36건(약 30%)" in burst and "출시 직후" in burst) if lang == "ko" else ("36 reviews (about 30%)" in burst and "right after launch" in burst)
    _assert_clean(p, lang)


@pytest.mark.parametrize("lang,key,reason,text", [
    ("ko", "thin-part", "below_threshold", "리뷰가 충분하지 않아요. (30건보다 적어요.)"),
    ("en", "thin-part", "below_threshold", "Not enough reviews. (Fewer than 30.)"),
    ("ko", "new-part", "out_of_period", "리뷰 데이터가 없어요. (2023년 9월 이후 출시)"),
    ("en", "new-part", "out_of_period", "No review data. (Released after September 2023.)"),
    ("ko", "lost-part", "no_match", "리뷰 데이터가 없어요."),
    ("en", "lost-part", "no_match", "No review data."),
    ("ko", "never-heard", "unmapped", "리뷰 데이터가 없어요."),
])
def test_no_data_reasons_are_told_apart(stores, lang, key, reason, text):
    p = review_plain.render(key, lang)
    assert p["reason"] == reason and p["headline"] == text
    assert p["points"] == [] and p["details"] == [] and p["sources"] == [] and p["verify_url"] is None


def test_slug_form_of_key_is_resolved(stores):
    assert review_plain.render("Flag Part", "ko")["reason"] is None
    assert review_plain.render("New Part", "ko")["reason"] == "out_of_period"


def test_store_unavailable(monkeypatch):
    monkeypatch.setattr(review_repo, "_default_store", None)
    monkeypatch.setattr(review_repo, "_default_store_tried", True)
    monkeypatch.setattr(review_repo, "_default_store_reason", review_repo.RISK_STORE_MISSING)
    ko, en = review_plain.render("x", "ko"), review_plain.render("x", "en")
    assert ko["reason"] == en["reason"] == "unavailable"
    assert ko["headline"] == "리뷰 분석을 불러오지 못했어요." and en["headline"] == "Could not load the review analysis."
    assert "pcparts" not in ko["headline"]      # 개발자용 사유(파일명)는 유저 문장에 나가지 않는다


def test_review_brief_carries_plain_medians_and_footer(stores):
    b = review_service.review_brief("flag-part", "en")
    assert b["plain"]["headline"].startswith("37 reviews")
    assert b["signals"]["burst7"]["median"] == 0.0549 and b["signals"]["rating5_share"]["median"] == 0.667
    assert b["signals"]["suspect_2plus"]["baseline"] == 0.031
    assert b["signals"]["shared_reviewers"]["median_count"] == 60
    assert b["cleansing_summary"]["status"] == "ready" and "does not judge" in b["cleansing_summary"]["text"]
    assert "판단하지 않아요" in review_service.review_brief("flag-part", "ko")["cleansing_summary"]["text"]
    thin = review_service.review_brief("thin-part", "ko")
    assert thin["signals"] is None and thin["plain"]["reason"] == "below_threshold"
