"""dataset.* 저장소 — generation_run / review_sample / label_definition / review_label.

리뷰 근거 판정 학습 데이터셋 (명세서 §8.5). 데이터셋 담당 팀원 소유.
C17 실제/합성 원천 XOR, C18 단일 부모·분할 일치, C20 승인 정답 단일성, C21 운영 유입 방지.
합성 표본은 dataset 에만 저장, 운영 review_summary/aggregate 로 역유입 금지.
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class DatasetRepo(Repo):
    def start_generation(self, *, method: str, generator_name: str, generator_version: str,
                         recipe_version: str, generation_config: dict, idempotency_key: str) -> UUID:
        raise NotImplementedError

    def add_real_sample(self, *, target_level: str, content_kind: str, content_text: str,
                        content_hash: str, split_group_id: UUID,
                        source_summary_id: UUID | None = None,
                        source_review_revision_id: UUID | None = None,
                        external_dataset_ref: dict | None = None,
                        subject_id: UUID | None = None,
                        purchase_verified: bool | None = None,
                        purchase_verification_ref: dict | None = None,
                        review_posted_at=None, analysis_snapshot: dict | None = None) -> UUID:
        """실제 표본: 세 원천 중 정확히 하나."""
        raise NotImplementedError

    def add_synthetic_sample(self, parent_sample_id: UUID, generation_run_id: UUID,
                             generation_item_key: str, *, target_level: str,
                             content_text: str, content_hash: str, split_group_id: UUID,
                             context_snapshot: dict, analysis_snapshot: dict) -> UUID:
        """합성 표본: 부모 1개 필수, is_synthetic=true, 부모 메타 복사 금지(C24)."""
        raise NotImplementedError

    def set_split(self, split_group_id: UUID, split: str) -> None:
        """그룹 단위로 train/validation/test. 부모가 train 인 경우만 증강(C18)."""
        raise NotImplementedError

    def add_label(self, sample_id: UUID, label_definition_id: UUID, *, revision_no: int,
                  label_value: dict, label_origin: str, labeler_ref: str,
                  labeling_config: dict, evidence_snapshot: dict,
                  annotator_user_id: UUID | None = None, confidence=None) -> UUID:
        """자동 라벨은 pending. 모델 예측을 승인 정답으로 덮어쓰지 않음(§8.5)."""
        raise NotImplementedError

    def approve_label(self, label_id: UUID, reviewer_user_id: UUID) -> None:
        """기존 approved → superseded, 새 라벨 → approved 원자 처리(C20)."""
        raise NotImplementedError
