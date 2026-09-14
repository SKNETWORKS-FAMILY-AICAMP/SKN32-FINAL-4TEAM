"""03 결과 화면 — 추천 요약(summary)·구매 전 확인(checks) 의 코드 소유 부분.

LLM 없이 도는 것만: 요약 본문 조립, extra 안내 문장, [5] 입력의 사용자 조건 줄, 슬롯별 checks 조립.
"""
from __future__ import annotations

from src.engine import stage5_explain as s5
from src.services import recommendation_service as rs


def test_explanation_text_is_summary_plus_caveats():
    assert rs.explanation_text("요약.", []) == "요약."
    out = rs.explanation_text("요약.", ["a 근거는 확인되지 않았습니다", "b"])
    assert out == "요약.\n\n확인이 필요한 것: a 근거는 확인되지 않았습니다 · b"


def test_conditions_lines_exclude_extra_and_note_is_code_owned():
    cond = {"purpose": "game", "priority": "value", "games": ["발로란트", "롤"], "extra": ["흰색 케이스"], "mode": "build"}
    lines = s5._conditions_lines(cond)
    assert len(lines) == 1 and "용도 game" in lines[0] and "게임 ['발로란트', '롤']" in lines[0]
    assert "흰색" not in lines[0]                       # LLM 에게는 안 보여 준다 — "반영됐다"고 쓰던 것
    note = s5._extra_note(cond)
    assert "'흰색 케이스'" in note and "반영되지 않았습니다" in note
    assert s5._extra_note({"purpose": "game"}) == ""
    assert s5._conditions_lines(None) == []


def _item(slot, name="X", reason_text=None):
    return {"slot": slot, "product": {"product_key": name}, "reason": {"status": "ready", "text": reason_text}}


def test_item_checks_maps_axes_to_slots_and_flags_swaps(monkeypatch):
    from src.errors import NotFound
    monkeypatch.setattr(rs, "_AXIS_SLOTS", {"power": ("파워", "GPU")})
    def fake_summary(key):
        raise NotFound("없음")
    monkeypatch.setattr("src.services.review_service.get_summary", fake_summary)
    validations = [{"rule_key": "power", "message": "상시부하 420W 관측"}]
    gpu = rs._item_checks(_item("GPU"), validations, 94)
    ram = rs._item_checks(_item("RAM"), validations, 94)
    swapped = rs._item_checks(_item("GPU", reason_text=rs._SWAP_REASON_PREFIX + " — …"), validations, 94)
    assert gpu["status"] == "ready" and "[power] 상시부하 420W 관측" in gpu["text"]
    assert "쟁점 없음 (세트 신뢰도 94점)" in ram["text"]
    assert "리뷰 관측 없음" in gpu["text"]
    assert "교체한 부품 — 호환·검증은 재실행되지 않았습니다" in swapped["text"] and "교체한 부품" not in gpu["text"]


def test_item_checks_unknown_axis_applies_to_all_slots(monkeypatch):
    from src.errors import NotFound
    monkeypatch.setattr("src.services.review_service.get_summary", lambda key: (_ for _ in ()).throw(NotFound("x")))
    out = rs._item_checks(_item("케이스"), [{"rule_key": "예산", "message": "110% 초과"}], 80)
    assert "[예산] 110% 초과" in out["text"]
