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


# ── 수치 가드 ──────────────────────────────────────────────────────────────
def test_numbers_normalise_commas_percent_and_product_names():
    assert ra._numbers("총액 1,457,000원 · 예산 비중 18% · RTX 5090 · DDR4-3600 · 1TB · 신뢰도 94점") == {
        "1457000", "18", "5090", "4", "3600", "1", "94"}


def test_reply_within_accepts_input_numbers_and_rejects_invented():
    prompt = "- GPU: RX 7600 · 525,000원 × 1\n예산 상한: 1,500,000원 · 총액: 1,457,000원 · 잔여: 43,000원"
    ok, out = ra._reply_within("총액은 1457000원이고 예산이 43,000원 남았습니다.", [prompt])
    assert ok and not out
    ok, out = ra._reply_within("이 GPU는 약 620,000원 정도의 성능입니다.", [prompt])
    assert not ok and out == {"620000"}
    ok, _ = ra._reply_within("교체했습니다 (+84,000원).", [prompt, "swap → … (+84,000원)"])   # 도구 결과의 숫자도 허용
    assert ok


def test_guarded_reply_prefers_changes_then_prefetched_then_template():
    s = _session()
    s.changed = True
    s.trace = ["prefetch:explain('CPU') → …", "set_qty('저장장치', '2') → 저장장치: selected=True qty=2 timing=now · 총액 780,000원 · 예산 잔여 720,000원"]
    out = ra._guarded_reply(s, "")
    assert out.startswith("적용된 변경: 저장장치: selected=True qty=2 timing=now") and "총액 780,000원" in out
    s2 = _session()
    assert ra._guarded_reply(s2, "CPU X 255,000원\n저장된 추천 이유: …") == "CPU X 255,000원 저장된 추천 이유: …"
    assert ra._guarded_reply(_session(), "").startswith("구성표 기준으로만 답할 수 있어요")


def test_amounts_are_dollar_first_when_session_currency_is_usd(monkeypatch):
    monkeypatch.setattr("src.agent.conditions_agent.USD_KRW_RATE", 1400.0)
    monkeypatch.setitem(ra._CURRENCY, "code", "USD")
    assert ra._won(1_457_000) == "$1,041 (1,457,000원)"
    p = ra.system_prompt(_result(), "am I within budget?", [])
    assert "총액: $557 (780,000원)" in p and "8. 금액은 달러를 앞에" in p
    monkeypatch.setitem(ra._CURRENCY, "code", "KRW")
    assert ra._won(1_457_000) == "1,457,000원"
    assert "달러를 앞에" not in ra.system_prompt(_result(), "예산 안이야?", [])
