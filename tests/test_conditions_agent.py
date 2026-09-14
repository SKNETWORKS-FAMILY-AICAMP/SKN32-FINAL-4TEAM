"""조건 대화 에이전트 — 모델 호출 없이 검증할 수 있는 부분.

도구가 값을 스키마대로 검사·강제하는지, 도구 결과에 '다음 질문'이 실리는지, 대화 이력 변환,
그리고 Strands SDK 가 도구를 실제로 등록하는지(네트워크 없음)를 본다. 실제 모델 응답은
docs/조건대화_에이전트_strands.md 의 실측 기록으로 대신한다.
"""
from __future__ import annotations

import pytest

from src.agent import conditions_agent as ca
from src.categories import load_category
from src.services.session_service import _next_question, compute_missing


def _draft(category: str, values: dict | None = None) -> ca.ConditionDraft:
    cat_def = load_category(category)
    return ca.ConditionDraft(
        category=category, cat_def=cat_def, values=dict(values or {}),
        missing_fn=lambda v: compute_missing(cat_def, v),
        next_question_fn=lambda v: _next_question(cat_def, v),
    )


# ── 값 강제 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("1500000", 1_500_000), ("1,500,000", 1_500_000), ("1,500,000 won", 1_500_000),
    ("150만원", 1_500_000), ("1.5억", 150_000_000), ("2.5 million won", 2_500_000),
    ("300k", 300_000), ("about 2 million", 2_000_000),
    ("300만", 3_000_000), ("300만원", 3_000_000), ("3000000", 3_000_000), ("3,000,000", 3_000_000),
    ("삼백만원", 3_000_000), ("백만원", 1_000_000), ("이천오백만원", 25_000_000), ("일억", 100_000_000),
])
def test_amount_parsing(raw, expected):
    assert ca._parse_amount(raw) == expected


def test_enum_case_insensitive_and_rejects_unknown():
    d = _draft("computer")
    assert d.set("purpose", "Game").startswith("purpose = \"game\"")
    assert d.patches["purpose"] == "game"
    msg = d.set("priority", "cheap")
    assert msg.startswith("오류") and "priority" not in d.patches


def test_unknown_and_file_fields_are_refused():
    d = _draft("computer")
    assert d.set("cpu_model", "5600").startswith("오류")
    assert d.set("current_specs", "{}").startswith("오류")   # 사양 파일이 채우는 필드
    assert not d.patches


def test_list_splits_on_comma_only():
    d = _draft("baby")
    d.set("needs", "수유, 이유식·식사")
    assert d.patches["needs"] == ["수유", "이유식·식사"]   # '·' 는 선택지 라벨 일부


def test_list_none_option_normalises_to_none():
    d = _draft("baby")
    d.set("health_skin", "특이사항 없음")
    d.set("owned_items", "none")
    assert d.patches["health_skin"] == ["none"]
    assert d.patches["owned_items"] == ["none"]


def test_nullable_int_clears_and_bool_parses():
    d = _draft("computer")
    d.set("budget_max", "null")
    assert d.patches["budget_max"] is None
    d.set("noise_sensitive", "yes")
    assert d.patches["noise_sensitive"] is True


@pytest.mark.parametrize("raw, expected", [
    ("1000000", 1_000_000), ("50000000", 50_000_000), ("100만원", 1_000_000),
    ("$1000", 1_000), ("1000만원", 10_000_000),
    ("300만", 3_000_000), ("300만원", 3_000_000), ("3000000", 3_000_000), ("3,000,000", 3_000_000),
    ("삼백만원", 3_000_000),
])
def test_money_type_parses_like_int(raw, expected):
    # baby.yaml 의 budget_max 는 type: money — int 전용 분기만 있으면 항상 실패했었다
    d = _draft("baby")
    out = d.set("budget_max", raw)
    assert not out.startswith("오류"), out
    assert d.patches["budget_max"] == expected


