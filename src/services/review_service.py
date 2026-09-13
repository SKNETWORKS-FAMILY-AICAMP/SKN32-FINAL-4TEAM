"""리뷰 서비스 — A7 부품 리뷰 / 전체 PC 리뷰 작성 · 게시 · 개봉/구매 인증.

부품 리뷰 = product/variant 대상, 자기신고. 전체 PC 리뷰 = pc_build_version/component 고정 +
assembled_self_reported 확인 후 게시(C11). 외부 리뷰 원문 미저장.
"""
from __future__ import annotations

from uuid import UUID


def write_part_review(user_id: UUID, variant_id: UUID, *, rating: int, title: str,
                      body: str, axis_scores: dict) -> dict:
    raise NotImplementedError


def write_build_review(user_id: UUID, build_version_id: UUID, *, rating: int, title: str,
                       body: str, axis_scores: dict) -> dict:
    """build.owner == author, build_version published, usage_status assembled_self_reported 확인."""
    raise NotImplementedError


def publish(review_id: UUID, user_id: UUID) -> None:
    raise NotImplementedError


def list_pending_for_user(user_id: UUID) -> dict:
    """A7: 작성해야 할 리뷰 / 개봉 확인 / 내가 쓴 리뷰."""
    raise NotImplementedError
