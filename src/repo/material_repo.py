"""assets.* + evidence.source/evidence.evidence — develop `da79839` schema (P3-D3).

Unlike the discarded reduced-schema design, `product_material`, `material_revision`
and `material_applicability` are three separate tables again (schema-v1.md), and
`evidence.source` is its own table joined by `evidence.evidence.source_id`. This repo
is the only place that writes/reads them; verification-time re-checks (publication,
file permission/scan/storage state, product/variant/market/corpus applicability,
revocation) all go through here so a caller cannot reconstruct a stale answer from a
JSON reference alone (evidence JSON has no automatic FK — CONTRACTS/schema-v1.md).
"""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from src.db.base import Repo


class SourceRepo(Repo):
    def get_or_create(self, name: str, source_type: str, base_url: str | None = None) -> UUID:
        row = self._one(
            "SELECT id FROM evidence.source WHERE name=%s AND source_type=%s", (name, source_type)
        )
        if row:
            return row["id"]
        return self._one(
            "INSERT INTO evidence.source (name, source_type, base_url) VALUES (%s,%s,%s) RETURNING id",
            (name, source_type, base_url),
        )["id"]


class MaterialRepo(Repo):
    def register_file(self, *, bucket: str, object_key: str, storage_version: str,
                      original_filename: str, mime_type: str, byte_size: int,
                      sha256: str, use_policy: dict, access_scope: str = "internal",
                      scan_status: str = "pending", storage_status: str = "pending") -> UUID:
        """pending 으로 생성. 스캔·해시 확인 후 available/clean 전환(§8.1) — 합성 설명서처럼
        업로드 즉시 신뢰 가능한 출처는 access_scope/scan_status/storage_status를 바로 넘긴다."""
        return self._one(
            """INSERT INTO assets.file_object
              (bucket, object_key, storage_version, original_filename, mime_type, byte_size,
               sha256, access_scope, use_policy, scan_status, storage_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (bucket, object_key, storage_version, original_filename, mime_type, byte_size,
             sha256, access_scope, Jsonb(use_policy), scan_status, storage_status),
        )["id"]

    def mark_file_available(self, file_object_id: UUID) -> None:
        self._exec(
            "UPDATE assets.file_object SET scan_status='clean', storage_status='available', "
            "updated_at=now() WHERE id=%s", (file_object_id,),
        )

    def create_material(self, source_id: UUID, title: str, material_type: str) -> UUID:
        return self._one(
            """INSERT INTO assets.product_material (source_id, title, material_type, status)
            VALUES (%s,%s,%s,'draft') RETURNING id""",
            (source_id, title, material_type),
        )["id"]

    def add_revision(self, material_id: UUID, file_object_id: UUID, *, language: str,
                     issued_at, retrieved_at, source_url: str | None = None) -> UUID:
        return self._one(
            """INSERT INTO assets.material_revision
              (material_id, revision_no, file_object_id, source_url, language, issued_at, retrieved_at, status)
            SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s, %s, %s, %s, 'staged'
            FROM assets.material_revision WHERE material_id=%s RETURNING id""",
            (material_id, file_object_id, source_url, language, issued_at, retrieved_at, material_id),
        )["id"]

    def publish_revision(self, material_id: UUID, revision_id: UUID) -> None:
        """게시 트랜잭션: material.current_revision + revision.status 동시 전환(§8.1, C06).

        같은 material의 기존 published revision은 superseded로 내리고, 새 revision의
        파일이 실제로 available/clean일 때만 승격한다 — 파일 상태를 신뢰로 대신하지 않는다.
        """
        with self.conn.transaction():
            revision = self._one(
                """SELECT r.id, r.material_id, r.status AS revision_status, f.scan_status, f.storage_status
                   FROM assets.material_revision r JOIN assets.file_object f ON f.id=r.file_object_id
                   WHERE r.id=%s AND r.material_id=%s FOR UPDATE""",
                (revision_id, material_id),
            )
            if revision is None:
                raise ValueError("revision_not_found_for_material")
            if revision["revision_status"] == "revoked":
                raise ValueError("revoked_revision_cannot_be_published")
            if revision["scan_status"] != "clean" or revision["storage_status"] != "available":
                raise ValueError("file_not_available_for_publish")
            self._exec(
                "UPDATE assets.material_revision SET status='superseded', updated_at=now() "
                "WHERE material_id=%s AND status='published' AND id<>%s",
                (material_id, revision_id),
            )
            self._exec(
                "UPDATE assets.material_revision SET status='published', updated_at=now() WHERE id=%s",
                (revision_id,),
            )
            self._exec(
                "UPDATE assets.product_material SET current_revision_id=%s, status='active', "
                "updated_at=now() WHERE id=%s",
                (revision_id, material_id),
            )

    def add_applicability(self, revision_id: UUID, product_id: UUID, *,
                          variant_id: UUID | None = None, conditions: dict,
                          verified: bool = False) -> UUID:
        return self._one(
            """INSERT INTO assets.material_applicability (revision_id, product_id, variant_id, conditions, verified)
            VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (revision_id, product_id, variant_id, Jsonb(conditions), verified),
        )["id"]

    def get_revision(self, revision_id: UUID) -> dict | None:
        """재검사용 전체 상태 — 인용을 돌려주기 전 다시 이 값을 확인한다(§8.3, VE06)."""
        return self._one(
            """SELECT r.id, r.material_id, r.revision_no, r.status AS revision_status,
                      m.status AS material_status, m.current_revision_id, m.source_id,
                      f.id AS file_id, f.object_key, f.sha256, f.access_scope, f.scan_status,
                      f.storage_status, f.use_policy
               FROM assets.material_revision r
               JOIN assets.product_material m ON m.id=r.material_id
               JOIN assets.file_object f ON f.id=r.file_object_id
               WHERE r.id=%s""",
            (revision_id,),
        )

    def is_currently_published(self, revision_id: UUID) -> bool:
        row = self.get_revision(revision_id)
        if row is None:
            return False
        policy = row["use_policy"] or {}
        return (
            row["revision_status"] == "published"
            and row["material_status"] == "active"
            and row["current_revision_id"] == row["id"]
            and row["access_scope"] == "public"
            and row["scan_status"] == "clean"
            and row["storage_status"] == "available"
            and bool(policy.get("allow_rag")) and bool(policy.get("allow_excerpt"))
        )

    def has_current_applicability(self, revision_id: UUID, *, product_id: UUID | None = None,
                                  variant_id: UUID | None = None) -> bool:
        """resolve_public_evidence 재검사용(P3 review R2) — 게시 상태와 별개로, 이
        revision이 지금도 verified=true인 material_applicability를 갖고 있는지 확인한다.
        product_id가 주어지면 그 상품(옵션 한정이면 variant_id까지)으로 범위를 좁힌다 —
        검색 당시엔 적용됐던 상품의 승인이 그 뒤 해제된 경우를 잡아낸다."""
        if product_id is not None:
            row = self._one(
                "SELECT 1 FROM assets.material_applicability WHERE revision_id=%s AND verified "
                "AND product_id=%s AND (variant_id IS NULL OR variant_id=%s)",
                (revision_id, product_id, variant_id),
            )
        else:
            row = self._one(
                "SELECT 1 FROM assets.material_applicability WHERE revision_id=%s AND verified",
                (revision_id,),
            )
        return row is not None

    def revoke_revision(self, revision_id: UUID) -> None:
        with self.conn.transaction():
            row = self._one(
                "SELECT material_id FROM assets.material_revision WHERE id=%s FOR UPDATE", (revision_id,)
            )
            if row is None:
                raise ValueError("revision_not_found")
            self._exec(
                "UPDATE assets.material_revision SET status='revoked', updated_at=now() WHERE id=%s",
                (revision_id,),
            )
            self._exec(
                "UPDATE assets.product_material SET current_revision_id=NULL, status='retired', "
                "updated_at=now() WHERE id=%s AND current_revision_id=%s",
                (row["material_id"], revision_id),
            )

    def find_applicable_revision(self, product_id: UUID, *, variant_id: UUID | None,
                                 market: str, corpus: str, language: str = "ko",
                                 domain: str = "baby") -> dict | None:
        """검증에 쓸 유일한 진입점 — published+active+public+verified 조건을 전부 SQL에서
        확인한다. 옵션별 적용조건이 있으면 모델 공통 조건보다 우선한다(P3 IMPLEMENTATION §1).
        domain 도 스코프에 포함해 다른 카테고리(예: computer)의 동일 문자열 product_key가
        섞여 들어오지 않게 한다."""
        rows = self._all(
            """SELECT a.id AS applicability_id, a.variant_id AS applicability_variant_id, r.id AS revision_id
               FROM assets.material_applicability a
               JOIN assets.material_revision r ON r.id=a.revision_id
               JOIN assets.product_material m ON m.id=r.material_id AND m.current_revision_id=r.id
               JOIN assets.file_object f ON f.id=r.file_object_id
               WHERE r.status='published' AND m.status='active'
                 AND f.access_scope='public' AND f.scan_status='clean' AND f.storage_status='available'
                 AND f.use_policy @> '{"allow_rag":true,"allow_excerpt":true}'::jsonb
                 AND r.language=%s AND a.verified IS TRUE
                 AND a.product_id=%s AND (a.variant_id IS NULL OR a.variant_id=%s)
                 AND a.conditions->>'market'=%s AND a.conditions->>'corpus'=%s
                 AND a.conditions->>'domain'=%s""",
            (language, product_id, variant_id, market, corpus, domain),
        )
        if not rows:
            return None
        variant_specific = [r for r in rows if r["applicability_variant_id"] == variant_id and variant_id is not None]
        chosen = variant_specific[0] if variant_specific else rows[0]
        return self.get_revision(chosen["revision_id"])


