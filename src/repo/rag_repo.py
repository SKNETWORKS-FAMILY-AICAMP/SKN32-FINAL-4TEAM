"""PostgreSQL/pgvector RAG using the existing assets/rag/evidence schema.

Public-only retrieval; synthetic and real corpora never mix. Caller supplies a
recommendation run. This repository never invents a run or user identity.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb

from src.db.base import Repo
from src.rag.contracts import SearchRequest
from src.rag.embedding import validate_vector
from src.rag.ingestion import PIPELINE_VERSION, digest
from src.rag.text import VERSION, lexical_text, query_expression


def stable_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, "truefit:synthetic:" + key)


# Applied before BOTH ranking branches and again before creating an evidence row.
ELIGIBLE = """
SELECT c.id AS chunk_id, c.content_text AS text, c.locator, c.content_hash,
       c.review_status, e.embedding, c.search_vector,
       r.id AS revision_id, r.revision_no, r.source_url, r.retrieved_at AS collected_at,
       m.id AS material_id, m.source_id, m.title, f.id AS file_id,
       f.sha256 AS file_sha256, f.object_key,
       a.conditions, j.extraction_manifest
FROM rag.document_chunk c
JOIN rag.chunk_embedding e ON e.chunk_id=c.id AND e.profile_id=%(profile_id)s
JOIN rag.embedding_profile p ON p.id=e.profile_id AND p.status='active'
JOIN rag.ingestion_job j ON j.id=c.ingestion_id AND j.status='ready'
JOIN assets.material_revision r ON r.id=j.revision_id AND r.active_ingestion_id=j.id
JOIN assets.product_material m ON m.id=r.material_id AND m.current_revision_id=r.id
JOIN assets.file_object f ON f.id=r.file_object_id
JOIN assets.material_applicability a ON a.revision_id=r.id AND a.verified
WHERE e.status='ready' AND c.review_status <> 'rejected'
  AND r.status='published' AND m.status='active'
  AND f.access_scope='public' AND f.scan_status='clean' AND f.storage_status='available'
  AND f.use_policy @> '{"allow_rag":true,"allow_excerpt":true}'::jsonb
  AND r.language=%(language)s
  AND a.conditions->>'domain'=%(domain)s
  AND a.conditions->>'product_key'=%(product_key)s
  AND a.conditions->>'market'=%(market)s
  AND (a.variant_id IS NULL OR a.conditions->>'variant_key'=%(variant_key)s)
  AND %(context)s::jsonb @> COALESCE(a.conditions->'required_context','{}'::jsonb)
  AND j.extraction_manifest->>'corpus'=%(corpus)s
