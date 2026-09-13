"""파이프라인 단계 입출력 DTO (pydantic v2).

경계를 넘는 값(단계 간 전달 / LLM JSON / HTTP / DB 행)은 전부 여기에 정의한다.
경계를 넘지 않는 순수 내부 값은 그냥 dataclass/tuple 로 둔다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["computer", "baby"]
Mode = Literal["build", "upgrade", "born", "prenatal"]
Verdict = Literal["Pass", "Fail", "Pending"]


# ── [1] 의도 분해 · 슬롯필링 ──────────────────────────────────────────────
class SlotFillResult(BaseModel):
    """LLM `fill_slots` tool 출력 스키마."""

    confirmed: dict[str, Any] = Field(default_factory=dict)
    assumed: dict[str, Any] = Field(default_factory=dict)
    assumed_reason: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class Slots(BaseModel):
    """확정 + 가정을 병합한 최종 조건 세트."""

    category: Category
    mode: Mode
    objective_text: str
    values: dict[str, Any] = Field(default_factory=dict)       # confirmed > assumed > defaults
    assumed_keys: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    def can_recommend(self, required_inputs: list[str]) -> bool:
        return not (set(required_inputs) & set(self.missing))


# ── [2] 요구사양 빌드 ────────────────────────────────────────────────────
class RequirementSpec(BaseModel):
    list_id: str
    category: Category
    mode: Mode
    targets: dict[str, dict[str, Any]] = Field(default_factory=dict)   # slot -> 제약 floor
    link_rules: list[str] = Field(default_factory=list)               # computer
    chain_warnings: list[str] = Field(default_factory=list)           # upgrade
    budget: dict[str, Any] = Field(default_factory=dict)              # total, alloc, feasibility
    flags: list[str] = Field(default_factory=list)
    unresolved: list[dict[str, str]] = Field(default_factory=list)


# ── [3-0]~[3-B] 후보 ────────────────────────────────────────────────────
class Candidate(BaseModel):
    product_key: str
    slot: str
    name: str
    brand: str = ""
    price: int = 0
    specs: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict = "Pass"
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    score: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    rank: int = 0


class HardFilterResult(BaseModel):
    slots: dict[str, list[Candidate]] = Field(default_factory=dict)          # Pass + 승격 Pending
    stats: dict[str, dict[str, int]] = Field(default_factory=dict)           # slot -> pool/pass/fail/pending


class RankResult(BaseModel):
    slots: dict[str, dict[str, Any]] = Field(default_factory=dict)           # slot -> ideal_tier/ranked/bottleneck_hint
    weights_used: dict[str, float] = Field(default_factory=dict)
    weight_adjustments: list[str] = Field(default_factory=list)


# ── [4] 세트 최적화 / 예산 배분 ─────────────────────────────────────────
class BuildItem(BaseModel):
    slot: str
    product_key: str
    name: str
    price: int
    perf_tier: float = 0.0
    score: float = 0.0
    rank_from_3b: int = 1


class BuildResult(BaseModel):
    list_id: str
    items: list[BuildItem] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    link_check: dict[str, str] = Field(default_factory=dict)
    balance: dict[str, Any] = Field(default_factory=dict)
    alternatives: dict[str, int] = Field(default_factory=dict)
    round: int = 1


class BasketLine(BaseModel):
    category: str
    sub_item: str
    product_key: str
    name: str
    price: int
    qty: int = 1
    score: float = 0.0
    timing: str = "now"


class BasketResult(BaseModel):
    list_id: str
    buy_now: list[BasketLine] = Field(default_factory=list)
    buy_later: list[BasketLine] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    adjustments: list[str] = Field(default_factory=list)


# ── [3-C] 적대적 검증 ───────────────────────────────────────────────────
class Issue(BaseModel):
    axis: str
    prosecutor: str = ""
    defender: str = ""
    tool_result: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    judge: str = ""
    penalty: int = 0


class VerificationTarget(BaseModel):
    subject: str
    confidence: int = 0
    passed: bool = False
    rounds: int = 1
    issues: list[Issue] = Field(default_factory=list)
    gray_axes: list[str] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)


class VerificationResult(BaseModel):
    list_id: str
    category: Category
    mode: Literal["set", "per_item"]
    targets: list[VerificationTarget] = Field(default_factory=list)


# ── [5] 설명 생성 ───────────────────────────────────────────────────────
class ExplanationItem(BaseModel):
    slot: str
    reason: str
    basis: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Explanation(BaseModel):
    list_id: str
    headline: str = ""
    contribution: dict[str, int] = Field(default_factory=dict)   # 가격/성능/호환성
    items: list[ExplanationItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    review_line_by_slot: dict[str, str] = Field(default_factory=dict)


# (구 추천 결과 DTO는 §D-4-2 계약(RecommendResultOut, src/schemas.py)으로 대체되어 제거됨.
#  서비스 계층은 이제 dict를 직접 만들어 schemas.RecommendResultOut 경계를 통과시킨다.)


# ── 전체 결과 ───────────────────────────────────────────────────────────
class PipelineResult(BaseModel):
    scenario: str
    category: Category
    input_text: str
    slots: Optional[Slots] = None
    requirement: Optional[RequirementSpec] = None
    hard_filter: Optional[HardFilterResult] = None
    rank: Optional[RankResult] = None
    build: Optional[BuildResult] = None
    basket: Optional[BasketResult] = None
    verification: Optional[VerificationResult] = None
    explanation: Optional[Explanation] = None
    logs: list[str] = Field(default_factory=list)
