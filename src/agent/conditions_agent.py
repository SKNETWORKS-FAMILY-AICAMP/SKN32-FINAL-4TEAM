"""조건 대화 에이전트 — Strands Agents SDK.

`POST /session/{id}/message` 의 자유 텍스트를 처리한다. 규칙 추출(`slot_rules`)은 정해진
키워드만 잡아서 "추가 조건·변경 요청"이 조건에 안 실렸다(2026-09-13 회의). 여기서는 LLM 이
슬롯 스키마에 맞춰 **도구 호출**로 조건을 반영하고, 비어 있는 필수 항목을 이어서 묻는다.

경계 (§D-3 "판정·수치는 코드, LLM 은 서술" 유지):
- 쓸 수 있는 필드는 `config/categories/<cat>.yaml` 의 `slot_schema` 뿐이다. enum·타입·nullable 은
  코드(`ConditionDraft`)가 검사하고, 틀리면 도구가 오류 문장을 돌려줘 모델이 고쳐 부르게 한다.
- 에이전트는 DB 를 만지지 않는다. 도구는 `ConditionDraft.patches` 에 모으고 `session_service` 가
  `upsert_condition(origin="extracted")` 으로 적는다 — 규칙 경로와 같은 origin.
- 추천 실행·검증·순위·수치는 그대로 엔진이 한다. 에이전트는 조건 수집과 답변 문장만.
- `available()` 이 False(MOCK_MODE·키 없음·`CONDITIONS_AGENT=0`)면 만들지 않는다. 호출 실패는
  예외로 올리고, 규칙 경로로 바꿀지는 호출자(`session_service`)가 정한다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from src.config import CONDITIONS_AGENT, LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY, USD_KRW_RATE
from src.engine.slot_rules import _parse_won
from src.i18n import Locale, normalize_locale

# 대화로 설정하지 않는 필드 — 사양 파일 첨부(/spec-file)가 채운다
_NOT_CONVERSATIONAL = {"current_specs", "spec_file_name"}
_HISTORY_LIMIT = 20


def available() -> bool:
    return (not MOCK_MODE and CONDITIONS_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


# ── 조건 초안: 도구가 쓰고 서비스가 읽는다 ──────────────────────────────────
MissingFn = Callable[[dict], list[str]]
NextQuestionFn = Callable[[dict], dict | None]


@dataclass
class ConditionDraft:
    category: str
    cat_def: dict
    values: dict                       # 현재 저장된 조건 (읽기 전용으로 취급)
    missing_fn: MissingFn              # 무엇이 필수인지는 규칙(session_service)이 정한다
    next_question_fn: NextQuestionFn
    lang: str = "ko"                   # 이번 턴의 사용자 언어 — 단위 없는 숫자를 달러로 볼지 정한다
    patches: dict = field(default_factory=dict)   # 이번 턴에 바뀐 것만
    _bare_budget: float | None = None  # 이번 턴에 단위 없이 받은 예산 숫자 — currency 가 뒤늦게 오면 다시 해석한다
    trace: list[str] = field(default_factory=list) # 도구 호출 기록 (로그·"추천 과정 보기" 용)

    def question(self, key: str) -> dict | None:
        return next((q for q in self.cat_def.get("question_sets", []) if q["maps_to"] == key), None)

    def merged(self) -> dict:
        return {**self.values, **self.patches}

    def missing(self) -> list[str]:
        return self.missing_fn(self.merged())

    def next_question(self) -> dict | None:
        return self.next_question_fn(self.merged())

    def _status(self) -> str:
        """도구 결과 꼬리 — 모델이 다음에 무엇을 물을지 여기서 읽는다."""
        nq = self.next_question()
        if nq:
            return f" · 남은 필수 항목 {json.dumps(self.missing(), ensure_ascii=False)} · 다음 질문: \"{nq['text']}\""
        return " · 필수 항목 모두 채워짐 — 추천을 받아볼 수 있다고 안내"

    def schema(self) -> dict[str, dict]:
        return {k: v for k, v in (self.cat_def.get("slot_schema") or {}).items()
                if k not in _NOT_CONVERSATIONAL}

    def current(self, key: str):
        return self.patches[key] if key in self.patches else self.values.get(key)

    def _record(self, call: str, result: str) -> str:
        self.trace.append(f"{call} → {result}")
        return result

    def set(self, key: str, raw) -> str:
        call = f"set_condition({key!r}, {raw!r})"
        meta = self.schema().get(key)
        if meta is None:
            return self._record(call, f"오류: '{key}' 는 설정할 수 없는 필드입니다. 가능한 필드: {', '.join(self.schema())}")
        budget_currency: str | None = None
        if key == "budget_max" and isinstance(raw, str) and raw.strip().lower() not in ("", "null", "none"):
            value, budget_currency = _parse_budget(raw, self.lang, self.current("currency"))
            if value is None or value <= 0:
                return self._record(call, f"오류: {key} — 0보다 큰 금액으로 (예: 1500000 · 150만원 · $1,500)")
            bare = raw.replace(",", "").strip()
            self._bare_budget = float(bare) if re.fullmatch(r"\d+(?:\.\d+)?", bare) else None
        elif key == "currency" and self._bare_budget is not None and str(raw).strip().upper() in ("KRW", "USD"):
            # 모델이 "1,500,000 won" 을 '1,500,000' + currency='KRW' 두 호출로 쪼갠다(실측). 단위 없이 받았던 숫자를
            # 이제 온 통화로 다시 해석한다 — 아니면 1,500,000 이 달러로 읽혀 21억 원이 된다.
            cur = str(raw).strip().upper()
            self.patches["budget_max"] = int(round(self._bare_budget * USD_KRW_RATE)) if cur == "USD" else int(self._bare_budget)
            self.patches["currency"] = cur
            b = self.patches["budget_max"]
            shown = usd(b) if cur == "USD" else f"{b:,}원"
            return self._record(call, f"currency = {cur} 반영 · budget_max 를 {shown} 로 다시 해석" + self._status())
        else:
            try:
                value = _coerce(meta, raw)
            except ValueError as exc:
                return self._record(call, f"오류: {key} — {exc}")
        q = self.question(key)
        if meta.get("type") == "list" and q and q.get("none_option"):
            # 목록형 "없음" 은 ["none"] 하나로 — 규칙 경로(slot_rules)·칩 선택(handle_answer)과 같은 표현
            if any(str(x).lower() in ("none", q["none_option"], "없음", "없어요") for x in value):
                value = ["none"]
        self.patches[key] = value
        shown = json.dumps(value, ensure_ascii=False)
        if key == "budget_max" and "currency" in self.schema():
            if budget_currency == "USD":
                # 달러로 말했다(또는 영어 대화의 단위 없는 숫자) — 저장은 원화, 통화는 따로 기록해 답변·표시가 달러를 앞에 두게
                self.patches["currency"] = "USD"
                shown = usd(value)     # 달러만 — 원화 병기 안 함 (사용자가 원화를 명시한 경우만 원화)
            elif isinstance(raw, str) and _KRW_RE.search(raw) and self.current("currency") == "USD":
                self.patches["currency"] = "KRW"       # 달러로 말하던 사용자가 명시적으로 원화를 말했다
        return self._record(call, f"{key} = {shown} 반영" + self._status())

    def clear(self, key: str) -> str:
        call = f"clear_condition({key!r})"
        if key not in self.schema():
            return self._record(call, f"오류: '{key}' 는 설정할 수 없는 필드입니다.")
        self.patches[key] = None
        return self._record(call, f"{key} 비움" + self._status())

    def add_extra(self, text: str) -> str:
        call = f"add_extra_condition({text!r})"
        text = text.strip()
        if not text:
            return self._record(call, "오류: 빈 조건")
        if "extra" not in self.schema():
            return self._record(call, "오류: 이 카테고리는 자유 조건(extra)을 받지 않습니다.")
        items = list(self.current("extra") or [])
        if text not in items:
            items.append(text)
        self.patches["extra"] = items
        return self._record(call, f"extra 에 추가: {text}" + self._status())


_USD_RE = re.compile(r"(?:\$|usd|us\s*dollars?|dollars?|달러|불)", re.I)


def _detect_currency(text: str) -> str | None:
    return "USD" if _USD_RE.search(text) else None


def _parse_money(text: str) -> tuple[int | None, str | None]:
    """(원 단위 정수, 사용자가 말한 통화). '$1,500' · '1500 dollars' · '1.2k USD' → 고정 환율로 원화 환산."""
    if _detect_currency(text) == "USD":
        t = _USD_RE.sub(" ", text).replace(",", "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*(k|thousand)\b", t, re.I)
        usd_amount = float(m.group(1)) * 1_000 if m else None
        if usd_amount is None:
            m = re.search(r"\d+(?:\.\d+)?", t)
            usd_amount = float(m.group(0)) if m else None
        return (int(round(usd_amount * USD_KRW_RATE)) if usd_amount is not None else None), "USD"
    return _parse_amount(text), None


_KRW_RE = re.compile(r"(원|won|krw|만|억)", re.I)


def _parse_budget(raw: str, lang: str = "ko", session_currency: str | None = None) -> tuple[int | None, str | None]:
    """예산 문자열 → (원화 정수, 통화). 달러 표지($·dollars)는 달러. 원·won·만·억은 원화.
    **단위 없는 숫자("1500")는 영어 대화이거나 이미 달러로 말한 사용자면 달러**, 아니면 원화."""
    krw, cur = _parse_money(raw)
    if cur == "USD" or krw is None or _KRW_RE.search(raw):
        return krw, cur
    if lang == "en" or session_currency == "USD":
        return int(round(krw * USD_KRW_RATE)), "USD"      # krw 는 이때 단위 없는 숫자 그대로다
    return krw, None


def usd(krw: int | None) -> str:
    return "-" if krw is None else f"${krw / USD_KRW_RATE:,.0f}"


def _parse_amount(text: str) -> int | None:
    """'1500000' · '1,500,000 won' · '150만원' · '1.5억' · '2.5 million' · '삼백만원' → 원 단위 정수."""
    plain = text.replace(",", "").strip()
    if re.fullmatch(r"-?\d+", plain):
        return int(plain)
    won = _parse_won(text)                      # 만·억·원 (숫자 또는 한글 숫자 단어, 예: 삼백만원)
    if won:
        return won
    low = plain.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(million|mil|m)\b", low)
    if m:
        return int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(thousand|k)\b", low)
    if m:
        return int(float(m.group(1)) * 1_000)
    m = re.search(r"\d{4,}", plain)
    if m:
        return int(m.group(0))
    return None


def _coerce(meta: dict, raw):
    t = meta.get("type")
    s = raw.strip() if isinstance(raw, str) else raw
    if s in (None, "", "null", "none", "None") and meta.get("nullable"):
        return None
    if t == "enum":
        allowed = [v for v in meta.get("values", []) if v is not None]
        for v in allowed:
            if str(v).lower() == str(s).lower():
                return v
        raise ValueError(f"허용값은 {allowed} 중 하나")
    if t in ("int", "money"):          # money: develop 의 baby.yaml 표기 — 저장은 원 단위 정수
        if isinstance(s, bool):
            raise ValueError("정수가 필요")
        if isinstance(s, (int, float)):
            return int(s)
        amount, _ = _parse_money(str(s))
        if amount is not None and (t != "money" or amount > 0):   # money(develop 의 baby 표기)는 0 이하 거부
            return amount
        raise ValueError("원 단위 정수로 (예: 1500000 · 150만원 · $1,500)")
    if t == "bool":
        if isinstance(s, bool):
            return s
        low = str(s).lower()
        if low in ("true", "yes", "1", "예", "네"):
            return True
        if low in ("false", "no", "0", "아니오", "아니요"):
            return False
        raise ValueError("true 또는 false")
    if t == "list":
        if isinstance(s, list):
            items = [str(x).strip() for x in s]
        else:
            text = str(s)
            if text.startswith("["):
                try:
                    items = [str(x).strip() for x in json.loads(text)]
                except json.JSONDecodeError as exc:
                    raise ValueError("JSON 배열 또는 쉼표 구분 목록") from exc
            else:
                items = [x.strip() for x in text.split(",")]
        items = [x for x in items if x]
        if not items:
            raise ValueError("빈 목록")
        return items
    if t == "str":
        return str(s)
    raise ValueError("이 필드는 대화로 설정하지 않습니다")


# ── 도구 ───────────────────────────────────────────────────────────────────
def make_tools(draft: ConditionDraft) -> list:
    from strands import tool

    @tool
    def set_condition(field: str, value: str) -> str:
        """조건 필드 하나를 설정한다. 사용자가 명시적으로 말한 값만 넣는다.
        Set one condition field. Game titles go to field "games" (comma-separated), a stated use ("gaming PC") also sets "purpose".

        Args:
            field: 시스템 프롬프트의 필드 목록에 있는 키 (예: purpose, budget_max)
            value: 값. enum 은 허용값 코드 그대로, 금액은 **통화 단위까지 사용자가 말한 그대로**("150만원",
                   "1,500,000 won", "$1,500", "1500 dollars" — 환산은 코드가 한다. 단위를 떼고 숫자만 넘기지 말 것),
                   목록은 쉼표로 구분, bool 은 true/false, 지우려면 "null".
                   Amounts: pass the unit/symbol the user used ("1,500,000 won", "$1,200"); never strip it.
        """
        return draft.set(field, value)

    @tool
    def add_extra_condition(text: str) -> str:
        """필드 목록에 없는 구체적 요구(예: "흰색 케이스", "RGB 없이", "무선 키보드 포함")를
        추가 조건으로 남긴다. 필드가 있는 값(게임 제목 → games, 해상도 → resolution 등)은
        여기가 아니라 set_condition 으로 넣는다. 판단·추천은 하지 않고 기록만 한다.
        Only for requests that have NO field (e.g. "white case", "no RGB"). Game titles, resolution, budget,
        priority are fields — use set_condition for those, never this tool.

        Args:
            text: 사용자의 요구를 짧은 한 구절로
        """
        return draft.add_extra(text)

    @tool
    def clear_condition(field: str) -> str:
        """사용자가 조건을 취소·변경하려 할 때 필드를 비운다. 새 값이 있으면 set_condition 을 쓴다.

        Args:
            field: 비울 필드 키
        """
        return draft.clear(field)

    return [set_condition, add_extra_condition, clear_condition]


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def _field_lines(draft: ConditionDraft) -> list[str]:
    """필드 한 줄씩: 키·타입·뜻, 그리고 질문 칩의 선택지→값 매핑 (모델이 코드값을 알게)."""
    labels = {f["key"]: f["label"] for f in draft.cat_def.get("fields", []) if "label" in f}
    lines = []
    for key, meta in draft.schema().items():
        q = draft.question(key)
        desc = f"{meta.get('type')}"
        if meta.get("type") == "enum":
            desc += " " + json.dumps([v for v in meta["values"] if v is not None], ensure_ascii=False)
        if meta.get("nullable"):
            desc += ", nullable"
        if meta.get("type") == "list":
            desc += " (항목 여러 개, 쉼표 구분)"
        label = labels.get(key) or (q["label"] if q else key)
        line = f"- {key}: {desc} — {label}"
        if q and q.get("options"):
            if q.get("values"):
                pairs = [f"{o}→{json.dumps(v, ensure_ascii=False)}" for o, v in zip(q["options"], q["values"]) if v is not None]
                line += ". 선택지: " + ", ".join(pairs)
                if meta.get("type") in ("int", "money"):
                    line += " (정확한 값을 알면 그 값)"
            else:
                line += ". 선택지: " + ", ".join(q["options"])
            if q.get("none_option"):
                line += f'. "{q["none_option"]}" 이면 값은 none'
        lines.append(line)
    return lines


_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")


def _chip_codes(cat_def: dict) -> set[str]:
    """칩 선택이 사용자 메시지로 남기는 값들("office", "value", "CPU") — 언어 판별에서 뺀다."""
    codes: set[str] = {"none"}
    for meta in (cat_def.get("slot_schema") or {}).values():
        codes.update(str(v) for v in meta.get("values", []) if v is not None)
    for q in cat_def.get("question_sets", []):
        codes.update(str(v) for v in q.get("values", []) if v is not None)
        codes.update(str(o) for o in q.get("options", []))
    return codes


def _reply_language(text: str, history: list[dict] = (), chip_codes: set[str] = frozenset()) -> str:
    """마지막 메시지의 글자로 판별. 숫자만("100000")이면 이전 메시지(양쪽 역할)를 거슬러 본다.

    칩 선택은 "office" 같은 코드값이 user 메시지로 남아 영어로 오판하므로 건너뛴다. 아무것도 없으면 한국어.
    """
    def is_chip(t: str) -> bool:
        parts = [x.strip() for x in t.split(",")]
        return bool(parts) and all(x in chip_codes for x in parts)

    candidates = [text] + [r["content"] for r in reversed(list(history))
                           if not (r.get("role") == "user" and is_chip(r["content"]))]
    for t in candidates:
        if _HANGUL.search(t):
            return "ko"
        if _LATIN.search(t):
            return "en"
    return "ko"


def system_prompt(
    draft: ConditionDraft,
    user_text: str = "",
    history: list[dict] = (),
    locale: Locale | None = None,
) -> str:
    current = {k: draft.current(k) for k in draft.schema() if draft.current(k) not in (None, [], "")}
    if current.get("currency") == "USD" and isinstance(current.get("budget_max"), int):
        current["budget_max"] = usd(current["budget_max"])
    # 턴 시작 시점의 '다음 질문' 을 여기 박으면 모델이 도구로 채운 뒤에도 그 질문을 또 붙인다(실측 2회).
    # 도구 결과에 다시 계산한 '다음 질문' 이 실리니 그것만 따르게 한다.
    ask = ("도구를 부른 뒤에는 **마지막 도구 결과의 '다음 질문'** 을 그대로 물어 답변을 맺습니다 (화면이 그 항목의 "
           "선택지를 함께 보여줍니다). 마지막 도구 결과가 '모두 채워짐' 이면 질문을 붙이지 않습니다. "
           "도구를 하나도 안 불렀으면 '비어 있는 필수 항목' 의 첫 번째를 묻습니다.")
    return "\n".join([
        f"당신은 TrueFit(목적성 쇼핑 플래너)의 조건 수집 도우미입니다. 카테고리: {draft.cat_def.get('label', draft.category)}.",
        "사용자의 말에서 아래 필드에 해당하는 값을 찾아 set_condition 으로 반영하고, 필드에 없는 구체적 요구는",
        "add_extra_condition 으로 남깁니다. 취소·변경 요청은 clear_condition 또는 새 값의 set_condition 으로 처리합니다.",
        "",
        "필드 (키: 타입 [허용값] — 뜻):",
        *_field_lines(draft),
        "",
        f"현재 값: {json.dumps(current, ensure_ascii=False)}",
        f"비어 있는 필수 항목: {json.dumps(draft.missing(), ensure_ascii=False)}",
        "",
        "규칙:",
        "1. 사용자가 말하지 않은 값을 추측해서 넣지 않습니다. 애매하면 되묻습니다. 도구가 '오류:' 를 돌려주면 값을 고쳐 다시 부릅니다.",
        "2. 필드에 맞는 값(예: 게임 제목 → games, 해상도 → resolution)은 add_extra_condition 이 아니라 그 필드에 넣습니다. "
        "'게임용'·'게임 위주'·'작업용'·'사무용' 처럼 용도가 드러나면 games 와 별개로 purpose 도 반드시 설정합니다.",
        "3. 답변은 2문장 이내. 반영한 내용을 짧게 확인합니다. " + ask,
        "4. 필수 항목이 모두 채워졌으면 '이 조건으로 추천을 받아볼 수 있다'고 안내하고 추가 조건이 있으면 말해 달라고 합니다.",
        "5. 값을 바꿀 때는 clear_condition 없이 set_condition 에 새 값만 넣습니다. clear 는 '취소'·'빼 주세요' 에만 씁니다.",
        "6. 제품 추천·가격·성능·호환성 판단을 하지 않습니다. 그건 다음 단계의 엔진이 합니다.",
        "7. 금액: 사용자가 달러로 말했거나 currency 가 USD 면 도구 결과의 달러 금액만 씁니다 — 원화(₩·KRW·원)로 바꾸거나 병기하지 않습니다. "
        "달러 얘기가 없었으면 원화만 씁니다. 금액을 새로 계산하지 않습니다.",
        "",
        ("답변 언어: 한국어 존댓말." if (
            normalize_locale(locale) == "ko-KR" if locale is not None
            else _reply_language(user_text, history, _chip_codes(draft.cat_def)) == "ko"
        )
         else "Reply language: English. Write the entire reply in English, including the closing question."),
    ])


def _history(rows: list[dict], limit: int = _HISTORY_LIMIT) -> list[dict]:
    """DB 대화 행 → Strands messages. 마지막 system 행(조건 초기화) 이후만, 같은 역할 연속은 합친다."""
    cut = 0
    for i, r in enumerate(rows):
        if r["role"] == "system":
            cut = i + 1
    msgs: list[dict] = []
    for r in rows[cut:]:
        if r["role"] not in ("user", "assistant"):
            continue
        if msgs and msgs[-1]["role"] == r["role"]:
            msgs[-1]["content"][0]["text"] += "\n" + r["content"]
        else:
            msgs.append({"role": r["role"], "content": [{"text": r["content"]}]})
    msgs = msgs[-limit:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


# ── 실행 ───────────────────────────────────────────────────────────────────
@dataclass
class TurnResult:
    reply: str
    patches: dict
    trace: list[str]


def _model():
    from strands.models.openai import OpenAIModel
    return OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL,
                       params={"temperature": 0.2})


def run_turn(category: str, cat_def: dict, values: dict, history: list[dict], text: str,
             *, missing_fn: MissingFn, next_question_fn: NextQuestionFn,
             locale: Locale | None = None) -> TurnResult:
    """한 턴 실행. history 는 이번 사용자 메시지를 제외한 DB 대화 행.

    `missing_fn`·`next_question_fn` 은 규칙(`session_service`)이다 — 무엇이 필수이고 다음에 무엇을
    물을지는 에이전트가 정하지 않는다. 도구 결과마다 다시 계산해 모델에 돌려준다.
    """
    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    draft = ConditionDraft(category=category, cat_def=cat_def, values=dict(values),
                           missing_fn=missing_fn, next_question_fn=next_question_fn,
                           lang=_reply_language(text, history, _chip_codes(cat_def)))
    agent = Agent(
        model=_model(),
        system_prompt=system_prompt(draft, text, history, locale),
        tools=make_tools(draft),
        messages=_history(history),
        tool_executor=SequentialToolExecutor(),   # 도구들이 한 draft 를 순서대로 고친다
        callback_handler=None,          # 기본 핸들러는 stdout 에 스트리밍한다
    )
    result = agent(text)
    # 사용자가 쓰는 언어를 조건으로 남긴다 — [3-C]·[5]·결과 조립이 읽어 문장 언어를 맞춘다 (패널엔 안 보임)
    if "language" in draft.schema():
        detected = _reply_language(text, history, _chip_codes(cat_def))
        if draft.values.get("language") != detected:
            draft.patches["language"] = detected
    return TurnResult(reply=str(result).strip(), patches=dict(draft.patches), trace=list(draft.trace))
