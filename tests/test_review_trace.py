"""[5] 의 리뷰 관측이 저장 경로(reasoning_log · explanation_text)까지 실리는지.

DB 경로가 review_line_by_slot·caveats 를 읽지 않아 감점만 되고 문장은 사라지던 것을 막는다.
순수 함수만 검증한다 — DB 없이 돈다.
"""
import pytest

from src.services.review_service import (
    REVIEW_TRACE_STEP,
    explanation_text_with_caveats,
    review_trace_steps,
)

NONE_LINE = "리뷰 관측 없음 (리뷰 수 문턱 미만이거나 데이터 기간 밖)"


def test_summary_step_carries_observed_slots():
    steps = review_trace_steps({
        "CPU": NONE_LINE,
        "메인보드": "리뷰 173건 관측 — 대조군 중앙값 대비 특이 없음",
        "케이스": "리뷰 449건 관측 — 7일 몰림 18% (부류 중앙값 5.5%)",
    })
    assert len(steps) == 1                     # evidence 를 안 주면 요약 하나
    head = steps[0]
    assert head["step"] == REVIEW_TRACE_STEP
    assert "2/3 슬롯" in head["title"]
    assert "메인보드" in head["detail"] and "케이스" in head["detail"]
    assert "CPU" not in head["detail"]         # 관측 없는 슬롯은 싣지 않는다


@pytest.mark.parametrize("lines", [
    {},                                         # 슬롯 자체가 없음
    {"CPU": NONE_LINE, "GPU": NONE_LINE},       # 전부 관측 없음
    None,
])
def test_no_steps_when_nothing_observed(lines):
    """"리뷰를 봤지만 깨끗했다" 와 "볼 리뷰가 없었다" 를 같게 보이지 않게 한다."""
    assert review_trace_steps(lines) == []


def test_explanation_text_appends_caveats():
    text = explanation_text_with_caveats(
        ["CPU — 조건 충족, 1순위", "GPU — 조건 충족, 1순위"],
        ["케이스 리뷰 관측: 7일 몰림이 부류 중앙값의 2배를 넘습니다"],
    )
    assert text.startswith("- CPU — 조건 충족, 1순위")
    assert "확인이 필요한 것:" in text
    assert "케이스 리뷰 관측" in text


def test_explanation_text_without_caveats_is_reasons_only():
    text = explanation_text_with_caveats(["CPU — 조건 충족"], [])
    assert text == "- CPU — 조건 충족"
    assert "확인이 필요한 것" not in text


# ── 관측 문장이 화면까지 가는지 ─────────────────────────────────────────────
# "7일 안에 몰림", "리뷰어가 다른 상품에서도 나타남" 은 [5] 가 슬롯별 evidence 로
# 만들어 두는데, 서비스가 reason 만 꺼내 쓰던 탓에 화면에 가지 않았다.
OBS = [
    {"kind": "review_observation",
     "text": "리뷰 449건 중 15건(3.3%)이 7일 안에 몰림 — 전체 상품 중앙값 5.5%",
     "verify_url": "https://www.amazon.com/dp/B0BFH9M9CY"},
    {"kind": "review_observation",
     "text": "리뷰어 411명이 다른 상품에서도 함께 나타남 (연결 상품 4246개) — 중앙값 60명 / 903개",
     "verify_url": "https://www.amazon.com/dp/B0BFH9M9CY"},
    {"kind": "review_observation", "text": "5점 비율 77% — 중앙값 67%"},
]


def test_observation_sentences_become_their_own_step():
    steps = review_trace_steps({"케이스": "리뷰 449건 관측 — 대조군 중앙값 대비 특이 없음"},
                               {"케이스": OBS})
    assert len(steps) == 2                                  # 요약 + 슬롯 하나
    detail = steps[1]["detail"]
    assert "7일 안에 몰림" in detail
    assert "다른 상품에서도 함께 나타남" in detail
    assert "중앙값" in detail                                # 대조군을 항상 옆에 둔다
    assert "확인: https://www.amazon.com/dp/B0BFH9M9CY" in detail
    assert "점수 아님" in steps[1]["title"]


def test_slot_without_evidence_gets_no_extra_step():
    steps = review_trace_steps({"케이스": "리뷰 449건 관측 — 대조군 중앙값 대비 특이 없음"},
                               {"케이스": [{"kind": "x"}]})   # text 없는 항목뿐
    assert len(steps) == 1


def test_unobserved_slot_evidence_is_not_leaked():
    """관측 없음인 슬롯에 evidence 가 섞여 들어와도 단계를 만들지 않는다."""
    steps = review_trace_steps({"CPU": NONE_LINE}, {"CPU": OBS})
    assert steps == []


# ── 순위를 낮춘 후보 ─────────────────────────────────────────────────────────
# 추천된 8개는 대개 "특이 없음" 이다 — 걸린 후보가 감점을 받아 밀려나기 때문이다.
# 그래서 축이 실제로 한 일(덜 보여준 것)이 화면에 하나도 안 나왔다.
from src.services.review_service import review_demotion_step  # noqa: E402

DEMOTED = {
    "케이스": [{"name": "ASUS Prime AP201", "over": [("burst7", 0.20, 0.055)]}],
    "메인보드": [{"name": "ASUS ROG STRIX Z790-E", "over": [("burst7", 0.135, 0.055)]}],
}


def test_demotion_step_names_the_candidates_and_numbers():
    step = review_demotion_step(DEMOTED)
    assert step is not None
    assert "2개" in step["title"]
    assert "ASUS Prime AP201" in step["detail"] and "ASUS ROG STRIX Z790-E" in step["detail"]
    assert "7일 몰림 20.0%" in step["detail"] and "부류 중앙값 5.5%" in step["detail"]


def test_demotion_is_not_described_as_exclusion():
    """낮춘 것은 제외가 아니다 — 후보에 남아 있고 순위만 내려갔다. 되돌릴 수 있는 자리다."""
    step = review_demotion_step(DEMOTED)
    assert "제외 아님" in step["title"]
    assert "순위만 내렸습니다" in step["detail"]
    assert "제외했" not in step["detail"] and "삭제" not in step["detail"]


@pytest.mark.parametrize("bad", [
    None,
    {},
    {"케이스": []},
    {"케이스": [{"name": "X", "over": []}]},      # 넘긴 지표가 없으면 낮춘 게 아니다
])
def test_no_step_when_nothing_demoted(bad):
    assert review_demotion_step(bad) is None
