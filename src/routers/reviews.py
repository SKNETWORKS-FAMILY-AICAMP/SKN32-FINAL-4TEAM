"""/reviews/* — A7 부품/전체 PC 리뷰 작성·게시. JWT 필수.

리뷰 상세 조회(S5, 정제 전후 평점·요약 3건)는 /session 결과에 포함되거나 별도 GET.
"""
from __future__ import annotations

from fastapi import APIRouter

from src import schemas

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


@router.get("/summary/{product_key}")
def review_summary(product_key: str) -> dict:
    """S5 리뷰 상세: 정제 전/후 평점, 항목별 평가, 요약 3건 + 출처·조회시점."""
    raise NotImplementedError
