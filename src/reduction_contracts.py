"""P0 JSON storage models, separate from the current HTTP response models.

These validate structure only; repository scope/ownership checks remain P0 work.
"""
from typing import Any, Literal
from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    """develop v3 (DEVELOP_DB_TRANSITION.md "Evidence and external search"): stored as
    a plain array element, not wrapped in {schema_version,refs}. `provider`/
    `external_hit_id` identify the external search backend hit this ref traces back
    to; `retrieval_run_id` has no PostgreSQL rag FK to satisfy anymore and is purely
    informational when present."""
    evidence_id: str
    claim_key: str
    material_id: str
    material_version: str
    file_sha256: str
    locator: dict[str, Any]
    provider: str | None = None
    external_hit_id: str | None = None
    retrieval_run_id: str | None = None


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


