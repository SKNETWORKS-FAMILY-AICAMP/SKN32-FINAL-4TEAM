"""리뷰 저장소 — community.review(_revision) + evidence.review_subject/summary/aggregate(_member).

리뷰 진위 탐지·오프라인 클렌징·review_summary 산출 로직은 리뷰 담당 팀원.
이 repo 는 그 산출물을 읽고([3-B]/[3-C]가 소비), 서비스 작성 리뷰(A7)를 저장한다.
외부 리뷰 원문 미저장(§15). 전체 PC 리뷰는 published + assembled_self_reported 구성에 연결(C11).
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class ReviewSubjectRepo(Repo):
    def get_or_create(self, *, product_id: UUID | None = None, variant_id: UUID | None = None,
                      offer_id: UUID | None = None, build_version_id: UUID | None = None) -> UUID:
        """정확히 하나만 non-null (CHECK). 각 FK 부분 UNIQUE."""
        raise NotImplementedError


class ReviewRepo(Repo):
    # ── 서비스 작성 리뷰 (A7) ──
    def create(self, author_user_id: UUID, subject_id: UUID) -> UUID:
        raise NotImplementedError

    def add_revision(self, review_id: UUID, domain_version_id: UUID, *, rating: int,
                     title: str, body: str, axis_scores: dict, usage_context: dict) -> UUID:
        raise NotImplementedError

    def publish(self, review_id: UUID, revision_id: UUID) -> None:
        """current_revision 전환 + 관련 요약·집계 stale(C12, §8.4)."""
        raise NotImplementedError

    # ── 집계·요약 읽기 ([3-B] 리뷰축 / [3-C] 리뷰 진위 / S5) ──
    def get_summary(self, subject_id: UUID, *, source_scope: str = "combined") -> dict | None:
        """정제 전/후 평점, cleanse_ratio, axis_scores, 대표 요약 3건 + 출처·조회시점."""
        raise NotImplementedError

    def top_summaries(self, subject_id: UUID, limit: int = 3) -> list[dict]:
        raise NotImplementedError

    def get_review_authenticity(self, product_key: str) -> dict:
        """[3-C] get_review_authenticity 계약 (기획서 §10-6).
        {orig_rating, cleaned_rating, cleanse_ratio, axis_scores, total_reviews,
         top_summaries, confidence_note}
        """
        raise NotImplementedError
