"""RecommendResultOut 계약 검증 (docs/frontend_외부수정요청.md §D-4-2).

이전엔 recommendation_run_id/candidates 모양(구 계약)을 검증했으나, 프론트 계약서가
list_id/run_id/items 모양(§D-4-2)으로 확정되면서 스키마가 교체됐다 — 이 테스트도 같이 갱신.
"""
from fastapi import FastAPI

from src.schemas import ItemOut, ProductOut, RecommendAcceptedOut, RecommendResultOut, TextStatusOut


def test_recommendation_response_is_explicit_in_openapi() -> None:
    app = FastAPI()

    @app.get("/result", response_model=RecommendResultOut)
    def result() -> dict:
        return {}

    schema = app.openapi()["components"]["schemas"]
    response = schema["RecommendResultOut"]
    assert {"list_id", "run_id", "status", "items", "totals", "verification", "explanation"} <= set(
        response["properties"]
    )
    assert response["properties"]["items"]["items"]["$ref"].endswith("/ItemOut")
    item = schema["ItemOut"]
    assert {"item_id", "slot", "product", "price", "reason", "checks"} <= set(item["properties"])


def test_recommend_accepted_shape() -> None:
    accepted = RecommendAcceptedOut(run_id="run-1")
    assert accepted.model_dump() == {"run_id": "run-1", "status": "running"}


def test_result_out_builds_from_plain_dict() -> None:
    result = RecommendResultOut(
        list_id="list-1", run_id="run-1", status="done", category="computer",
        items=[
            ItemOut(
                item_id="item-1", slot="GPU", slot_label="그래픽카드",
                product=ProductOut(product_key="rtx-4060", name="GeForce RTX 4060"),
                price=330000, reason=TextStatusOut(status="ready", text="예산 안에서 성능이 가장 좋습니다."),
                checks=TextStatusOut(status="pending"),
            )
        ],
    )
    assert result.items[0].product.name == "GeForce RTX 4060"
    assert result.explanation.status == "pending"  # 기본값


def test_mutable_schema_defaults_are_not_shared() -> None:
    first = RecommendResultOut(list_id="list-1", run_id="run-1", status="done", category="computer")
    second = RecommendResultOut(list_id="list-2", run_id="run-2", status="done", category="computer")

    first.items.append(
        ItemOut(
            item_id="item-1", slot="GPU", slot_label="그래픽카드",
            product=ProductOut(product_key="rtx-4060", name="GeForce RTX 4060"),
            price=330000, reason=TextStatusOut(status="pending"), checks=TextStatusOut(status="pending"),
        )
    )
    assert second.items == []
