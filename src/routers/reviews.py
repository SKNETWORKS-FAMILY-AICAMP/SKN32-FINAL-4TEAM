"""/reviews/* — A7 부품/전체 PC 리뷰 작성·게시. JWT 필수.

리뷰 상세 조회(S5, 정제 전후 평점·요약 3건)는 /session 결과에 포함되거나 별도 GET.
작성 요청의 선택 필드 `telemetry`(schemas.ReviewTelemetry)는 폼 계측값 — 횟수·시간만 받고
`review_revision.usage_context.telemetry` 로 저장한다. 프론트는 붙여넣기·키 입력 이벤트를
세기만 하고 내용은 보내지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter

from src import schemas
from src.services import review_service

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/pending")
def pending() -> dict:
    """작성해야 할 리뷰 / 개봉 확인 / 내가 쓴 리뷰."""
    raise NotImplementedError


@router.post("/part")
def write_part(body: schemas.PartReviewIn) -> dict:
    raise NotImplementedError


@router.post("/build")
def write_build(body: schemas.BuildReviewIn) -> dict:
    raise NotImplementedError


@router.post("/{review_id}/publish")
def publish(review_id: str) -> dict:
    raise NotImplementedError


@router.get("/summary/{product_key}", response_model=schemas.ReviewSummaryOut)
def review_summary(product_key: str) -> schemas.ReviewSummaryOut:
    """S5 리뷰 상세 — 실측 관측(관계·행동 축)과 합성 데모 블록을 분리해 낸다.

    product_key 는 엔진 키(`amd-ryzen-5-5600`)·요약 키·ASIN 모두 받는다.
    읽기 전용 공개 데이터라 인증 없이 둔다 (auth 구현 후 optional_principal 로 소유 세션 연결).
    """
    return review_service.get_summary(product_key)