"""


class RagRepo(Repo):
    def active_profile(self):
        rows = self._all("SELECT * FROM rag.embedding_profile WHERE status='active'")
        if len(rows) != 1:
            raise ValueError("exactly_one_active_embedding_profile_required")
        return rows[0]

    def ensure_profile(self, embedder):
        if embedder.dimensions != 1024:
            raise ValueError("schema_requires_1024_dimensions")
        self._exec("SELECT pg_advisory_xact_lock(9182401)")
        active = self._all("SELECT * FROM rag.embedding_profile WHERE status='active'")
        if active and (
            len(active) != 1 or active[0]["profile_key"] != embedder.profile_key
        ):
            raise ValueError("active_profile_change_requires_explicit_migration")
        row = self._one(
            """INSERT INTO rag.embedding_profile
            (profile_key,provider,model_name,model_revision,dimensions,preprocessing_version,status)
            VALUES (%s,%s,%s,%s,1024,%s,'active') ON CONFLICT (profile_key) DO NOTHING RETURNING id""",
            (
                embedder.profile_key,
                embedder.provider,
                embedder.model,
                embedder.model,
                VERSION,
            ),
        )
        if row:
            return row["id"]
        profile = self._one(
            "SELECT * FROM rag.embedding_profile WHERE profile_key=%s",
            (embedder.profile_key,),
        )
        if profile["status"] != "active" or profile["dimensions"] != 1024:
            raise ValueError("embedding_profile_not_active")
        return profile["id"]

    def publish_manual(self, doc, vectors, embedder, *, reviewed=False):
        if len(vectors) != len(doc.chunks):
            raise ValueError("incomplete_embedding_batch")
        vectors = [validate_vector(v, 1024) for v in vectors]
        if not doc.revision.startswith("R") or not doc.revision[1:].isdigit():
            raise ValueError("manual_revision_must_be_R_positive_integer")
        revision_no = int(doc.revision[1:])
        if revision_no < 1:
            raise ValueError("invalid_revision")
        # Immutable local object copy; only administrator CLI supplies input paths.
        root = Path(os.getenv("RAG_STORAGE_ROOT", ".rag-files")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        object_path = root / (doc.sha256 + ".md")
        data = doc.text.encode("utf-8")
        if digest(data) != doc.sha256:
            raise ValueError("manual_changed_during_ingestion")
        try:
            with object_path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            if digest(object_path.read_bytes()) != doc.sha256:
                raise ValueError("stored_object_hash_mismatch")
        source, material = stable_id("manual-source"), stable_id(doc.manual_id)
        revision = stable_id(doc.manual_id + ":" + doc.revision)
        product, variant = stable_id(doc.product_key), stable_id(doc.variant_key)
        job_key = digest(
            (
                str(revision)
                + doc.sha256
                + embedder.profile_key
                + PIPELINE_VERSION
                + str(reviewed)
            ).encode()
        )
        job, file_id = stable_id(job_key), stable_id(doc.sha256)
        with self.conn.transaction():
            profile_id = self.ensure_profile(embedder)
            self._exec("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(material),))
            old = self._one(
                """SELECT f.sha256,r.status FROM assets.material_revision r
                JOIN assets.file_object f ON f.id=r.file_object_id WHERE r.id=%s""",
                (revision,),
            )
            if old and (old["sha256"] != doc.sha256 or old["status"] == "revoked"):
                raise ValueError("immutable_or_revoked_revision_use_new_revision")
            current = self._one(
                """SELECT r.revision_no FROM assets.product_material m
                JOIN assets.material_revision r ON r.id=m.current_revision_id WHERE m.id=%s""",
                (material,),
            )
            if current and current["revision_no"] > revision_no:
                raise ValueError("cannot_publish_older_revision")
            self._exec(
                """INSERT INTO evidence.source(id,name,source_type)
                VALUES (%s,'가상제품 RAG 테스트 자료','derived') ON CONFLICT (id) DO NOTHING""",
                (source,),
            )
            self._exec(
                """INSERT INTO catalog.product(id,name,brand,model,product_type,attributes)
                VALUES (%s,%s,'synthetic',%s,'baby',%s) ON CONFLICT (id) DO NOTHING""",
                (
                    product,
                    doc.product_key,
                    doc.product_key,
                    Jsonb({"is_synthetic": True}),
                ),
            )
            self._exec(
                "INSERT INTO shared.unit(code,dimension) VALUES ('each','count') ON CONFLICT DO NOTHING"
            )
            self._exec(
                """INSERT INTO catalog.product_variant(id,product_id,variant_key)
                VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (variant, product, doc.variant_key),
            )
            self._exec(
                """INSERT INTO assets.file_object
                (id,bucket,object_key,storage_version,original_filename,mime_type,byte_size,sha256,
                 access_scope,use_policy,scan_status,storage_status)
                VALUES (%s,'local',%s,%s,'manual.md','text/markdown',%s,%s,'public',%s,'clean','available')
                ON CONFLICT (id) DO NOTHING""",
                (
                    file_id,
                    str(object_path),
                    doc.sha256,
                    len(data),
                    doc.sha256,
                    Jsonb(
                        {
                            "allow_rag": True,
                            "allow_excerpt": True,
                            "allow_original": True,
                        }
                    ),
                ),
            )
            file = self._one("SELECT * FROM assets.file_object WHERE id=%s", (file_id,))
            if file["storage_status"] != "available" or file["scan_status"] != "clean":
                raise ValueError("file_not_available")
            self._exec(
                """INSERT INTO assets.product_material(id,source_id,title,material_type)
                VALUES (%s,%s,%s,'manual') ON CONFLICT (id) DO NOTHING""",
                (material, source, doc.manual_id),
            )
            self._exec(
                """INSERT INTO assets.material_revision
                (id,material_id,revision_no,file_object_id,language,retrieved_at)
                VALUES (%s,%s,%s,%s,'ko',now()) ON CONFLICT (id) DO NOTHING""",
                (revision, material, revision_no, file_id),
            )
            conditions = {
                "domain": "baby",
                "product_key": doc.product_key,
                "variant_key": doc.variant_key,
                "market": doc.market,
                "required_context": {},
            }
            self._exec(
                """INSERT INTO assets.material_applicability
                (revision_id,product_id,variant_id,conditions,verified) VALUES (%s,%s,%s,%s,true)
                ON CONFLICT DO NOTHING""",
                (revision, product, variant, Jsonb(conditions)),
            )
            manifest = {
                "corpus": "synthetic",
                "coverage_status": doc.coverage_status,
                "manual_revision": doc.revision,
                "profile_key": embedder.profile_key,
                "chunk_count": len(doc.chunks),
                "pipeline_version": PIPELINE_VERSION,
            }
            self._exec(
                """INSERT INTO rag.ingestion_job
                (id,revision_id,pipeline_version,idempotency_key,status,attempts,completed_at,extraction_manifest)
                VALUES (%s,%s,%s,%s,'ready',1,now(),%s) ON CONFLICT (id) DO NOTHING""",
                (job, revision, PIPELINE_VERSION, job_key, Jsonb(manifest)),
            )
            for chunk, vector in zip(doc.chunks, vectors):
                chunk_id = stable_id(str(job) + ":" + str(chunk.ordinal))
                self._exec(
                    """INSERT INTO rag.document_chunk
                    (id,ingestion_id,ordinal,content_type,content_text,locator,content_hash,review_status,search_vector)
                    VALUES (%s,%s,%s,'text',%s,%s,%s,%s,to_tsvector('simple',%s)) ON CONFLICT (id) DO NOTHING""",
                    (
                        chunk_id,
                        job,
                        chunk.ordinal,
                        chunk.text,
                        Jsonb(chunk.locator),
                        chunk.content_hash,
                        "verified" if reviewed else "unreviewed",
                        lexical_text(chunk.text),
                    ),
                )
                self._exec(
                    """INSERT INTO rag.chunk_embedding(chunk_id,profile_id,embedding,input_hash)
                    VALUES (%s,%s,%s::vector,%s) ON CONFLICT DO NOTHING""",
                    (chunk_id, profile_id, json.dumps(vector), chunk.content_hash),
                )
            self._exec(
                """UPDATE assets.material_revision SET status='superseded'
                WHERE material_id=%s AND id<>%s AND status='published'""",
                (material, revision),
            )
            self._exec(
                "UPDATE assets.material_revision SET active_ingestion_id=%s,status='published' WHERE id=%s",
                (job, revision),
            )
            self._exec(
                "UPDATE assets.product_material SET current_revision_id=%s,status='active' WHERE id=%s",
                (revision, material),
            )
        return {
            "material_id": str(material),
            "revision_id": str(revision),
            "ingestion_id": str(job),
            "profile_id": str(profile_id),
            "chunk_count": len(doc.chunks),
            "file_sha256": doc.sha256,
        }

    def _scope(self, request, profile_id):
        return {
            **asdict(request),
            "profile_id": profile_id,
            "context": json.dumps(request.context),
        }

    def search(
        self, request: SearchRequest, query_vec, profile_id, *, min_similarity=0.20
    ):
        params = self._scope(request, profile_id)
        params.update(
            vector=json.dumps(validate_vector(query_vec, 1024)),
            lex=query_expression(request.query),
            candidate_limit=20,
            min_similarity=min_similarity,
        )
        # Exact search is intentional for the small curated corpus. Both branches
        # share identical visibility and applicability filters, then merge by RRF.
        return self._all(
            """WITH eligible AS MATERIALIZED ("""
            + ELIGIBLE
            + """),
            scored AS (SELECT *, 1-(embedding <=> %(vector)s::vector) AS vector_score,
                ts_rank_cd(search_vector,to_tsquery('simple',%(lex)s)) AS keyword_score FROM eligible),
            vr AS (SELECT chunk_id,row_number() OVER(ORDER BY vector_score DESC,chunk_id) AS rank
                   FROM scored WHERE vector_score >= %(min_similarity)s ORDER BY vector_score DESC,chunk_id LIMIT %(candidate_limit)s),
            kr AS (SELECT chunk_id,row_number() OVER(ORDER BY keyword_score DESC,chunk_id) AS rank
                   FROM scored WHERE keyword_score > 0 ORDER BY keyword_score DESC,chunk_id LIMIT %(candidate_limit)s)
            SELECT s.chunk_id,s.text,s.locator,s.content_hash,s.review_status,s.revision_id,
                   s.revision_no,s.source_url,s.collected_at,s.material_id,s.source_id,s.title,
                   s.file_id,s.file_sha256,s.conditions,s.extraction_manifest,s.vector_score,s.keyword_score,
                   COALESCE(1.0/(60+vr.rank),0)+COALESCE(1.0/(60+kr.rank),0) AS score
            FROM scored s LEFT JOIN vr USING(chunk_id) LEFT JOIN kr USING(chunk_id)
            WHERE vr.chunk_id IS NOT NULL OR kr.chunk_id IS NOT NULL
            ORDER BY score DESC,s.chunk_id LIMIT %(k)s""",
            params,
        )

    def start_run(
        self,
        recommendation_run_id,
        profile_id,
        *,
        purpose,
        query_text,
        scope_snapshot,
        retrieval_config,
    ):
        if not recommendation_run_id:
            raise ValueError("recommendation_run_id_required")
        return self._one(
            """INSERT INTO rag.retrieval_run
            (recommendation_run_id,profile_id,purpose,query_text,scope_snapshot,retrieval_config)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                recommendation_run_id,
                profile_id,
                purpose,
                query_text,
                Jsonb(scope_snapshot),
                Jsonb(retrieval_config),
            ),
        )["id"]

    def complete_run(self, retrieval_run_id, status="completed"):
        if status not in {"completed", "failed"}:
            raise ValueError("invalid_retrieval_status")
        self._exec(
            "UPDATE rag.retrieval_run SET status=%s,completed_at=now() WHERE id=%s",
            (status, retrieval_run_id),
        )

    def record_hits(self, run_id, profile_id, request, hits):
        accepted = []
        with self.conn.transaction():
            for hit in hits:
                params = self._scope(request, profile_id)
                params["chunk_id"] = hit["chunk_id"]
                # Lock the rows that carry authorization until evidence is saved.
                current = self._one(
                    ELIGIBLE + " AND c.id=%(chunk_id)s FOR SHARE OF f,r,m,a,j,e,p,c",
                    params,
                )
                if current is None or current["content_hash"] != hit["content_hash"]:
                    continue
                rank = len(accepted) + 1
                hit_id = self._one(
                    """INSERT INTO rag.retrieval_hit
                    (retrieval_run_id,chunk_id,profile_id,rank_no,vector_score,keyword_score,rerank_score,selected_for_context)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,false) RETURNING id""",
                    (
                        run_id,
                        hit["chunk_id"],
                        profile_id,
                        rank,
                        hit["vector_score"],
                        hit["keyword_score"],
                        float(hit["score"]),
                    ),
                )["id"]
                snapshot = {
                    "text": current["text"],
                    "locator": current["locator"],
                    "file_sha256": current["file_sha256"],
                    "revision_id": str(current["revision_id"]),
                    "is_synthetic": request.corpus == "synthetic",
                    "coverage_status": current["extraction_manifest"].get(
                        "coverage_status"
                    ),
                }
                evidence_id = self._one(
                    """INSERT INTO evidence.evidence
                    (source_id,kind,retrieval_hit_id,citation_snapshot,retrieved_at)
                    VALUES (%s,'material',%s,%s,now()) RETURNING id""",
                    (current["source_id"], hit_id, Jsonb(snapshot)),
                )["id"]
                accepted.append(
                    {
                        **snapshot,
                        "chunk_id": str(hit["chunk_id"]),
                        "evidence_id": str(evidence_id),
                        "retrieval_hit_id": str(hit_id),
                        "file_id": str(current["file_id"]),
                        "source_url": current["source_url"],
                        "collected_at": str(current["collected_at"]),
                        "product_key": request.product_key,
                        "variant_key": request.variant_key,
                        "review_status": current["review_status"],
                        "score": float(hit["score"]),
                        "vector_score": hit["vector_score"],
                        "keyword_score": hit["keyword_score"],
                    }
                )
        return accepted

    def mark_context(self, run_id, evidence_ids):
        """Track actual downstream use separately from retrieved candidates."""
        self._exec(
            """UPDATE rag.retrieval_hit SET selected_for_context=false
            WHERE retrieval_run_id=%s""",
            (run_id,),
        )
        if evidence_ids:
            self._exec(
                """UPDATE rag.retrieval_hit h SET selected_for_context=true
                FROM evidence.evidence ev WHERE ev.retrieval_hit_id=h.id
                AND h.retrieval_run_id=%s AND ev.id=ANY(%s::uuid[]) AND ev.status='active'""",
                (run_id, evidence_ids),
            )

    def resolve_evidence(self, evidence_id, request, profile_id):
        row = self._one(
            """SELECT h.chunk_id FROM evidence.evidence ev
            JOIN rag.retrieval_hit h ON h.id=ev.retrieval_hit_id
            WHERE ev.id=%s AND ev.status='active' AND h.profile_id=%s""",
            (evidence_id, profile_id),
        )
        if not row:
            return None
        params = self._scope(request, profile_id)
        params["chunk_id"] = row["chunk_id"]
        return self._one(ELIGIBLE + " AND c.id=%(chunk_id)s", params)

    def revoke_material(self, material_id):
        with self.conn.transaction():
            self._exec(
                "UPDATE assets.product_material SET status='retired' WHERE id=%s",
                (material_id,),
            )
            self._exec(
                "UPDATE assets.material_revision SET status='revoked' WHERE material_id=%s",
                (material_id,),
            )
            self._exec(
                """UPDATE rag.chunk_embedding SET status='revoked',embedding=NULL WHERE chunk_id IN
                (SELECT c.id FROM rag.document_chunk c JOIN rag.ingestion_job j ON j.id=c.ingestion_id
                 JOIN assets.material_revision r ON r.id=j.revision_id WHERE r.material_id=%s)""",
                (material_id,),
            )
            self._exec(
                """UPDATE evidence.evidence SET status='revoked' WHERE retrieval_hit_id IN
                (SELECT h.id FROM rag.retrieval_hit h JOIN rag.document_chunk c ON c.id=h.chunk_id
                 JOIN rag.ingestion_job j ON j.id=c.ingestion_id JOIN assets.material_revision r ON r.id=j.revision_id
                 WHERE r.material_id=%s)""",
                (material_id,),
            )

    def process_job(self, ingestion_id, embedder):
        # Upload/OCR worker is outside this slice. Do not mark unsupported jobs ready.
        with self.conn.transaction():
            job = self._one(
                "SELECT * FROM rag.ingestion_job WHERE id=%s FOR UPDATE",
                (ingestion_id,),
            )
            if not job:
                raise ValueError("unknown_ingestion_job")
            if job["status"] == "ready":
                return
            self._exec(
                """UPDATE rag.ingestion_job SET status='failed',attempts=attempts+1,
                error_code='unsupported_ingestion_source_use_manual_cli',completed_at=now() WHERE id=%s""",
                (ingestion_id,),
            )
        raise ValueError("unsupported_ingestion_source_use_manual_cli")
