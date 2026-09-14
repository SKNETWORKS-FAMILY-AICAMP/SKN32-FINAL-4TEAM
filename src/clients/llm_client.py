"""관리형 LLM API 호출 래퍼 (벤더 중립).

실제 구현에서는 env 로 주입된 LLM_PROVIDER / LLM_MODEL 에 맞는 SDK 로
- 함수 호출(structured output) 로 스키마를 강제한 JSON
- 자유 텍스트 응답
을 받는다. 현재는 MOCK_MODE 에서 용도(system 프롬프트 / 스키마 모양)를 보고 고정 가짜 응답을 준다.
"""
from __future__ import annotations

import json
from typing import Any

from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY

_client: Any = None


def _get_client():
    global _client
    if _client is None:
        if LLM_PROVIDER != "openai":
            raise NotImplementedError(f"call_llm: 지원하지 않는 LLM_PROVIDER={LLM_PROVIDER!r}")
        if not OPENAI_API_KEY:
            raise RuntimeError("call_llm: OPENAI_API_KEY 미설정 (MOCK_MODE=0)")
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _call_openai(prompt: str, *, system: str | None, output_schema: dict | None, model: str) -> dict:
    client = _get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {"model": model or LLM_MODEL, "messages": messages}
    if output_schema:
        # strict=False: 일부 스키마가 dict[str, Any] 같은 자유 형태 필드를 포함해
        # OpenAI strict 모드의 additionalProperties 제약과 맞지 않을 수 있다.
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": output_schema, "strict": False},
        }

    last_error: Exception | None = None
    for _attempt in range(2):  # 파싱 실패 시 1회 재시도
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        if not output_schema:
            return {"text": content}
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"call_llm: 구조화 출력 JSON 파싱 실패: {last_error}")


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    output_schema: dict | None = None,
    model: str = LLM_MODEL,
) -> dict:
    """LLM 호출.

    Args:
        prompt: 사용자 메시지 텍스트.
        system: 시스템 프롬프트.
        output_schema: 주어지면 스키마에 맞는 dict, 없으면 {"text": str} 반환.
        model: 모델 식별자 (env 주입).

    Returns:
        output_schema 가 있으면 dict, 없으면 {"text": str}.
    """
    if not MOCK_MODE:
        return _call_openai(prompt, system=system, output_schema=output_schema, model=model)

    preview = prompt.replace("\n", " ")[:36]
    print(f"[MOCK] LLM 호출: {preview}...")

    sys_text = system or ""
    if "검증 쟁점" in sys_text:
        if "OUTPUT_LOCALE=en-US" in sys_text:
            return {
                "text": (
                    "[MOCK] This issue statement reflects only the observed value "
                    "and evidence."
                )
            }
        return {"text": "[MOCK] 관측값과 근거를 그대로 옮긴 쟁점 문장입니다."}

    # 그 외 구조화 출력 요청 → 호출자가 시나리오 정답값을 직접 주입하므로 빈 골격 반환
    return {"text": "[MOCK] 일반 응답"}
