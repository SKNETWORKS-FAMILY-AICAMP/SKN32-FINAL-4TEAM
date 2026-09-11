"""assets.* + evidence.source/evidence 저장소 — file_object / product_material /
material_revision / material_applicability / source / evidence.

파일 바이너리는 객체 저장소, DB 에는 식별·권한·해시만(§24). 인용 근거 추적:
evidence → retrieval_hit → document_chunk → ingestion_job → material_revision → file_object.
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class SourceRepo(Repo):
    def get_or_create(self, name: str, source_type: str, base_url: str | None = None) -> UUID:
        raise NotImplementedError


class MaterialRepo(Repo):
    def register_file(self, *, bucket: str, object_key: str, storage_version: str,
                      original_filename: str, mime_type: str, byte_size: int,
                      sha256: str, use_policy: dict) -> UUID:
        """pending 으로 생성. 스캔·해시 확인 후 available/clean 전환(§8.1)."""
        raise NotImplementedError

    def mark_file_available(self, file_object_id: UUID) -> None:
        raise NotImplementedError

    def create_material(self, source_id: UUID, title: str, material_type: str) -> UUID:
        raise NotImplementedError

    def add_revision(self, material_id: UUID, file_object_id: UUID, *, language: str,
                     issued_at, retrieved_at, source_url: str | None = None) -> UUID:
        raise NotImplementedError

    def publish_revision(self, material_id: UUID, revision_id: UUID, active_ingestion_id: UUID) -> None:
        """게시 트랜잭션: material.current_revision + revision.active_ingestion 동시 전환(§8.1, C06)."""
        raise NotImplementedError

    def add_applicability(self, revision_id: UUID, product_id: UUID, *,
                          variant_id: UUID | None = None, conditions: dict,
                          verified: bool = False) -> UUID:
        raise NotImplementedError


class EvidenceRepo(Repo):
    def create_material_evidence(self, source_id: UUID, retrieval_hit_id: UUID, *,
                                 facts: dict, citation_snapshot: dict, retrieved_at) -> UUID:
        raise NotImplementedError

    def create_aggregate_evidence(self, source_id: UUID, review_aggregate_id: UUID, *,
                                  facts: dict, citation_snapshot: dict, retrieved_at) -> UUID:
        raise NotImplementedError

    def revoke(self, evidence_id: UUID) -> None:
        """revoked → 과거 인용에서도 접근 차단(§8.3)."""
        raise NotImplementedError