class EvidenceRepo(Repo):
    def create_material_evidence(self, source_id: UUID, retrieval_hit_id: UUID, *,
                                 facts: dict, citation_snapshot: dict, retrieved_at) -> UUID:
        return self._one(
            """INSERT INTO evidence.evidence (source_id, kind, retrieval_hit_id, facts, citation_snapshot, retrieved_at)
            VALUES (%s,'material',%s,%s,%s,%s) RETURNING id""",
            (source_id, retrieval_hit_id, Jsonb(facts), Jsonb(citation_snapshot), retrieved_at),
        )["id"]

    def create_aggregate_evidence(self, source_id: UUID, review_aggregate_id: UUID, *,
                                  facts: dict, citation_snapshot: dict, retrieved_at) -> UUID:
        return self._one(
            """INSERT INTO evidence.evidence (source_id, kind, review_aggregate_id, facts, citation_snapshot, retrieved_at)
            VALUES (%s,'review_aggregate',%s,%s,%s,%s) RETURNING id""",
            (source_id, review_aggregate_id, Jsonb(facts), Jsonb(citation_snapshot), retrieved_at),
        )["id"]

    def get(self, evidence_id: UUID) -> dict | None:
        return self._one("SELECT * FROM evidence.evidence WHERE id=%s", (evidence_id,))

    def revoke(self, evidence_id: UUID) -> None:
        """revoked → 과거 인용에서도 접근 차단(§8.3)."""
        self._exec("UPDATE evidence.evidence SET status='revoked', updated_at=now() WHERE id=%s", (evidence_id,))
