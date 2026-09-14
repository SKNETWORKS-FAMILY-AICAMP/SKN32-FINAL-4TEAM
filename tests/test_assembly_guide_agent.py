"""조립 가이드 에이전트 — 순서 고정·폴백 경로·에이전트 미가용 시 동작 확인."""
from __future__ import annotations

from src.agent import assembly_guide_agent as agent_mod


def _item(slot: str, name: str) -> dict:
    return {"slot": slot, "product": {"name": name}}


def test_ordered_items_follows_fixed_assembly_order():
    items = [_item("GPU", "지포스"), _item("케이스", "타워"), _item("CPU", "인텔")]
    ordered = agent_mod._ordered_items(items)
    assert [it["slot"] for it in ordered] == ["케이스", "CPU", "GPU"]


def test_unknown_slot_goes_last_but_keeps_relative_order():
    items = [_item("특이슬롯A", "x"), _item("케이스", "타워"), _item("특이슬롯B", "y")]
    ordered = agent_mod._ordered_items(items)
    assert [it["slot"] for it in ordered] == ["케이스", "특이슬롯A", "특이슬롯B"]


def test_build_guide_fallback_cites_real_search_result_per_item():
    items = [_item("GPU", "AMD Radeon RX 7600"), _item("저장장치", "Crucial MX500 1TB")]
    text = agent_mod.build_guide_fallback(items)
    assert "1. GPU — AMD Radeon RX 7600" in text
    assert "2. 저장장치 — Crucial MX500 1TB" in text
    # 폴백도 실제 검색을 쓴다 — 두 줄 다 빈 문장이 아니어야 한다.
    lines = text.splitlines()
    assert all(line.strip() for line in lines)


def test_build_guide_returns_pending_when_no_items():
    assert agent_mod.build_guide([]) == {"status": "pending", "text": None}


def test_build_guide_falls_back_when_agent_unavailable(monkeypatch):
    monkeypatch.setattr(agent_mod, "available", lambda: False)
    result = agent_mod.build_guide([_item("케이스", "타워")])
    assert result["status"] == "ready"
    assert "케이스" in result["text"]


def test_build_guide_falls_back_when_agent_raises(monkeypatch):
    monkeypatch.setattr(agent_mod, "available", lambda: True)

    class _Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("strands unavailable in test")

    monkeypatch.setattr("strands.Agent", _Boom, raising=False)
    result = agent_mod.build_guide([_item("케이스", "타워")])
    assert result["status"] == "ready"
    assert "케이스" in result["text"]


def test_system_prompt_switches_to_english_instruction():
    ordered = [_item("케이스", "타워")]
    ko = agent_mod._system_prompt(ordered)
    en = agent_mod._system_prompt(ordered, lang="en")
    assert "한국어 존댓말로 답합니다." in ko
    assert "Reply entirely in English" in en
    assert "한국어 존댓말로 답합니다." not in en


def test_fallback_translates_slot_label_when_english(monkeypatch):
    """폴백도 LLM 없이 slot 라벨(_slot_label)과 근거 문서의 text_en으로 영어를 낼 수 있다."""
    monkeypatch.setattr(agent_mod, "available", lambda: False)
    result = agent_mod.build_guide([_item("케이스", "타워")], lang="en")
    assert result["status"] == "ready"
    assert "Case" in result["text"]
    assert "케이스" not in result["text"]


def test_fallback_stays_korean_when_lang_ko(monkeypatch):
    monkeypatch.setattr(agent_mod, "available", lambda: False)
    result = agent_mod.build_guide([_item("케이스", "타워")])
    assert result["status"] == "ready"
    assert "케이스" in result["text"]
