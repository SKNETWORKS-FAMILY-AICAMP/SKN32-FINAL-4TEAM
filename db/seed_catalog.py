#!/usr/bin/env python3
"""컴퓨터 부품 카탈로그를 DB에 적재 — data/parts_list.csv → catalog.*.

src.repo.catalog_repo(엔진 [3-0]이 읽는 CSV 경로)와 완전히 같은 결정적 가격/티어
함수를 그대로 재사용한다 — 그래야 추천 엔진이 계산한 가격과 DB에 저장되는 가격이
어긋나지 않는다. 멱등(ON CONFLICT). 스펙 원문 확보 전까지의 데모용 브리지.

    DATABASE_URL=... python db/seed_catalog.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR  # noqa: E402
from src.db import get_conn  # noqa: E402
from src.repo.catalog_repo import TYPE_TO_SLOT, _load_rows, _mock_price, _mock_tier  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402

_SOURCE_NAME = "데모 합성 카탈로그"
_ASIN_MAP_CSV = DATA_DIR / "parts_asin_map.csv"


def _load_asin_map() -> dict[str, str]:
    """product_key → ASIN. 리뷰 분석에 쓴 것과 같은 매핑(data/parts_asin_map.csv) —
    있으면 검색 링크 대신 그 상품의 실제 Amazon 상세 페이지로 바로 연결한다(요청 R3)."""
    if not _ASIN_MAP_CSV.exists():
        return {}
    out: dict[str, str] = {}
    with _ASIN_MAP_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key, asin = (row.get("product_key") or "").strip(), (row.get("asin") or "").strip()
            if key and asin:
                out[key] = asin
    return out


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
        asin_map = _load_asin_map()

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
            # ASIN이 있으면(리뷰 분석에 쓴 것과 같은 매핑) 그 상품의 실제 상세 페이지로 —
            # "우리가 분석한 그 상품 페이지"라는 연결이 생긴다(요청 R3). 없으면 상품명으로
            # 실제 쇼핑몰 검색 결과 페이지로 연결한다 — 항상 유효하게 열리고, 검색 결과
            # 페이지 링크는 저작권·이용약관 이슈가 사실상 없다(단순 링크, 콘텐츠 복제 없음).
            asin = asin_map.get(pk)
            purchase_url = (f"https://www.amazon.com/dp/{asin}" if asin
                            else f"https://www.amazon.com/s?k={quote_plus(row['name'])}")
            offer_id = repo.upsert_offer(variant_id, merchant_id, pk, purchase_url)
            repo.add_observation(
                offer_id, source_id, observed_at=datetime.now(timezone.utc),
                price=price, stock_status="available", quality_status="valid",
            )
            n += 1
        print(f"seed_catalog: {n}개 부품 → product/variant/offer/observation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
