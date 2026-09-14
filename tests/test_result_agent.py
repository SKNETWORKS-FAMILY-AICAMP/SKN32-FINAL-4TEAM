"""결과 화면 에이전트 — 모델·DB 없이 검증할 수 있는 부분.

슬롯 찾기, 도구 인자 검사, 근거 질문 선조회 트리거, 프롬프트에 구성표·이유가 실리는지, Strands 도구 등록.
실제 모델 응답과 DB 경로는 docs/결과화면_에이전트_strands.md 의 실측 기록.
"""
from __future__ import annotations

from uuid import uuid4

from src.agent import result_agent as ra


def _result() -> dict:
    def item(slot, name, price, reason="ready", **kw):
        d = {"item_id": str(uuid4()), "slot": slot, "slot_label": slot, "price": price, "qty": 1,
             "selected": True, "timing": "now", "alternatives_count": 3, "budget_share": 0.2,
             "product": {"product_key": name.lower().replace(" ", "-"), "name": name, "spec_summary": "성능 티어 6"},
             "reason": {"status": reason, "text": "1순위, 밸런스" if reason == "ready" else None}}
        d.update(kw)
        return d
    return {
        "run_id": str(uuid4()), "category": "computer", "conditions_summary": "게임 · 가성비",
        "budget_max": 1_500_000,
        "items": [item("CPU", "Intel Core Ultra 7 265K", 255_000), item("GPU", "AMD Radeon RX 7600", 525_000),
                  item("케이스", "NR200P", 69_000, reason="pending", selected=False)],
        "totals": {"selected_price": 780_000, "selected_units": 2, "budget_remaining": 720_000, "over_budget": False},
        "verification": {"status": "ready", "confidence": 94, "issues": [{"axis": "power", "text": "ok (근사)"}]},
    }


def _session() -> ra.ResultSession:
    return ra.ResultSession(conn=None, revision_id=uuid4(), result=_result())


def test_item_lookup_by_slot_case_insensitive():
    s = _session()
    assert s.item("gpu")["product"]["name"] == "AMD Radeon RX 7600"
    assert s.item("케이스")["selected"] is False
    assert s.item("모니터") is None


def test_set_item_validates_before_touching_db():
    s = _session()          # conn=None — DB 에 닿으면 AttributeError 로 터진다
    assert s.set_item("GPU", qty="0").startswith("오류")
    assert s.set_item("GPU", qty="abc").startswith("오류")
    assert s.set_item("GPU", timing="tomorrow").startswith("오류")
    assert s.set_item("GPU").startswith("오류")          # 바꿀 값 없음
    assert s.set_item("모니터", qty="2").startswith("오류")
    assert s.swap("GPU", "not-a-uuid").startswith("오류")
    assert s.swap("모니터", str(uuid4())).startswith("오류")
    assert len(s.trace) == 7 and not s.changed


def test_prefetch_triggers_only_on_why_questions(monkeypatch):
    s = _session()
    monkeypatch.setattr(ra.ResultSession, "explain", lambda self, slot: f"EXPLAIN[{slot}]")
    assert ra._prefetch_explanations(s, "그래픽카드 더 싼 걸로") == ""
    assert ra._prefetch_explanations(s, "왜 이 CPU야?") == "EXPLAIN[CPU]"
    assert ra._prefetch_explanations(s, "그래픽카드 리뷰 어때?") == "EXPLAIN[GPU]"    # 동의어 → 슬롯
    out = ra._prefetch_explanations(s, "이 구성 괜찮아?")                                # 슬롯 없음 → 담긴 것 전부
    assert out == "EXPLAIN[CPU]\n\nEXPLAIN[GPU]"                                            # 빼둔 케이스는 제외


def test_system_prompt_carries_table_reasons_budget_and_language():
    r = _result()
    p = ra.system_prompt(r, "왜 이 CPU야?", [], prefetched="PRE")
    assert "- CPU: Intel Core Ultra 7 265K · 255,000원 × 1" in p
    assert "추천 이유: 1순위, 밸런스" in p
    assert "케이스: NR200P · 69,000원 × 1 · 시점 now (빼둠)" in p
    assert "예산 상한: 1,500,000원 · 총액: 780,000원 · 잔여: 720,000원" in p
    assert "[power] ok (근사)" in p
    assert "미리 조회한 근거" in p and "\nPRE" in p
    assert p.endswith("답변 언어: 한국어 존댓말.")
    assert "미리 조회한 근거" not in ra.system_prompt(r, "swap the gpu", [])
    assert ra.system_prompt(r, "swap the gpu", []).endswith("Write the entire reply in English.")


def test_strands_registers_six_tools():
    tools = ra.make_tools(_session())
    assert [t.tool_name for t in tools] == [
        "list_alternatives", "swap", "set_timing", "set_qty", "remove_or_restore", "explain"]
    swap_spec = next(t for t in tools if t.tool_name == "swap").tool_spec
    assert set(swap_spec["inputSchema"]["json"]["required"]) == {"slot", "candidate_id"}


def test_unavailable_under_mock_mode(monkeypatch):
    monkeypatch.setattr(ra, "MOCK_MODE", True)
    monkeypatch.setattr(ra, "RESULT_AGENT", True)
    assert ra.available() is False
