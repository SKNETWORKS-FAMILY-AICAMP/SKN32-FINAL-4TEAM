"""규칙 기반 "의심 지표 2개+ 리뷰 수" — 판정이 아니라는 것이 문장에 남아야 한다.

리뷰 단위 정답 라벨이 없어 정밀도를 잴 수 없다. 그래서 이 수는 조작 건수가 아니고,
문장에 **건수 · 이항 95% CI · 전체 기준선** 셋이 항상 같이 나와야 한다 — 숫자만 내면
n=30 과 n=3,830 이 같은 무게로 읽힌다(n=37 의 21.6% 는 CI 가 [9.8, 38.2] 다).
"""
import json

import pytest

import src.config as cfg
import src.repo.review_repo as rr
from src.repo.review_repo import SUSPECT_SOURCE, SuspectCountFile

DOC = {
    "method": {"thresholds": {"min_flags": 2}},
    "limits": ["리뷰 단위 정답 라벨이 없어 정밀도를 잴 수 없다"],
    "baseline": {"n": 1000, "ge2": 31, "rate_pct": 3.1},
    "products": {
        "loud": {"asin": "A1", "n": 37, "ge2": 8, "ge3": 0, "ci2": [9.8, 38.2], "flags": {}},
        "quiet": {"asin": "A2", "n": 449, "ge2": 12, "ge3": 1, "ci2": [1.4, 4.6], "flags": {}},
        "tiny": {"asin": "A3", "n": 0, "ge2": 0, "ge3": 0, "ci2": [0.0, 100.0], "flags": {}},
    },
}


@pytest.fixture
def counts(tmp_path):
    p = tmp_path / "suspect.json"
    p.write_text(json.dumps(DOC), encoding="utf-8")
    return SuspectCountFile(p)


def test_sentence_carries_count_ci_and_baseline(counts):
    s = counts.sentence("loud")
    assert "37건 중 8건(21.6%)" in s
    assert "95% 신뢰구간 [9.8, 38.2]" in s      # CI 없이 내보내면 안 된다
    assert "데모 상품 전체 3.1%" in s            # 기준선을 옆에 둔다
    assert "기준선 초과" in s


def test_sentence_says_when_not_distinguishable(counts):
    """CI 하한이 기준선 아래면 "구별되지 않음" 이라고 쓴다 — 16개 중 13개가 그렇다."""
    s = counts.sentence("quiet")
    assert "구별되지 않음" in s and "기준선 초과" not in s


def test_sentence_never_claims_manipulation(counts):
    """조작으로 판정했다고 읽히는 말을 쓰지 않는다."""
    for key in ("loud", "quiet"):
        s = counts.sentence(key)
        for banned in ("조작 리뷰", "조작으로", "가짜", "제외했", "걸러냈"):
            assert banned not in s, f"{banned!r} 가 문장에 있다: {s}"
        assert "의심 지표" in s               # 무엇을 센 것인지 말한다


def test_source_label_says_it_is_not_a_verdict():
    assert "판정 아님" in SUSPECT_SOURCE and "라벨 없음" in SUSPECT_SOURCE


def test_no_sentence_without_reviews(counts):
    assert counts.sentence("tiny") is None
    assert counts.sentence("없는키") is None


def test_missing_file_yields_no_sentence(monkeypatch, tmp_path):
    """파일이 없으면 이 문장을 아예 내지 않는다 — 0건으로 단정하지 않는다."""
    monkeypatch.setattr(cfg, "REVIEW_SUSPECT_COUNTS", tmp_path / "없음.json")
    monkeypatch.setattr(rr, "_suspect_file", None)
    monkeypatch.setattr(rr, "_suspect_tried", False)
    assert rr.default_suspect_counts() is None


def test_broken_file_yields_no_sentence(monkeypatch, tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cfg, "REVIEW_SUSPECT_COUNTS", p)
    monkeypatch.setattr(rr, "_suspect_file", None)
    monkeypatch.setattr(rr, "_suspect_tried", False)
    assert rr.default_suspect_counts() is None


def test_shipped_file_carries_its_own_limits():
    """산출물이 방법·한계를 자기 안에 담아야 한다 — 숫자만 떠돌면 판정으로 읽힌다."""
    from src.config import REVIEW_SUSPECT_COUNTS
    if not REVIEW_SUSPECT_COUNTS.exists():
        pytest.skip("산출물 없음")
    d = json.loads(REVIEW_SUSPECT_COUNTS.read_text(encoding="utf-8"))
    assert d["method"]["thresholds"]["min_flags"] == 2
    assert len(d["limits"]) >= 5
    assert any("정밀도" in x for x in d["limits"])
    assert any("근거로 정한 값이 아니다" in x for x in d["limits"])
    assert d["baseline"]["rate_pct"] > 0
