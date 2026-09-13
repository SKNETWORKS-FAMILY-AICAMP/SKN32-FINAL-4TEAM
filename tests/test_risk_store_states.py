"""산출물(pcparts_product_risk.json)이 없거나 깨졌거나 대조군이 다를 때.

이 파일은 gitignore 라 팀원은 클론만으로 받지 못하고 손으로 전달된다(5MB). 그래서
없음·잘림·엉뚱한 파일이 일상적으로 생긴다. 셋 다 추천을 죽이지 않고, **원인을 구분해
말해야** 한다 — "리뷰 수 문턱 미만" 으로 뭉개면 파일을 안 받은 사람이 그 사실을 모른다.
"""
import json

import pytest

import src.config as cfg
import src.repo.review_repo as rr
from src.repo.review_repo import (RISK_STORE_INVALID, RISK_STORE_MISSING, RISK_STORE_OK,
                                  RISK_STORE_SCOPE_MISMATCH, ProductRiskStore)

GOOD = {
    "meta": {"control_scope": "Computer Components|Data Storage"},
    "controls": {"burst7": 0.05},
    "products": {"B001": {"n": 100, "burst7": 0.2}},
    "cards": {"flagged": [{"product_key": "B001"}]},
}


@pytest.fixture
def reset_store():
    """모듈 전역 캐시를 매번 비운다 — 한 번만 읽는 구조라 테스트 간 누수가 생긴다."""
    saved = (cfg.REVIEW_RISK_JSON, rr._default_store, rr._default_store_tried, rr._default_store_reason)
    yield
    cfg.REVIEW_RISK_JSON, rr._default_store, rr._default_store_tried, rr._default_store_reason = saved


def _point_at(tmp_path, content, name="pcparts_product_risk.json"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    cfg.REVIEW_RISK_JSON = p
    rr._default_store, rr._default_store_tried, rr._default_store_reason = None, False, "not_loaded"
    return p


def test_good_file_loads(reset_store, tmp_path):
    _point_at(tmp_path, json.dumps(GOOD))
    assert rr.default_risk_store() is not None
    assert rr.risk_store_reason() == RISK_STORE_OK
    assert "문턱" in rr.risk_store_note()          # 관측 없음의 정상 사유


def test_missing_file_is_named(reset_store, tmp_path):
    cfg.REVIEW_RISK_JSON = tmp_path / "없는파일.json"
    rr._default_store, rr._default_store_tried, rr._default_store_reason = None, False, "not_loaded"
    assert rr.default_risk_store() is None
    assert rr.risk_store_reason() == RISK_STORE_MISSING
    assert "미탑재" in rr.risk_store_note() and "없는파일.json" in rr.risk_store_note()


@pytest.mark.parametrize("bad,label", [
    ('{"wrong":"shape"}', "필수 키 없음"),
    ('{"meta":{},"controls":{}}', "필수 키 없음"),      # 일부만 있는 것도 거부
    ('{"meta": {"control_sco', "읽지 못함"),            # 전송 중 잘림
    ('[1,2,3]', "객체가 아니다"),
])
def test_broken_file_does_not_crash(reset_store, tmp_path, bad, label):
    """전에는 KeyError 로 추천 전체가 죽었다."""
    _point_at(tmp_path, bad)
    assert rr.default_risk_store() is None            # 예외가 아니라 None
    assert rr.risk_store_reason().startswith(RISK_STORE_INVALID)
    assert label in rr.risk_store_reason() or label in rr.risk_store_note()


@pytest.mark.parametrize("scope", [None, "Baby Products", "all"])
def test_wrong_control_scope_is_refused(reset_store, tmp_path, scope):
    """대조군이 다르면 관측을 내지 않는다 — 틀린 중앙값과 비교하면 조용히 틀린다."""
    data = dict(GOOD, meta={} if scope is None else {"control_scope": scope})
    _point_at(tmp_path, json.dumps(data))
    assert rr.default_risk_store() is None
    assert rr.risk_store_reason().startswith(RISK_STORE_SCOPE_MISMATCH)
    assert "대조군 범위 불일치" in rr.risk_store_note()


def test_card_without_product_key_is_skipped(reset_store, tmp_path):
    """카드 한 항목이 깨졌다고 파일 전체를 버리지 않는다."""
    data = dict(GOOD, cards={"flagged": [{"product_key": "B001"}, {"no_key": 1}, "문자열"]})
    p = _point_at(tmp_path, json.dumps(data))
    store = ProductRiskStore(p)
    assert set(store.cards) == {"B001"}


# ── 출시 첫 주 몰림 ─────────────────────────────────────────────────────────
# 출시 주에 몰린 것은 조작이 아니라 출시다(산출물 전체에서 몰림 2배 초과 상품의 11.9%).
# 랭킹 신호에서는 빼되 **카드에는 그 이유를 적어야** 한다 — 적지 않으면 검토자가
# "중앙값의 3배인데 왜 검토 권장이 안 붙었나" 를 알 수 없다.
LAUNCH = {
    "meta": {"control_scope": "Computer Components|Data Storage"},
    "controls": {"burst7": 0.05, "shared_reviewers": 60, "deg": 900, "p5": 0.67},
    "products": {"A": {"n": 100, "burst7": 0.3, "burst7_count": 30, "burst7_start_day": 105,
                       "first_day": 100, "shared_reviewers": 70, "deg": 1000, "p5": 0.8},
                 "B": {"n": 100, "burst7": 0.3, "burst7_count": 30, "burst7_start_day": 400,
                       "first_day": 100, "shared_reviewers": 70, "deg": 1000, "p5": 0.8}},
    "cards": {},
}


@pytest.fixture
def launch_store(tmp_path):
    p = tmp_path / "risk.json"
    p.write_text(json.dumps(LAUNCH), encoding="utf-8")
    return ProductRiskStore(p)


def test_launch_burst_is_dropped_from_ranking_signal(launch_store):
    assert [k for k, _, _ in launch_store.excess("A")] == []        # 출시 5일째 → 뺀다
    assert "burst7" in [k for k, _, _ in launch_store.excess("B")]  # 300일째 → 남긴다


def test_launch_burst_says_why_on_the_card(launch_store):
    """반박에 필요한 사실을 쥐고 안 주면 안 된다."""
    a = launch_store.observations("A")[0]
    assert "출시 첫 주" in a and "랭킹 신호에서 뺐다" in a
    assert "30건" in a and "전체 상품 중앙값" in a      # 관측 자체는 그대로 보인다
    assert "출시 첫 주" not in launch_store.observations("B")[0]


def test_launch_rule_lives_in_one_place(launch_store):
    """excess() 와 observations() 가 같은 판정을 쓴다 — 갈리면 화면과 랭킹이 어긋난다."""
    assert launch_store.is_launch_burst(LAUNCH["products"]["A"]) is True
    assert launch_store.is_launch_burst(LAUNCH["products"]["B"]) is False
    assert launch_store.is_launch_burst({}) is False          # 날짜가 없으면 판정하지 않는다
