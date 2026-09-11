"""Retrieval orchestration and extractive, citation-only responses."""

from __future__ import annotations

import re
from dataclasses import asdict
import psycopg

from src.rag.contracts import EmbeddingError, SearchRequest, SearchResult

RETRIEVAL_CONFIG = {
    "version": "rrf-exact-v1",
    "candidate_limit": 20,
    "rrf_constant": 60,
    "min_vector_similarity": 0.20,
    "tokenizer": "nfkc-ko-bigram-v1",
}


class RagService:
    def __init__(self, repo, embedder):
        self.repo, self.embedder = repo, embedder

    def search(self, request: SearchRequest) -> SearchResult:
        run_id = None
        try:
            profile = self.repo.active_profile()
            if (
                profile["profile_key"] != self.embedder.profile_key
                or profile["dimensions"] != self.embedder.dimensions
            ):
                raise ValueError("query_document_profile_mismatch")
            if self.embedder.provider == "local-test" and request.corpus != "synthetic":
                raise ValueError("test_embeddings_cannot_search_real_corpus")
            run_id = self.repo.start_run(
                request.recommendation_run_id,
                profile["id"],
                purpose=request.purpose,
                query_text=request.query,
                scope_snapshot=asdict(request),
                retrieval_config=RETRIEVAL_CONFIG,
            )
            # A savepoint preserves the started run when retrieval SQL fails.
            with self.repo.conn.transaction():
                vector = self.embedder.embed([request.query])[0]
                hits = self.repo.search(
                    request,
                    vector,
                    profile["id"],
                    min_similarity=RETRIEVAL_CONFIG["min_vector_similarity"],
                )
                hits = self.repo.record_hits(run_id, profile["id"], request, hits)
            self.repo.complete_run(run_id)
            return SearchResult(
                "success" if hits else "no_evidence",
                hits,
                str(run_id),
                profile_key=self.embedder.profile_key,
            )
        except (EmbeddingError, ValueError) as exc:
            if run_id:
                self.repo.complete_run(run_id, "failed")
            return SearchResult(
                "error",
                run_id=str(run_id) if run_id else None,
                error_code=str(exc),
                profile_key=self.embedder.profile_key,
            )
        except psycopg.Error:
            if run_id:
                # A disconnected DB may also fail here; the connection boundary
                # returns a DB error and never substitutes no_evidence.
                self.repo.complete_run(run_id, "failed")
                return SearchResult(
                    "error",
                    run_id=str(run_id),
                    error_code="retrieval_database_error",
                    profile_key=self.embedder.profile_key,
                )
            raise

    def answer(self, request: SearchRequest) -> dict:
        result = self.search(request)
        if result.status != "success":
            return {
                **result.to_dict(),
                "answer": None,
                "verification_status": "unknown",
            }
        hits = result.hits
        # Feature existence does not prove a procedure, cleaning method or temperature.
        # These are supported question contracts, not inferred usage instructions.
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
            hits = [
                h for h in hits if re.search(r"(?:단계|\d+[.)] |절차|먼저)", h["text"])
            ]
        if not hits:
            return {
                **result.to_dict(),
                "status": "no_evidence",
                "hits": [],
                "answer": None,
                "verification_status": "unknown",
                "reason": "requested_instruction_not_in_retrieved_manual",
            }
        # Returning source excerpts avoids inventing facts or claiming global safety.
        chosen = hits[:1]
        self.repo.mark_context(result.run_id, [h["evidence_id"] for h in chosen])
        excerpts = [re.sub(r"<!--.*?-->", "", h["text"]).strip() for h in chosen]
        prefix = (
            "가상제품 테스트 설명서의 발췌입니다.\n\n"
            if request.corpus == "synthetic"
            else "설명서 발췌입니다.\n\n"
        )
        return {
            **result.to_dict(),
            "hits": chosen,
            "answer": prefix + "\n\n".join(excerpts),
            "verification_status": "partial",
            "answer_kind": "extractive",
            "coverage_status": chosen[0].get("coverage_status"),
        }
