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


def test_memo_suggestion_collects_facts_only():
    def item(slot, name, price, *, selected=True, timing="now", qty=1, reason=None):
        return {"slot": slot, "product": {"name": name, "product_key": name}, "price": price, "selected": selected,
                "timing": timing, "qty": qty, "reason": {"status": "ready", "text": reason}}
    result = {
        "conditions_summary": "새 컴퓨터 · 게임 · 1,500,000원 · 가성비", "budget_max": 1_500_000,
        "items": [
            item("CPU", "Intel 265K", 255_000),
            item("GPU", "RTX 5090", 609_000, reason="사용자 요청으로 교체한 부품입니다 — 자동 추천은 'RX 7600'(525,000원)였고 이 후보는 +84,000원입니다. 순위·검증 점수는 교체 전 구성 기준입니다."),
            item("케이스", "NR200P", 69_000, timing="later"),
            item("쿨러", "AK400", 45_000, selected=False),
            item("저장장치", "MX500", 93_000, qty=2),
        ],
        "totals": {"selected_price": 1_119_000, "budget_remaining": 381_000, "over_budget": False},
        "explanation": {"status": "ready", "headline": "게임용 구성, 신뢰도 94점."},
        "verification": {"confidence": 94, "issues": [{"axis": "power", "text": "…"}]},
    }
    memo = rs.memo_suggestion(result, {"extra": ["흰색 케이스"]})
    assert memo.splitlines()[0] == "[조건] 새 컴퓨터 · 게임 · 1,500,000원 · 가성비"     # 예산 중복 없음
    assert "[구성] 4개 부품 1,119,000원, 예산 잔여 381,000원 — " in memo
    assert "케이스 NR200P (나중에)" in memo and "저장장치 MX500 ×2" in memo and "쿨러" not in memo.split("[뺀 것]")[0]
    assert "[뺀 것] 쿨러" in memo
    assert "[직접 바꾼 것] GPU RX 7600 → RTX 5090 (+84,000원) — 호환·검증은 교체 전 구성 기준" in memo
    assert "[요약] 게임용 구성, 신뢰도 94점." in memo
    assert "[확인] 추가 요청 미반영: 흰색 케이스 — 직접 확인 · 세트 검증 신뢰도 94점 (쟁점 있음)" in memo
    assert len(memo) <= 1000


def test_memo_suggestion_over_budget_and_empty():
    result = {"conditions_summary": "", "budget_max": 100, "items": [], "totals": {"selected_price": 0, "budget_remaining": -50, "over_budget": True},
              "explanation": {}, "verification": {}}
    assert rs.memo_suggestion(result, {}) == "[조건] 예산 100원"


def test_rule_path_treats_questions_as_questions():
    slots = {"GPU", "RAM", "CPU"}
    assert rs._parse_swap_request("이 그래픽카드 성능 괜찮아?", slots) == ("GPU", "pricier", True)   # 실측 오탐 1
    assert rs._parse_swap_request("램은 가성비 쪽이 나아?", slots) == ("RAM", "cheaper", True)     # 실측 오탐 2
    assert rs._parse_swap_request("GPU 더 좋은 걸로", slots) == ("GPU", "pricier", False)
    assert rs._parse_swap_request("그래픽카드 더 저렴한 걸로 바꿔줘", slots) == ("GPU", "cheaper", False)
    assert rs._parse_swap_request("저렴하고 좋은 GPU로", slots) == ("GPU", None, True)           # 양방향 → 되묻기
    assert rs._parse_swap_request("케이스 흰색으로", slots) == (None, None, False)


def test_fmt_money_usd_only_and_signed():
    from src.engine.lang import fmt_money
    import src.config as cfg
    rate = cfg.USD_KRW_RATE
    assert fmt_money(1_680_000, "USD") == f"${1_680_000 / rate:,.0f}"
    assert "원" not in fmt_money(1_680_000, "USD")
    assert fmt_money(84_000, "USD", signed=True).startswith("+$")
    assert fmt_money(-84_000, "USD", signed=True).startswith("-$")
    assert fmt_money(84_000, "KRW", signed=True) == "+84,000원" and fmt_money(1_500_000) == "1,500,000원"


def test_memo_and_swap_regex_accept_dollar_amounts():
    rt = "Swapped at your request — the automatic pick was 'RX 7600' ($375); this one is +$60. Ranking …"
    sw = rs._SWAP_RE_EN.search(rt)
    assert sw and sw.group(1) == "RX 7600" and sw.group(2) == "$375" and sw.group(3) == "+$60"
