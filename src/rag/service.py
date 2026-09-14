"""Retrieval orchestration over the external SearchProvider boundary (P3-D3).

The PostgreSQL `rag` schema is gone (`0011_drop_rag_schema.sql`); this service now
holds a `MaterialRepo` (publication/permission/applicability truth) and a
`SearchProvider` (chunk storage + lexical search, external to PostgreSQL — see
src/rag/provider.py). Every hit the provider returns is revalidated against
`MaterialRepo` before being trusted or turned into an `evidence.evidence` row — the
provider's own claim of "found in document X" is never sufficient on its own.
"""

from __future__ import annotations

import re
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from src.rag.contracts import SearchRequest, SearchResult
from src.rag.provider import ProviderError, ProviderUnavailable


class RagService:
    def __init__(self, material_repo, provider):
        self.material_repo = material_repo
        self.provider = provider

    def _resolve_scope(self, request: SearchRequest):
        """product_key/variant_key -> real catalog UUIDs, then the one applicable
        published+verified material revision for this exact scope (or None)."""
        from src.ids import stable_id

        product_id = stable_id(request.product_key)
        variant_id = stable_id(request.variant_key) if request.variant_key else None
        revision = self.material_repo.find_applicable_revision(
            product_id, variant_id=variant_id, market=request.market,
            corpus=request.corpus, language=request.language, domain=request.domain,
        )
        return product_id, variant_id, revision

    def search(self, request: SearchRequest) -> SearchResult:
        if self.provider is None:
            return SearchResult("error", error_code="search_provider_unavailable")
        try:
            product_id, variant_id, revision = self._resolve_scope(request)
            if revision is None:
                return SearchResult("no_evidence", [])
            hits = self.provider.search(
                query=request.query, product_id=str(product_id),
                variant_id=str(variant_id) if variant_id else None,
                market=request.market, language=request.language, corpus=request.corpus,
                k=request.k,
            )
        except ProviderUnavailable as exc:
            return SearchResult("error", error_code=str(exc) or "search_provider_unavailable")
        except ProviderError as exc:
            return SearchResult("error", error_code=str(exc) or "search_provider_error")
        except psycopg.Error:
            # A disconnected/broken DB during scope resolution never silently
            # degrades to no_evidence — the caller must see a real error.
            return SearchResult("error", error_code="retrieval_database_error")

        try:
            accepted = []
            for hit in hits:
                if hit.material_revision_id != str(revision["id"]):
                    continue  # a stale/other-revision hit; never cite it
                # P3 review R3: a provider is external and untrusted — even a hit that
                # names the right material_revision_id must still claim the same
                # product/option/corpus this request actually resolved, not just echo
                # back whatever revision id the request happened to look up.
                if hit.product_id != str(product_id):
                    continue
                if variant_id is not None and hit.variant_id is not None and hit.variant_id != str(variant_id):
                    continue
                if hit.corpus != request.corpus:
                    continue
                if not self.material_repo.is_currently_published(revision["id"]):
                    continue
                if hit.file_sha256 != revision["sha256"]:
                    continue
                evidence_id = self._record_evidence(hit, revision, request)
                accepted.append({
                    "evidence_id": str(evidence_id),
                    "provider": hit.provider,
                    "external_hit_id": hit.external_hit_id,
                    "material_id": str(revision["material_id"]),
                    "material_revision_id": hit.material_revision_id,
                    "file_sha256": hit.file_sha256,
                    "locator": hit.locator,
                    "text": hit.text,
                    "corpus": hit.corpus,
                    "review_status": "verified" if hit.verified else "unreviewed",
                    "score": hit.score,
                })
        except psycopg.Error:
            return SearchResult("error", error_code="retrieval_database_error")
        return SearchResult("success" if accepted else "no_evidence", accepted)

    def _record_evidence(self, hit, revision, request: SearchRequest):
        # Each app-generated UUID stands in for the removed rag.retrieval_hit id
        # (develop kept evidence.evidence.retrieval_hit_id as a plain UUID column
        # with no FK — DEVELOP_DB_TRANSITION.md "Evidence and external search").
        retrieval_hit_id = uuid4()
        snapshot = {
            "text": hit.text, "locator": hit.locator, "file_sha256": hit.file_sha256,
            "material_revision_id": hit.material_revision_id, "is_synthetic": hit.corpus == "synthetic",
            "provider": hit.provider, "external_hit_id": hit.external_hit_id,
        }
        return self.material_repo._one(
            """INSERT INTO evidence.evidence
              (source_id, kind, retrieval_hit_id, facts, citation_snapshot, retrieved_at)
            VALUES (%s,'material',%s,%s,%s,now()) RETURNING id""",
            (
                revision["source_id"], retrieval_hit_id,
                Jsonb({
                    "provider": hit.provider, "external_hit_id": hit.external_hit_id,
                    "material_revision_id": hit.material_revision_id, "file_sha256": hit.file_sha256,
                    "recommendation_run_id": request.recommendation_run_id,
                }),
                Jsonb(snapshot),
            ),
        )["id"]

    def answer(self, request: SearchRequest) -> dict:
        result = self.search(request)
        if result.status != "success":
            return {**result.to_dict(), "answer": None, "verification_status": "unknown"}
        hits = result.hits
        # Feature existence does not prove a procedure, cleaning method or temperature.
        requirements = [
            (r"세탁|세척|소독|관리|건조", {"S08"}),
            (r"조립|설치", {"S03"}),
            (r"점검", {"S04"}),
            (r"보관", {"S10"}),
            (r"고장|문제 해결", {"S09"}),
        ]
        for pattern, sections in requirements:
            if re.search(pattern, request.query):
                hits = [h for h in hits if h["locator"].get("section_code") in sections]
        for topic in (r"KC|인증", r"리콜"):
            if re.search(topic, request.query, re.I):
                hits = [h for h in hits if re.search(topic, h["text"], re.I)]
        if re.search(r"순서|방법|어떻게|절차", request.query):
            hits = [h for h in hits if re.search(r"(?:단계|\d+[.)] |절차|먼저)", h["text"])]
        if not hits:
            return {
                **result.to_dict(), "status": "no_evidence", "hits": [], "answer": None,
                "verification_status": "unknown", "reason": "requested_instruction_not_in_retrieved_manual",
            }
        chosen = hits[:1]
        excerpts = [re.sub(r"<!--.*?-->", "", h["text"]).strip() for h in chosen]
        prefix = (
            "가상제품 테스트 설명서의 발췌입니다.\n\n" if request.corpus == "synthetic"
            else "설명서 발췌입니다.\n\n"
        )
        return {
            **result.to_dict(), "hits": chosen, "answer": prefix + "\n\n".join(excerpts),
            "verification_status": "partial", "answer_kind": "extractive",
        }
