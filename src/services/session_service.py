"""세션 서비스 — S1~S3 대화·조건 수집.

카테고리 선택(필수) → 전용 슬롯 구조 생성 → 대화 주도 + 인라인 칩 →
[추천 실행] 활성 판정(required_inputs 충족).
"""
from __future__ import annotations

from uuid import UUID

from src.auth.deps import Principal


def create_session(principal: Principal) -> dict:
    """conversation + plan 생성 → {list_id, browser_token}."""
    raise NotImplementedError


def choose_category(list_id: UUID, category: str, mode: str | None) -> dict:
    """카테고리·모드 확정 → 슬롯 구조 + required_inputs + question_sets 반환. plan_node 생성."""
    raise NotImplementedError


def handle_message(list_id: UUID, text: str) -> dict:
    """자유 입력 → [1] 슬롯필링(LLM) → {slots, assumed, missing, next_questions, can_recommend}.
    plan_condition 갱신, identity.message 저장.
    """
    raise NotImplementedError


def handle_answer(list_id: UUID, question_id: str, selected: list[str]) -> dict:
    """칩 선택 → 서버가 maps_to 로 슬롯 직접 갱신 (LLM 0회)."""
    raise NotImplementedError


def patch_slot(list_id: UUID, field: str, value) -> dict:
    """조건 수정·삭제(value=None) → missing 재계산."""
    raise NotImplementedError
