"""조립 가이드 에이전트 — Strands Agents SDK.

확정/추천된 부품 목록을 받아 조립 순서·주의사항 가이드를 만든다. `src/agent/conditions_agent.py`와
같은 경계 원칙을 따른다:

- 조립 **순서**는 코드가 고정한다(`ASSEMBLY_ORDER`) — 일반적인 PC 조립 순서는 의견이 아니라
  관행이라, 에이전트가 순서를 새로 만들거나 단계를 빼먹지 않는다.
- 각 단계 안내는 `search_guide` 도구(= `src/rag/care_guides.py`의 RAG 검색)가 찾은 내용만
  쓴다. 검색 결과가 없으면 "특별히 확인할 점 없음"이라고 정직하게 쓰고, 없는 주의사항을
  지어내지 않는다.
- `available()`이 False(MOCK_MODE·키 없음·`ASSEMBLY_GUIDE_AGENT=0`)면 규칙 기반 폴백을 쓴다 —
  검색 자체는 그대로 실제로 하고, 문장만 템플릿이다("[3-C] 문장 생성 실패는 신뢰도에 영향을
  주지 않는다"는 이 프로젝트의 원칙과 같다 — 여기서도 에이전트 실패가 가이드 자체를 막지 않는다).
"""
from __future__ import annotations

from src.config import ASSEMBLY_GUIDE_AGENT, LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.rag.care_guides import search_care_guide

# 일반적인 PC 조립 순서(케이스 준비 → 전원 → 메인보드 계열 → 확장 카드 → 정리). 의견이 아니라 관행이다.
ASSEMBLY_ORDER = ["케이스", "파워", "메인보드", "CPU", "쿨러", "RAM", "저장장치", "GPU"]


def available() -> bool:
    return (not MOCK_MODE and ASSEMBLY_GUIDE_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


def _ordered_items(items: list[dict]) -> list[dict]:
    """items(슬롯당 하나)를 표준 조립 순서로 정렬. 순서표에 없는 슬롯은 등장 순서대로 맨 뒤에."""
    rank = {slot: i for i, slot in enumerate(ASSEMBLY_ORDER)}
    return sorted(items, key=lambda it: rank.get(it["slot"], len(ASSEMBLY_ORDER)))


def build_guide_fallback(ordered_items: list[dict]) -> str:
    """규칙 기반 폴백 — 검색은 실제로 하되 문장은 템플릿. 에이전트 미가용 시 이걸 쓴다."""
    lines = []
    for i, it in enumerate(ordered_items, start=1):
        name = it["product"]["name"]
        hits = search_care_guide(f"{it['slot']} {name} 조립 시 확인할 점", k=1)
        note = hits[0]["text"] if hits else "특별히 확인할 점은 없습니다."
        lines.append(f"{i}. {it['slot']} — {name}\n   {note}")
    return "\n".join(lines)


def make_tools() -> list:
    from strands import tool

    @tool
    def search_guide(query: str) -> str:
        """부품 사용 가이드·주의사항 문서에서 질의와 가장 관련 있는 내용을 찾는다.

        Args:
            query: 찾고 싶은 내용 — 부품명 + 확인하고 싶은 것 (예: "그래픽카드 전력 확인")
        """
        hits = search_care_guide(query, k=1)
        return hits[0]["text"] if hits else "관련된 가이드를 찾지 못했습니다."

    return [search_guide]


def _model():
    from strands.models.openai import OpenAIModel

    return OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL,
                       params={"temperature": 0.2})


def _system_prompt(ordered_items: list[dict], lang: str = "ko") -> str:
    lines = [f"{i}. {it['slot']}: {it['product']['name']}" for i, it in enumerate(ordered_items, start=1)]
    language_line = (
        "한국어 존댓말로 답합니다."
        if lang != "en"
        else "Reply entirely in English, including step titles and every sentence — "
             "even though the guide docs you find via search_guide are in Korean, "
             "translate them faithfully into English rather than quoting the Korean."
    )
    return "\n".join([
        "당신은 TrueFit에서 확정된 부품 목록으로 조립 가이드를 작성하는 도우미입니다.",
        "",
        "아래는 이미 정해진 조립 순서와 부품입니다 — 순서를 바꾸거나 단계를 빼먹지 않습니다:",
        *lines,
        "",
        "각 단계마다 search_guide 도구로 그 부품에 확인할 점이 있는지 찾아보고, 찾은 내용을",
        "그대로 반영해 1~2문장으로 안내합니다. 검색 결과가 없거나 그 부품과 관련 없으면",
        "\"특별히 확인할 점은 없습니다\"라고 정직하게 씁니다 — 없는 내용을 지어내지 않습니다.",
        "",
        "출력은 번호를 매긴 단계 목록으로, 각 단계는 '슬롯 — 부품명' 제목과 안내 문장으로",
        "구성합니다. 순서·부품명·슬롯 이름은 위에 주어진 그대로 씁니다.",
        language_line,
    ])


def build_guide(items: list[dict], lang: str = "ko") -> dict:
    """{"status": "ready", "text": str}. 품목이 없으면만 다른 status.

    에이전트가 미가용이거나 실패하면 규칙 폴백으로 내려간다 — 이 기능은 [3-C]/[5]처럼
    "문장 생성 실패가 결과 자체를 막지 않는다"는 원칙을 따른다. 검색(RAG)은 폴백에서도
    실제로 수행되므로, 사용자에게 보이는 조립 가이드는 항상 실제 데이터를 인용한다.

    lang="en"은 에이전트 경로에서만 적용된다 — 폴백(build_guide_fallback)은 근거 문서
    (data/pc_care_guides.json)를 한국어 원문 그대로 인용하는 구조라 LLM을 거치지 않고는
    번역할 수 없다. 에이전트 미가용 시에는 lang과 무관하게 한국어로 나간다.
    """
    ordered = _ordered_items(items)
    if not ordered:
        return {"status": "pending", "text": None}
    if not available():
        return {"status": "ready", "text": build_guide_fallback(ordered)}
    from strands import Agent

    try:
        agent = Agent(model=_model(), system_prompt=_system_prompt(ordered, lang),
                     tools=make_tools(), callback_handler=None)
        result = agent("이 목록으로 조립 가이드를 작성해 주세요."
                       if lang != "en" else "Write the assembly guide for this list.")
        text = str(result).strip()
        if not text:
            raise ValueError("empty_agent_response")
        return {"status": "ready", "text": text}
    except Exception:  # noqa: BLE001 — 에이전트 실패는 가이드 자체를 막지 않는다, 폴백으로
        return {"status": "ready", "text": build_guide_fallback(ordered)}