def test_money_type_nullable_clears_and_rejects_non_positive():
    d = _draft("baby")
    d.set("budget_max", "null")
    assert d.patches["budget_max"] is None
    msg = d.set("budget_max", "0")
    assert msg.startswith("오류") and d.patches["budget_max"] is None   # 실패한 set 은 이전 값을 안 건드린다
    msg = d.set("budget_max", "-100")
    assert msg.startswith("오류")


def test_extra_appends_without_duplicates():
    d = _draft("computer", {"extra": ["흰색 케이스"]})
    d.add_extra("흰색 케이스")
    d.add_extra("RGB 없이")
    assert d.patches["extra"] == ["흰색 케이스", "RGB 없이"]


# ── 도구 결과가 다음 질문을 실어 나른다 ────────────────────────────────────
def test_tool_result_carries_next_question_from_rules():
    d = _draft("computer", {"category": "computer", "mode": "build"})
    out = d.set("purpose", "game")
    assert "다음 질문" in out and "예산" in out              # purpose 다음은 budget_max
    d.set("budget_max", "150만원")
    out = d.set("priority", "value")
    assert "모두 채워짐" in out
    assert d.trace and d.trace[0].startswith("set_condition('purpose', 'game')")


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def test_system_prompt_lists_option_codes_and_language():
    d = _draft("baby", {"category": "baby"})
    p = ca.system_prompt(d, "출산 예정이에요")
    assert "0~3개월→1" in p                  # 현재 유아 질문 칩의 라벨→값 매핑이 모델에 보인다
    assert '"특이사항 없음" 이면 값은 none' in p
    assert p.endswith("답변 언어: 한국어 존댓말.")
    assert ca.system_prompt(d, "we're expecting").endswith("including the closing question.")


def test_digits_only_message_follows_conversation_language():
    codes = ca._chip_codes(load_category("computer"))
    # 실측(2026-09-14 원격 테스트): 칩으로 "office" 고르고 "100000" 을 치면 영어로 답했다
    chip_then_digits = [{"role": "assistant", "content": "주로 어떤 용도로 쓰실 건가요?"},
                        {"role": "user", "content": "office"},
                        {"role": "assistant", "content": "예산은 얼마까지 생각하시나요?"}]
    assert ca._reply_language("100000", chip_then_digits, codes) == "ko"
    en_hist = [{"role": "user", "content": "for gaming"}, {"role": "assistant", "content": "Budget?"}]
    assert ca._reply_language("100000", en_hist, codes) == "en"
    assert ca._reply_language("100000") == "ko"
    assert ca._reply_language("QHD 165Hz 쓸 거예요") == "ko"  # 한글이 있으면 라틴 단어가 섞여도 한국어
    multi_chip = [{"role": "user", "content": "CPU, GPU"}, {"role": "assistant", "content": "예산은요?"}]
    assert ca._reply_language("100000", multi_chip, codes) == "ko"   # 멀티 칩 값도 건너뛴다


# ── 대화 이력 ──────────────────────────────────────────────────────────────
def test_history_cuts_at_reset_merges_roles_and_starts_with_user():
    rows = [
        {"role": "user", "content": "옛날 얘기"},
        {"role": "assistant", "content": "옛 답"},
        {"role": "system", "content": "조건을 초기화했어요."},
        {"role": "assistant", "content": "무엇을 도와드릴까요?"},
        {"role": "user", "content": "게임용"},
        {"role": "user", "content": "150만원"},
        {"role": "assistant", "content": "우선순위는요?"},
    ]
    msgs = ca._history(rows)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"][0]["text"] == "게임용\n150만원"


# ── Strands 등록 (네트워크 없음) ───────────────────────────────────────────
def test_strands_registers_three_tools():
    d = _draft("computer")
    tools = ca.make_tools(d)
    assert [t.tool_name for t in tools] == ["set_condition", "add_extra_condition", "clear_condition"]
    spec = tools[0].tool_spec
    assert set(spec["inputSchema"]["json"]["required"]) == {"field", "value"}


def test_unavailable_under_mock_mode(monkeypatch):
    monkeypatch.setattr(ca, "MOCK_MODE", True)
    monkeypatch.setattr(ca, "CONDITIONS_AGENT", True)
    assert ca.available() is False
