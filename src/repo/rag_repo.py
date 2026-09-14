"""Business-scope evidence behavior over the develop `da79839` schema (P3-D3).

The PostgreSQL `rag` schema (chunks/vectors/retrieval history) was dropped by
`0011_drop_rag_schema.sql`; publish/search/resolve/revoke now live in
`src.rag.provider`/`src.rag.ingestion`/`src.repo.material_repo`. This module keeps
`stable_id` (re-exported so existing importers — ProductRepo, seed scripts, tests —
do not need to change) and `resolve_public_evidence`, the citation-return-time
revalidation CONTRACTS §Evidence step 6 requires.
"""

from __future__ import annotations

import re

from src.ids import stable_id  # noqa: F401 — re-exported for existing importers

__all__ = ["stable_id", "resolve_public_evidence"]


def resolve_public_evidence(conn, refs: list[dict], principal_scope: dict) -> list[dict]:
    """Re-check publication/permission/scope for each ref at citation-return time
    (CONTRACTS: "recheck at citation return and again via P5 result reads").

    principal_scope requires "recommendation_run_id": an evidence row recorded for a
    *different* run resolves to unavailable — evidence access is scoped per
    recommendation run (the run id is carried in evidence.facts.recommendation_run_id,
    since evidence.evidence.retrieval_hit_id is a plain UUID with no FK to reconstruct
    ownership from after the rag schema was dropped — DEVELOP_DB_TRANSITION.md). A
    run id missing on *either* side is always out_of_scope (P3 review R2) — two
    absent values must never agree by string comparison.

    principal_scope may also carry "product_id"/"variant_id" (the candidate currently
    being displayed); when given, the material_applicability re-check is scoped to
    them. Re-verifies, beyond publish status: the material still has a *currently
    verified* applicability (an approval pulled after the original search is caught
    even though the revision itself is still "published"), and the citation's
    recorded file_sha256 still matches the file's current hash (the file changed
    since this text was captured).

    A revoked/permission-changed/out-of-scope/stale ref returns available=False with
    the evidence_id/locator trace kept (VE06); it is never silently dropped.
    """
    from src.reduction_contracts import PublicEvidence
    from src.repo.material_repo import MaterialRepo

    material_repo = MaterialRepo(conn)
    scope_run_id = principal_scope.get("recommendation_run_id")
    scope_product_id = principal_scope.get("product_id")
    scope_variant_id = principal_scope.get("variant_id")
    out: list[PublicEvidence] = []
    for ref in refs:
        evidence_id = ref.get("evidence_id") if isinstance(ref, dict) else None
        locator = (ref.get("locator") if isinstance(ref, dict) else None) or {}
        if not evidence_id:
            out.append(PublicEvidence(evidence_id="", available=False, redacted_reason="malformed_ref"))
            continue
        row = material_repo._one(
            "SELECT status, facts, citation_snapshot FROM evidence.evidence WHERE id=%s", (evidence_id,)
        )
        if row is None:
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="orphan_evidence"))
            continue
        facts = row["facts"] or {}
        facts_run_id = facts.get("recommendation_run_id")
        if not scope_run_id or not facts_run_id or str(facts_run_id) != str(scope_run_id):
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="out_of_scope"))
            continue
        if row["status"] != "active":
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="revoked_or_permission_changed"))
            continue
        revision_id = facts.get("material_revision_id")
        revision = material_repo.get_revision(revision_id) if revision_id else None
        if revision is None or not material_repo.is_currently_published(revision["id"]):
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="revoked_or_permission_changed"))
            continue
        if not material_repo.has_current_applicability(
            revision["id"], product_id=scope_product_id, variant_id=scope_variant_id,
        ):
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="not_currently_applicable"))
            continue
        snapshot = row["citation_snapshot"] or {}
        snapshot_hash = facts.get("file_sha256") or snapshot.get("file_sha256")
        if not snapshot_hash or not revision["sha256"] or snapshot_hash != revision["sha256"]:
            out.append(PublicEvidence(evidence_id=evidence_id, available=False, locator=locator,
                                      redacted_reason="file_changed_since_citation"))
            continue
        out.append(PublicEvidence(
            evidence_id=evidence_id, available=True,
            text=re.sub(r"<!--.*?-->", "", snapshot.get("text", "")).strip(),
            locator=snapshot.get("locator", locator), material_id=str(revision["material_id"]),
            material_version=str(revision["revision_no"]),
            is_synthetic=bool(snapshot.get("is_synthetic")),
        ))
    return [pe.model_dump() for pe in out]
