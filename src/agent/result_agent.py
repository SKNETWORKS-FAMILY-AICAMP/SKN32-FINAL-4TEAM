"""결과 화면 대화 에이전트 — Strands Agents SDK.

`POST /session/{id}/result-message` 의 자유 텍스트를 처리한다. 기존 규칙 경로(`handle_result_message`)는
"슬롯 이름 + 저렴/좋은" 만 알아듣고 최저가/최고가 후보로 바꿨다. 여기서는 LLM 이 구성표를 읽고
**기존 서비스 함수를 도구로** 불러 후보 조회·교체·담기/빼기·수량·구매 시점을 처리하고, "왜 이거?" 에는
저장된 근거(추천 이유·검증 쟁점·리뷰 관측)만 돌려준다.

경계:
- 도구는 `recommendation_service` 의 `list_alternatives`·`swap_item`·`patch_item` 을 감싼다. 최적화·검증·
  순위는 그대로 엔진 몫이고 에이전트는 무엇을 부를지만 고른다.
- 판정 금지 — "이 리뷰 조작인가", "이 부품이 더 좋은가" 를 에이전트가 정하지 않는다(결정 0001).
  `explain` 은 관측·쟁점·저장된 이유를 그대로 옮긴다.
- 교체 뒤 호환·검증은 재실행되지 않는다. 지금 엔진의 link_check 는 고정값이라(stage4) 코드도 못 하므로
  도구 결과에 그 사실을 적어 모델이 사용자에게 말하게 한다. 재계산은 화면의 "다른 구성 보기".
- 도구는 순차 실행(`SequentialToolExecutor`) — 요청 스레드의 psycopg 연결 하나를 같이 쓴다.
- 대화 이력은 프로세스 메모리(run_id 별 최근 N턴)에만 둔다. 결과 화면 채팅은 서버에 저장되지 않는
  계약이라 재시작하면 사라진다. "두 번째 걸로" 같은 이어 말하기는 이 이력으로 통한다.
- `available()` 이 False(MOCK_MODE·키 없음·`RESULT_AGENT=0`)면 규칙 경로.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from uuid import UUID

from src.agent.conditions_agent import _model, _reply_language
from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY, RESULT_AGENT
from src.errors import NotFound

log = logging.getLogger(__name__)

_HISTORY_TURNS = 8
_HISTORY: dict[str, deque] = {}     # run_id → deque[(user, assistant)]


def available() -> bool:
    return (not MOCK_MODE and RESULT_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


def _won(n: int | None) -> str:
    return "-" if n is None else f"{n:,}원"


# ── 세션: 도구가 공유하는 연결·상태 ────────────────────────────────────────
@dataclass
class ResultSession:
    conn: object
    revision_id: UUID
    result: dict                                  # get_stored_result 스냅샷 (도구가 바꾸면 갱신)
    trace: list[str] = field(default_factory=list)
    changed: bool = False

    def _record(self, call: str, out: str) -> str:
        self.trace.append(f"{call} → {out[:160]}")
        return out

    def refresh(self) -> None:
        from src.services.recommendation_service import get_stored_result
        self.result = get_stored_result(self.conn, self.revision_id)

    def item(self, slot: str) -> dict | None:
        s = slot.strip()
        for it in self.result.get("items", []):
            if it["slot"].lower() == s.lower() or it["slot_label"] == s:
                return it
        return None

    def _perf_min_by_slot(self) -> dict[str, int]:
        from src.repo.plan_repo import PlanRepo
        full = PlanRepo(self.conn).load_full(self.revision_id)
        node_slot = {n["id"]: n["template_key"] for n in full.get("nodes", [])}
        out = {}
        for r in full.get("requirements", []):
            spec = r.get("match_spec") or {}
            if spec.get("perf_tier_min") is not None and r["node_id"] in node_slot:
                out[node_slot[r["node_id"]]] = int(spec["perf_tier_min"])
        return out

    # ── 도구 본체 ──
    def list_alternatives(self, slot: str) -> str:
        from src.services.recommendation_service import list_alternatives
        call = f"list_alternatives({slot!r})"
        it = self.item(slot)
        if it is None:
            return self._record(call, f"오류: '{slot}' 슬롯이 없습니다. 슬롯: {[i['slot'] for i in self.result['items']]}")
        rows = list_alternatives(self.conn, self.revision_id, UUID(it["item_id"]))["items"]
        if not rows:
            return self._record(call, f"{it['slot']}: 다른 후보 없음")
        pmin = self._perf_min_by_slot().get(it["slot"])
        lines = [f"{it['slot']} 현재: {it['product']['name']} {_won(it['price'])}"
                 + (f" · 요구 성능 티어 ≥ {pmin}" if pmin is not None else "")]
        for i, r in enumerate(rows, 1):
            tier = None
            if r["product"].get("spec_summary", "") and "티어" in r["product"]["spec_summary"]:
                try:
                    tier = int(r["product"]["spec_summary"].split("티어")[1])
                except ValueError:
                    tier = None
            flag = " ⚠ 요구 사양 미달" if (pmin is not None and tier is not None and tier < pmin) else ""
            lines.append(f"{i}. candidate_id={r['candidate_id']} · {r['product']['name']} · {_won(r['price'])}"
                         f" ({r['price_delta']:+,}원) · {r['label']}"
                         + (f" · 성능 티어 {tier}" if tier is not None else "") + flag)
        return self._record(call, "\n".join(lines))

    def swap(self, slot: str, candidate_id: str) -> str:
        from src.services.recommendation_service import swap_item
        call = f"swap({slot!r}, {candidate_id!r})"
        it = self.item(slot)
        if it is None:
            return self._record(call, f"오류: '{slot}' 슬롯이 없습니다.")
        try:
            cid = UUID(candidate_id)
        except ValueError:
            return self._record(call, "오류: candidate_id 는 list_alternatives 가 돌려준 값이어야 합니다.")
        before = it["product"]["name"], it["price"]
        try:
            self.result = swap_item(self.conn, self.revision_id, UUID(it["item_id"]), cid)
        except NotFound as exc:
            return self._record(call, f"오류: {exc}")
        self.changed = True
        after = self.item(it["slot"])
        t = self.result["totals"]
        return self._record(call, (
            f"{it['slot']} 교체: {before[0]} {_won(before[1])} → {after['product']['name']} {_won(after['price'])}"
            f" · 총액 {_won(t['selected_price'])} · 예산 잔여 {_won(t['budget_remaining'])}"
            + (" · ⚠ 예산 초과" if t["over_budget"] else "")
            + " · 호환·검증은 재실행되지 않음(재계산은 화면의 '다른 구성 보기')"))

    def set_item(self, slot: str, selected: str = "", qty: str = "", timing: str = "") -> str:
        from src.services.recommendation_service import patch_item
        call = f"set_item({slot!r}, selected={selected!r}, qty={qty!r}, timing={timing!r})"
        it = self.item(slot)
        if it is None:
            return self._record(call, f"오류: '{slot}' 슬롯이 없습니다.")
        sel = None if selected == "" else selected.strip().lower() in ("true", "1", "yes")
        q = None
        if qty != "":
            if not qty.strip().isdigit() or not 1 <= int(qty) <= 99:
                return self._record(call, "오류: qty 는 1~99 정수")
            q = int(qty)
        tm = None
        if timing != "":
            if timing not in ("now", "soon", "later"):
                return self._record(call, "오류: timing 은 now/soon/later")
            tm = timing
        if sel is None and q is None and tm is None:
            return self._record(call, "오류: 바꿀 값이 없습니다")
        self.result = patch_item(self.conn, self.revision_id, UUID(it["item_id"]), selected=sel, qty=q, timing=tm)
        self.changed = True
        after = self.item(it["slot"])
        t = self.result["totals"]
        return self._record(call, (
            f"{it['slot']}: selected={after['selected']} qty={after['qty']} timing={after['timing']}"
            f" · 총액 {_won(t['selected_price'])} · 예산 잔여 {_won(t['budget_remaining'])}"
            + (" · ⚠ 예산 초과" if t["over_budget"] else "")))

    def explain(self, slot: str) -> str:
        from src.services import review_service
        call = f"explain({slot!r})"
        it = self.item(slot)
        if it is None:
            return self._record(call, f"오류: '{slot}' 슬롯이 없습니다.")
        lines = [f"{it['slot']} {it['product']['name']} {_won(it['price'])}"
                 + (f" · {it['product']['spec_summary']}" if it['product'].get('spec_summary') else "")
                 + (f" · 예산 비중 {it['budget_share']:.0%}" if it.get("budget_share") else "")]
        r = it.get("reason") or {}
        lines.append("저장된 추천 이유: " + (r.get("text") if r.get("status") == "ready" and r.get("text")
                                       else f"(없음 — 상태 {r.get('status')})"))
        # engine.candidate_evidence 는 0012 에서 삭제됐다(engine_repo.get_candidate_evidence 는 옛 코드) — 인용은 못 낸다
        issues = (self.result.get("verification") or {}).get("issues") or []
        if issues:
            lines.append("세트 검증 쟁점(전체 구성 기준): " + " | ".join(f"[{i['axis']}] {i['text']}" for i in issues))
        try:
            s = review_service.get_summary(it["product"]["product_key"])
            obs = [x["text"] for x in s.summaries] if s.summaries else []
            lines.append("리뷰 관측(상품 단위, 개별 리뷰 진위 아님): " + (" | ".join(obs) if obs else s.data_notice))
        except NotFound:
            lines.append("리뷰 관측: 없음")
        return self._record(call, "\n".join(lines))


# ── 도구 등록 ──────────────────────────────────────────────────────────────
def make_tools(s: ResultSession) -> list:
    from strands import tool

    @tool
    def list_alternatives(slot: str) -> str:
        """슬롯의 다른 후보를 가격순으로 보여준다. 교체 전에 반드시 이걸로 candidate_id 를 확인한다.

        Args:
            slot: 슬롯 이름 (예: GPU, CPU, RAM, 메인보드, 저장장치, 파워, 케이스, 쿨러)
        """
        return s.list_alternatives(slot)

    @tool
    def swap(slot: str, candidate_id: str) -> str:
        """슬롯의 부품을 다른 후보로 교체한다. candidate_id 는 list_alternatives 결과의 값.

        Args:
            slot: 슬롯 이름
            candidate_id: list_alternatives 가 돌려준 candidate_id
        """
        return s.swap(slot, candidate_id)

    @tool
    def set_timing(slot: str, timing: str) -> str:
        """부품의 구매 시점만 바꾼다. "나중에 살게/미루자" → "later", "곧" → "soon", "지금" → "now".
        장바구니에는 그대로 남는다 — 빼는 게 아니다.

        Args:
            slot: 슬롯 이름
            timing: "now" / "soon" / "later"
        """
        return s.set_item(slot, timing=timing)

    @tool
    def set_qty(slot: str, qty: str) -> str:
        """부품의 수량만 바꾼다 ("SSD 2개로").

        Args:
            slot: 슬롯 이름
            qty: 1~99
        """
        return s.set_item(slot, qty=qty)

    @tool
    def remove_or_restore(slot: str, keep: str) -> str:
        """부품을 장바구니에서 빼거나("빼줘", "필요 없어" → keep="false") 다시 담는다("다시 담아줘" → keep="true").
        "나중에 살게" 는 여기가 아니라 set_timing 이다.

        Args:
            slot: 슬롯 이름
            keep: "false" = 뺌, "true" = 담음
        """
        return s.set_item(slot, selected=keep)

    @tool
    def explain(slot: str) -> str:
        """왜 이 부품인지 묻는 질문("왜 이 CPU야?", "이거 괜찮아?", "리뷰 어때?")에 답하기 위해 부른다.
        저장된 추천 이유, 예산 비중, 근거 인용, 세트 검증 쟁점, 리뷰 관측(상품 단위)을 그대로 돌려준다.
        판정은 하지 않는다.

        Args:
            slot: 슬롯 이름
        """
        return s.explain(slot)

    return [list_alternatives, swap, set_timing, set_qty, remove_or_restore, explain]


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def _build_table(result: dict) -> str:
    rows = []
    for it in result.get("items", []):
        mark = "" if it["selected"] else " (빼둠)"
        r = it.get("reason") or {}
        reason = f" · 추천 이유: {r['text']}" if r.get("status") == "ready" and r.get("text") else ""
        rows.append(f"- {it['slot']}: {it['product']['name']} · {_won(it['price'])} × {it['qty']}"
                    f" · 시점 {it['timing']}{mark} · 다른 후보 {it['alternatives_count']}개{reason}")
    return "\n".join(rows) or "(부품 없음)"


_WHY = ("왜", "이유", "근거", "괜찮", "믿을", "어때", "리뷰", "why", "reason", "review", "good", "ok?")


def _prefetch_explanations(session: ResultSession, text: str) -> str:
    """'왜 이 CPU야?' 류는 모델이 explain 을 안 부르고 답하는 일이 있어서, 코드가 먼저 조회해 프롬프트에 싣는다.
    슬롯을 못 찾으면 담긴 부품 전부. 판단은 여전히 안 한다 — 저장된 사실을 옮길 뿐."""
    from src.services.recommendation_service import _match_slot
    low = text.lower()
    if not any(w in low for w in _WHY):
        return ""
    slots = [it["slot"] for it in session.result.get("items", [])]
    hit = _match_slot(text, set(slots))
    targets = [hit] if hit else [it["slot"] for it in session.result.get("items", []) if it["selected"]]
    out = "\n\n".join(session.explain(sl) for sl in targets)
    session.trace[:] = [f"prefetch:{t}" for t in session.trace]   # 도구 호출과 구분
    return out


def system_prompt(result: dict, user_text: str, history: list[dict], prefetched: str = "") -> str:
    t = result.get("totals") or {}
    v = result.get("verification") or {}
    issues = " | ".join(f"[{i['axis']}] {i['text']}" for i in (v.get("issues") or [])) or "없음"
    return "\n".join([
        "당신은 TrueFit 추천 결과 화면의 도우미입니다. 아래 구성표를 읽고 사용자의 요청을 도구로 처리하거나 질문에 답합니다.",
        "",
        f"카테고리: {result.get('category')} · 조건: {result.get('conditions_summary') or '-'}",
        f"예산 상한: {_won(result.get('budget_max'))} · 총액: {_won(t.get('selected_price'))} · 잔여: {_won(t.get('budget_remaining'))}"
        + (" · ⚠ 예산 초과" if t.get("over_budget") else ""),
        f"세트 검증 신뢰도: {v.get('confidence')} · 쟁점: {issues}",
        "구성표:",
        _build_table(result),
        "",
        "규칙:",
        "1. 부품을 바꾸려면 먼저 list_alternatives 로 후보와 candidate_id 를 확인하고 swap 을 부릅니다. candidate_id 를 지어내지 않습니다.",
        "2. 사용자가 방향만 말하면('더 싼 걸로', '한 단계 위로') 목록에서 가장 가까운 후보를 고릅니다. '⚠ 요구 사양 미달' 표시가 있는 후보는 고르지 말고 그 사실을 알립니다. "
        "후보가 둘 이상 애매하면 이름·가격을 나열하고 고르게 합니다.",
        "3. '나중에 살게/미루자' → set_timing(later). '빼줘/필요 없어' → remove_or_restore(false). '2개로' → set_qty. "
        "한 문장에 부품 여러 개가 나오면 각 부품에 그 부품 앞뒤에 붙은 요청만 적용하고 도구를 따로 부릅니다.",
        "4. '왜 이거?', '이유가 뭐야?', '이거 괜찮아?', '믿을 만해?' 처럼 근거를 묻는 말에는 **반드시 explain 을 먼저 부르고** 그 내용만 전합니다. "
        "explain 을 부르기 전에 '이유를 확인할 수 없다'고 답하지 않습니다. 저장된 추천 이유가 없어도 explain 이 준 가격·예산 비중·검증 쟁점·리뷰 관측은 전합니다. "
        "부품의 좋고 나쁨, 리뷰의 진위, 호환 여부를 스스로 판정하지 않고, explain 에 없는 수치·사실을 만들지 않습니다.",
        "5. 답변은 3문장 이내. 바뀐 것과 총액·예산 잔여를 말하고, 도구 결과에 '예산 초과'나 '호환·검증은 재실행되지 않음' 이 있으면 그것도 한 번 언급합니다. "
        "호환·검증에 대해 '문제 없다'고 단정하지 않습니다 — 재실행 여부만 말합니다.",
        "6. 전체를 다시 짜 달라는 요청('처음부터', '다른 구성')은 도구가 없습니다 — 화면의 '다른 구성 보기' 버튼을 안내합니다.",
        "7. 구성표에 없는 슬롯이나 상품을 만들지 않습니다. '죄송'·'확인할 수 없다' 로 시작하지 않습니다 — 아는 사실부터 말합니다.",
        *(["", "사용자 질문에 대해 미리 조회한 근거 (이걸로 답합니다. 더 필요하면 explain):", prefetched] if prefetched else []),
        "",
        ("답변 언어: 한국어 존댓말." if _reply_language(user_text, history) == "ko"
         else "Reply language: English. Write the entire reply in English."),
    ])


def _history_messages(run_id: str) -> list[dict]:
    msgs = []
    for u, a in _HISTORY.get(run_id, ()):
        msgs.append({"role": "user", "content": [{"text": u}]})
        msgs.append({"role": "assistant", "content": [{"text": a}]})
    return msgs


# ── 실행 ───────────────────────────────────────────────────────────────────
@dataclass
class TurnResult:
    reply: str
    result: dict
    trace: list[str]
    changed: bool


def run_turn(conn, revision_id: UUID, result: dict, text: str) -> TurnResult:
    """한 턴. `result` 는 호출 시점의 get_stored_result. 도구가 바꾸면 갱신된 것을 돌려준다."""
    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    run_id = result["run_id"]
    hist_rows = [{"role": "user", "content": u} for u, _ in _HISTORY.get(run_id, ())]
    session = ResultSession(conn=conn, revision_id=revision_id, result=result)
    prefetched = _prefetch_explanations(session, text)
    agent = Agent(
        model=_model(),
        system_prompt=system_prompt(result, text, hist_rows, prefetched),
        tools=make_tools(session),
        messages=_history_messages(run_id),
        tool_executor=SequentialToolExecutor(),   # 도구들이 요청 스레드의 DB 연결 하나를 같이 쓴다
        callback_handler=None,
    )
    try:
        reply = str(agent(text)).strip()
    except Exception:
        if not session.changed:
            raise                      # 아무것도 안 바꿨으면 호출자가 규칙 경로로
        # 도구가 이미 구성표를 바꿨다 — 규칙 경로가 또 바꾸면 안 되니 바뀐 것만 알린다
        log.exception("result agent failed after tool writes; reporting trace")
        reply = "요청을 처리하다 답변 생성에 실패했어요. 적용된 변경: " + " / ".join(session.trace)
    _HISTORY.setdefault(run_id, deque(maxlen=_HISTORY_TURNS)).append((text, reply))
    if session.changed:
        session.refresh()
    return TurnResult(reply=reply, result=session.result, trace=list(session.trace), changed=session.changed)
