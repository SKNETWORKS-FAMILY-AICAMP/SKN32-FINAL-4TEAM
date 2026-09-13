"""[5] 설명 — [3-B] 의 REVIEW_OBS flags 가 슬롯별 한 줄·근거·주의로 나온다. 점수는 어디에도 없다."""
import json

import pytest

from src.dto import BuildItem, BuildResult, RankResult, VerificationResult
from src.engine import stage5_explain
from src.repo import review_repo
from src.repo.review_repo import ProductRiskStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    risk = {
        "meta": {"min_reviews": 30, "labels": None, "control_scope": "test", "source": "test"},
        "controls": {"burst7": 0.055, "one_off_rate": 0.1, "prolific_rate": 0.1, "p5": 0.6,
                     "shared_reviewers": 50, "deg": 500},
        "products": {"ASIN-CASE": {"n": 49, "mean_rating": 4.7, "p5": 0.8, "burst7": 0.184, "burst7_count": 9,
                                   "burst7_start_day": 300, "first_day": 100, "one_off_rate": 0.2,
                                   "prolific_rate": 0.02, "shared_reviewers": 39, "deg": 309},
                     "ASIN-COOL": {"n": 323, "mean_rating": 4.6, "p5": 0.7, "burst7": 0.04, "burst7_count": 13,
                                   "burst7_start_day": 400, "first_day": 100, "one_off_rate": 0.08,
                                   "prolific_rate": 0.06, "shared_reviewers": 289, "deg": 1200}},
        "cards": {},
    }
    p = tmp_path / "risk.json"; p.write_text(json.dumps(risk), encoding="utf-8")
    s = ProductRiskStore(p)
    s.alias.update({"nzxt-h5-flow": "ASIN-CASE", "deepcool-ak400": "ASIN-COOL"})
    monkeypatch.setattr(review_repo, "_default_store", s)
    monkeypatch.setattr(review_repo, "_default_store_tried", True)
    return s


def test_review_lines_evidence_and_caveat(store):
    rank = RankResult(slots={
        "케이스": {"ranked": [{"product_key": "nzxt-h5-flow",
                             "flags": ["REVIEW_OBS:burst7=0.184>2x0.055", "REVIEW_OBS:prolific_rate=0.250>2x0.100"]}]},
        "쿨러": {"ranked": [{"product_key": "deepcool-ak400", "flags": ["REVIEW_OBS:observed"]}]},
        "CPU": {"ranked": [{"product_key": "intel-core-i5-14400f", "flags": []}]},
    })
    build = BuildResult(list_id="L", items=[
        BuildItem(slot="케이스", product_key="nzxt-h5-flow", name="NZXT H5 Flow", price=90_000),
        BuildItem(slot="쿨러", product_key="deepcool-ak400", name="DeepCool AK400", price=60_000),
        BuildItem(slot="CPU", product_key="intel-core-i5-14400f", name="i5-14400F", price=300_000),
    ], totals={"price": 450_000}, budget={"max": 1_000_000})
    e = stage5_explain.run(build, VerificationResult(list_id="L", category="computer", mode="set"),
                           lambda *_: None, rank=rank)

    lines = e.review_line_by_slot
    assert "7일 몰림 18.4% (부류 중앙값 5.5%)" in lines["케이스"] and "검토 권장" in lines["케이스"]
    assert lines["쿨러"] == "리뷰 323건 관측 — 대조군 중앙값 대비 특이 없음"
    assert lines["CPU"].startswith("리뷰 관측 없음")
    case = next(i for i in e.items if i.slot == "케이스")
    assert case.evidence and case.evidence[0]["kind"] == "review_observation"
    assert case.evidence[0]["verify_url"].endswith("/dp/ASIN-CASE")
    assert any("상품 단위 신호이며 개별 리뷰의 진위가 아닙니다" in c for c in e.caveats)
    assert "score" not in json.dumps(e.model_dump(), ensure_ascii=False)   # 점수는 어디에도 없다
