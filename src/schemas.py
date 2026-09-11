"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


# ── auth ──
class RequestCodeIn(BaseModel):
    email: str


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class TokenOut(BaseModel):
    token: str


# ── session (S1~S3) ──
class SessionOut(BaseModel):
    list_id: str
    browser_token: str


class CategoryIn(BaseModel):
    category: Literal["computer", "baby"]
    mode: Optional[str] = None


class MessageIn(BaseModel):
    text: str


class AnswerIn(BaseModel):
    question_id: str
    selected: list[str]


class SlotPatchIn(BaseModel):
    field: str
    value: Any | None = None


class ConditionStateOut(BaseModel):
    slots: dict[str, Any]
    assumed: dict[str, Any]
    missing: list[str]
    next_questions: list[dict]
    can_recommend: bool


# ── recommend / result (S4) ──
class RecommendResultOut(BaseModel):
    list_id: str
    status: str                      # running | done | failed
    items: list[dict] = []
    totals: dict[str, Any] = {}
    reasoning_log: list[dict] = []   # S4-a 5단계
    explanation: dict = {}


# ── list confirm (S5-a) / report (S5-b) ──
class ConfirmIn(BaseModel):
    name: str
    planned_purchase_at: Optional[str] = None
    target_amount: Optional[int] = None


class ReportOut(BaseModel):
    list_id: str
    name: str
    items: list[dict]
    total: int
    buy_links: list[dict]
    price_watch: Optional[dict] = None


# ── reviews (A7) ──
class PartReviewIn(BaseModel):
    variant_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = {}


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = {}
