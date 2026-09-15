#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/baby/review_risk.json 합성 생성기 — ProductRiskStore(review_repo.py)가 읽는 "관계·행동 축"
산출물 스키마를 유아용품 카탈로그에 맞춰 만든다. PC(data/amazon23/pcparts_product_risk.json)와
같은 자리이지만 유아용품은 그런 실측 배치 산출물이 없어서, 합성 데모로 채운다.

- 입력  : data/baby/review_summaries.json (scripts/gen_baby_review_summaries.py 산출물 — n·평점 재사용)
- 출력  : data/baby/review_risk.json (meta/controls/products/cards, ProductRiskStore.REQUIRED_KEYS)
- 성격  : 데모용. 전부 합성값이고 alias(ASIN 매핑)가 없어 product_key 를 그대로 키로 쓴다.
- 재현성: product_key 해시 시드 → 재실행해도 동일.

사용:  python scripts/gen_baby_review_risk.py
"""
from __future__ import annotations
import json, hashlib, random, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARIES_JSON = ROOT / "data" / "baby" / "review_summaries.json"
OUT_JSON = ROOT / "data" / "baby" / "review_risk.json"

CONTROL_KEYS = ["burst7", "one_off_rate", "prolific_rate", "p5", "shared_reviewers", "deg",
                "short_span_rate", "verified_rate"]


def seeded_rng(product_key: str) -> random.Random:
    h = int(hashlib.sha256(("risk:" + product_key).encode("utf-8")).hexdigest(), 16)
    return random.Random(h)


def gen_one(entry: dict) -> dict:
    key = entry["product_key"]
    rng = seeded_rng(key)
    n = max(15, int(entry.get("total_reviews", 30)))
    mean_rating = float(entry.get("orig_rating", 4.4))

    first_day = rng.randint(0, 220)
    is_launch = rng.random() < 0.15
    burst7_start_day = first_day + (rng.randint(0, 6) if is_launch else rng.randint(10, 90))
    burst7 = round(rng.uniform(0.25, 0.55) if is_launch else rng.uniform(0.03, 0.18), 4)
    burst7_count = round(n * burst7)

    return {
        "product_key": key,
        "n": n,
        "mean_rating": round(mean_rating, 2),
        "p5": round(rng.uniform(0.42, 0.72), 4),
        "burst7": burst7,
        "burst7_count": burst7_count,
        "burst7_start_day": burst7_start_day,
        "first_day": first_day,
        "one_off_rate": round(rng.uniform(0.05, 0.32), 4),
        "prolific_rate": round(rng.uniform(0.02, 0.14), 4),
        "shared_reviewers": rng.randint(0, 18),
        "deg": rng.randint(0, 40),
        "short_span_rate": round(rng.uniform(0.05, 0.28), 4),
        "verified_rate": round(rng.uniform(0.55, 0.95), 4),
    }


def main() -> int:
    entries = json.loads(SUMMARIES_JSON.read_text(encoding="utf-8"))
    products = {}
    for e in entries:
        row = gen_one(e)
        products[row["product_key"]] = row

    controls = {k: round(statistics.median(p[k] for p in products.values()), 4) for k in CONTROL_KEYS}

    out = {
        "meta": {
            "min_reviews": 15,
            "labels": None,
            "control_scope": "Baby products (synthetic demo)",
            "source": "synthetic demo generator — scripts/gen_baby_review_risk.py",
        },
        "controls": controls,
        "products": products,
        "cards": {},
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"생성 완료: {len(products)} products -> {OUT_JSON}")
    print("controls (medians):", controls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
