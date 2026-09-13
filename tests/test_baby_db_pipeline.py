from src.pipeline import run_baby_db_pipeline

def test_baby_db_pipeline_excludes_unidentified_and_over_budget_candidates():
    basket, verification = run_baby_db_pipeline(list_id="l", slots={}, budget_max=100, candidates=[
        {"product_key":"seat", "variant_key":"v1", "name":"seat", "price":80},
        {"product_key":"unknown", "name":"missing", "price":1},
        {"product_key":"stroller", "variant_key":"v2", "name":"stroller", "price":30},
    ])
    assert [line.product_key for line in basket.buy_now] == ["seat"]
    assert basket.totals["total"] == 80
    assert [target.gray_axes[0] for target in verification.targets] == ["manual_verification_pending", "missing_catalog_identifier", "budget_exceeded"]
