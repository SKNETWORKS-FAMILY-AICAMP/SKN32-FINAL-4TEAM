#!/usr/bin/env python3
"""컴퓨터 부품 카탈로그를 DB에 적재 — data/parts_list.csv → catalog.*.

src.repo.catalog_repo(엔진 [3-0]이 읽는 CSV 경로)와 완전히 같은 결정적 가격/티어
함수를 그대로 재사용한다 — 그래야 추천 엔진이 계산한 가격과 DB에 저장되는 가격이
어긋나지 않는다. 멱등(ON CONFLICT). 스펙 원문 확보 전까지의 데모용 브리지.

    DATABASE_URL=... python db/seed_catalog.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn  # noqa: E402
from src.repo.catalog_repo import TYPE_TO_SLOT, _load_rows, _mock_price, _mock_tier  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402

_SOURCE_NAME = "데모 합성 카탈로그"


def main() -> int:
    with get_conn() as conn:
        repo = ProductRepo(conn)
        source = repo._one(
            "SELECT id FROM evidence.source WHERE name = %s", (_SOURCE_NAME,)
        )
        if source is None:
            source = repo._one(
                "INSERT INTO evidence.source (name, source_type) VALUES (%s, 'derived') RETURNING id",
                (_SOURCE_NAME,),
            )
        source_id = source["id"]
        merchant_id = repo.upsert_merchant("demo", "demo-seller", "데모 판매처")

        n = 0
        for row in _load_rows():
            slot = TYPE_TO_SLOT.get(row["type"])
            if slot is None:
                continue
            pk = row["name"].lower().replace(" ", "-")
            price = _mock_price(pk, slot)
            tier = _mock_tier(pk)

            product_id = repo.upsert_product(
                name=row["name"], brand=row["brand"], model=row["name"],
                product_type=row["type"], attributes={"slot": slot, "perf_tier": tier},
            )
            variant_id = repo.upsert_variant(
                product_id, "default", attributes={"slot": slot, "perf_tier": tier},
            )
            offer_id = repo.upsert_offer(variant_id, merchant_id, pk, f"https://example.com/buy/{pk}")
            repo.add_observation(
                offer_id, source_id, observed_at=datetime.now(timezone.utc),
                price=price, stock_status="available", quality_status="valid",
            )
            n += 1
        print(f"seed_catalog: {n}개 부품 → product/variant/offer/observation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
