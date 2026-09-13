"""P0 JSON storage models, separate from the current HTTP response models.

These validate structure only; repository scope/ownership checks remain P0 work.
"""
from typing import Any, Literal
from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    evidence_id: str
    claim_key: str
    material_id: str
    material_version: str
    file_sha256: str
    locator: dict[str, Any]
    retrieval_run_id: str | None = None


class EvidenceRefs(BaseModel):
    schema_version: Literal[1] = 1
    refs: list[EvidenceRef] = Field(default_factory=list)


class PublicEvidence(BaseModel):
    """resolve_public_evidence() return shape — a citation re-checked for current
    publication/permission at read time (P3 CONTRACTS step 6/VE06). `available=False`
    keeps the trace (evidence_id/locator) but drops `text`; it never means the
    citation never existed."""
    evidence_id: str
    available: bool
    text: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    material_id: str | None = None
    material_version: str | None = None
    is_synthetic: bool | None = None
    redacted_reason: str | None = None


class ValidationIssue(BaseModel):
    schema_version: Literal[1] = 1
    rule_key: str
    rule_version: str
    target: dict[str, str | None]
    status: Literal["pass", "fail", "unknown"]
    severity: str
    measured: dict[str, Any] = Field(default_factory=dict)
    threshold: dict[str, Any] = Field(default_factory=dict)
    reason: str
    penalty: float | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


