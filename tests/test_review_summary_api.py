"""GET /reviews/summary/{product_key} — 실측 관측과 합성 데모 블록이 섞이지 않는다."""
import json

import pytest

pytest.importorskip("httpx")                      # TestClient 의존성 — `uv sync --group test`
from fastapi.testclient import TestClient         # noqa: E402

from src.api import app
from src.config import REVIEW_SUMMARIES_DEMO
from src.repo import review_repo
from src.repo.review_repo import ProductRiskStore, ReviewSummaryDemoFile
from src.services import review_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    """관계 축 산출물을 손으로 만든 최소 JSON 으로 대체 — pandas·실데이터 없이 돈다."""
    risk = {
        "meta": {"min_reviews": 30, "labels": None, "control_scope": "test", "source": "test"},
        "controls": {"burst7": 0.05, "one_off_rate": 0.1, "prolific_rate": 0.1, "p5": 0.6,
                     "shared_reviewers": 50, "deg": 500},
        "products": {"ASIN1": {"n": 120, "mean_rating": 4.5, "p5": 0.7, "burst7": 0.2, "burst7_count": 24,
                               "burst7_start_day": 300, "first_day": 100, "one_off_rate": 0.1,
                               "prolific_rate": 0.05, "shared_reviewers": 80, "deg": 900}},
        "cards": {"burst_top": []},
    }
    p = tmp_path / "risk.json"
    p.write_text(json.dumps(risk), encoding="utf-8")
    store = ProductRiskStore(p)
    store.alias["amd-ryzen-5-5600"] = "ASIN1"          # 데모 부품 하나를 관측에 잇는다
    monkeypatch.setattr(review_repo, "_default_store", store)
    monkeypatch.setattr(review_repo, "_default_store_tried", True)
    monkeypatch.setattr(review_service, "_demo_file", ReviewSummaryDemoFile(REVIEW_SUMMARIES_DEMO))
    return TestClient(app)


def test_observed_part_fills_contract_names_and_nulls_the_verdicts(client):
    """계약 이름(total_count · rating_raw)으로 낸다 — 이름을 달리 지으면 화면이 "리뷰 0건" 을 낸다."""
    j = client.get("/reviews/summary/amd-ryzen-5-5600").json()
    assert j["total_count"] == 120 and j["rating_raw"] == 4.5              # 낼 수 있는 것은 채운다
    assert j["rating_refined"] is None                                     # 판정기 없음
    assert j["excluded_count"] is None and j["excluded_ratio"] is None
    assert j["distribution_raw"] == {} and j["distribution_refined"] == {}  # 4·3·2점이 없어 안 낸다
    risk = j["product_manipulation_risk"]
    assert risk["score"] is None and risk["reliable_range"] is True
    assert any("7일 안에 몰림" in e for e in risk["evidence"]) and risk["product_ref"] == "ASIN1"
    assert j["synthetic_demo"]["is_synthetic"] is True                     # 합성 블록은 표지와 함께 분리
    assert "합성" in j["synthetic_demo"]["note"] and j["synthetic_demo"]["cleaned_rating"] is not None


def test_observations_reach_summaries_with_their_source(client):
    """화면에 문장을 실을 칸이 summaries 뿐이다. 리뷰 발췌로 읽히지 않게 출처를 밝힌다."""
    j = client.get("/reviews/summary/amd-ryzen-5-5600").json()
    assert j["summaries"], "관측 문장이 화면에 갈 자리에 없다"
    obs = [e for e in j["summaries"] if e["source"] == review_service.OBSERVATION_SOURCE]
    assert any("7일 안에 몰림" in e["text"] for e in obs)
    assert "리뷰 본문 아님" in review_service.OBSERVATION_SOURCE
    # 규칙 기반 의심 건수가 섞여 들어오면 **출처가 달라야** 한다 — 관측 사실과 성격이 다르다
    from src.repo.review_repo import SUSPECT_SOURCE
    assert all(e["source"] in (review_service.OBSERVATION_SOURCE, SUSPECT_SOURCE)
               for e in j["summaries"])
    for e in j["summaries"]:
        if e["source"] == SUSPECT_SOURCE:
            assert "의심 지표" in e["text"] and "신뢰구간" in e["text"]
    # 합성 요약이 실측 자리로 새지 않는다
    assert j["summaries"] != j["synthetic_demo"]["top_summaries"]


def test_burst_count_is_not_reported_as_excluded(client):
    """몰림 24건을 excluded_count 로 내면 화면이 "24건 제외" 로 그린다 — 우리는 아무것도 빼지 않았다."""
    j = client.get("/reviews/summary/amd-ryzen-5-5600").json()
    assert j["excluded_count"] is None
    assert "24" not in str(j["excluded_count"]) and j["excluded_ratio"] is None


def test_unobserved_demo_part_returns_demo_block_only(client):
    j = client.get("/reviews/summary/intel-core-i5-14400f").json()
    assert j["total_count"] == 0 and j["rating_raw"] is None
    assert j["product_manipulation_risk"]["evidence"] == [] and j["summaries"] == []
    assert "관측 없음" in j["data_notice"]
    assert j["synthetic_demo"]["axis_scores"]                             # 항목별 평가는 데모에서


def test_unknown_key_is_404_envelope(client):
    r = client.get("/reviews/summary/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ── 결과 응답의 product_key 가 슬러그가 아닐 때 ─────────────────────────────
# GET /session/{id}/result 는 catalog.product.model(제품명 원문)을 product_key 로 내보내고
# 화면이 그 값을 이 엔드포인트에 그대로 넘긴다. 슬러그만 받으면 전부 404 가 된다.
def test_candidate_keys_adds_slug_form():
    from src.services.review_service import candidate_keys
    assert candidate_keys("ASUS TUF GAMING B650-PLUS WIFI") == [
        "ASUS TUF GAMING B650-PLUS WIFI", "asus-tuf-gaming-b650-plus-wifi"]


def test_candidate_keys_keeps_slug_first_and_does_not_duplicate():
    """저쪽이 슬러그를 내보내게 고쳐지면 첫 후보가 바로 맞고 변환은 일어나지 않는다."""
    from src.services.review_service import candidate_keys
    assert candidate_keys("asus-tuf-gaming-b650-plus-wifi") == ["asus-tuf-gaming-b650-plus-wifi"]
