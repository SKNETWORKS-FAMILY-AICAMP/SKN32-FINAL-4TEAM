"""관리형 LLM API 호출 래퍼 (벤더 중립).

실제 구현에서는 env 로 주입된 LLM_PROVIDER / LLM_MODEL 에 맞는 SDK 로
- 함수 호출(structured output) 로 스키마를 강제한 JSON
- 자유 텍스트 응답
을 받는다. 현재는 MOCK_MODE 에서 용도(system 프롬프트 / 스키마 모양)를 보고 고정 가짜 응답을 준다.
"""
from __future__ import annotations

from typing import Any

from src.config import LLM_MODEL, MOCK_MODE


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
        # TODO: 실제 로직 구현 필요
        #   provider SDK 로 함수 호출(structured output) / 자유 텍스트 호출
        #   구조화 출력은 model_validate 로 검증 후 반환, 실패 시 1회 재시도
        raise NotImplementedError("call_llm: 실제 LLM 호출 미구현 (MOCK_MODE=0)")

    preview = prompt.replace("\n", " ")[:36]
    print(f"[MOCK] LLM 호출: {preview}...")

    sys_text = system or ""
    if "검사AI" in sys_text or "prosecutor" in sys_text:
        return {"text": "[MOCK 검사AI] 조합 이슈를 근거와 함께 제기합니다."}
    if "변호인AI" in sys_text or "defender" in sys_text:
        return {"text": "[MOCK 변호인AI] 제기된 쟁점에 도구 근거로 반박합니다."}

    # 그 외 구조화 출력 요청 → 호출자가 시나리오 정답값을 직접 주입하므로 빈 골격 반환
    return {"text": "[MOCK] 일반 응답"}
