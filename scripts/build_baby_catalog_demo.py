"""Build the committed default seed input data/baby/catalog_demo_v1.json.

Deterministic transform: reuses generate_baby_products.generate_dataset() (seeded,
validated) for a reviewed subset of categories that the 9 need-area rules in
config/baby_requirement_rules.yaml actually reference, converts each record into
the P2 CONTRACTS data-contract shape (product_key/variant_key/offer/facts/...),
then appends a small set of hand-authored fixtures:

  - the exact SYN-STROLLER-001 / SYN-STROLLER-001-GREY identity already used by
    the RAG stroller fixture (data/synthetic_manuals/stroller_example.json,
    tests/fixtures/rag/stroller_cases.json) so seeded catalog rows and published
    manuals resolve to the SAME product/variant id (see stable_id reuse in
    src/repo/product_repo.py).
  - six named diagnostic options required by P2_catalog_requirements.md:
    a valid in-budget alternative, a record with a missing/unknown identifier,
    an over-budget option, an option with an active *synthetic* recall fact, an
    option with an explicitly unknown certification fact, and a car-seat option
    that is not applicable to a newborn (no fabricated real KC numbers).

Not a random/live generator run: this script is committed source, and its output
data/baby/catalog_demo_v1.json is the committed deterministic artifact. Re-run
only when the curation below changes.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from generate_baby_products import generate_dataset, load_dictionary  # noqa: E402

DATASET_VERSION = "baby-demo-v1"
OUT = ROOT / "data" / "baby" / "catalog_demo_v1.json"
GENERATOR_SEED = 42

# category_code == slot_key for baby (each product has exactly one canonical
# category/slot; a *need* maps to several slot_keys via config/baby_requirement_rules.yaml).
CATEGORIES_FOR_DEMO = [
    "stroller", "car_seat", "carrier", "crib", "sleepwear", "bottle", "formula",
    "high_chair", "baby_food", "cup", "bib", "diaper", "wipes", "bath", "skincare",
    "mat", "gate", "thermometer",
]
PER_CATEGORY = 2

CATEGORY_NAME_KO = {
    "stroller": "유모차", "car_seat": "카시트", "carrier": "아기띠", "crib": "아기침대",
    "sleepwear": "수면조끼/우주복", "bottle": "젖병", "formula": "분유", "high_chair": "하이체어",
    "baby_food": "이유식", "cup": "빨대컵", "bib": "턱받이", "diaper": "기저귀", "wipes": "물티슈",
    "bath": "목욕용품", "skincare": "스킨케어", "mat": "놀이매트", "gate": "안전문/펜스",
    "thermometer": "체온계",
}


def _pack_semantics(p: dict) -> tuple[float, str, float]:
    """CA03: 팩 수(pack_quantity)와 팩당 낱개 수(unit_qty)를 별도로 저장한다 —
    2팩 x 40매를 80매 단가로 청구하지 않는다. diaper/wipes 만 팩 스펙을 갖는다."""
    specs = p["specs"]
    if p["category_id"] == "diaper" and "pack_count" in specs:
        return float(specs["pack_count"]), "pack", float(specs["pieces_per_pack"])
    if p["category_id"] == "wipes" and "pack_count" in specs:
        return float(specs["pack_count"]), "pack", float(specs["sheets_per_pack"])
    return 1.0, "each", 1.0


def generator_record_to_catalog_record(p: dict, *, corpus="synthetic") -> dict:
    offer = p["offer"]
    pack_quantity, unit_code, unit_qty = _pack_semantics(p)
    return {
        "dataset_version": DATASET_VERSION,
        "is_synthetic": True,
        "product_key": p["product_id"],
        "variant_key": p["variant_id"],
        "name": f"{p['brand']} {p['model']}",
        "brand": p["brand"],
        "category_code": p["category_id"],
        "slot_key": p["category_id"],
        "market": p["market"],
        "language": "ko",
        "corpus": corpus,
        "pack_quantity": pack_quantity,
        "unit_code": unit_code,
        "unit_qty": unit_qty,
        "attributes": {"specs": p["specs"], "eligibility": p["eligibility"],
                       "components": p["components"], "profile": p["dataset_meta"]["profile_id"]},
        "offer": {
            "merchant_key": "baby-demo-synthetic",
            "external_offer_id": p["variant_id"],
            "price": offer["price_krw"],
            "currency": "KRW",
            "observed_at": "2026-09-13T00:00:00Z",
            "stock_status": "available" if offer["stock"] > 0 else "sold_out",
            "purchase_url": None,
        },
        "facts": [
            {"key": "simulated_safety_status", "value": p["simulated_safety_status"],
             "unit": None, "verification_status": "unknown"},
        ],
        "manual_ref": None,
    }


def curated_fixtures() -> list[dict]:
    def rec(**kw) -> dict:
        base = {
            "dataset_version": DATASET_VERSION, "is_synthetic": True, "market": "KR_DEMO",
            "language": "ko", "corpus": "synthetic", "pack_quantity": 1, "unit_code": "each",
            "unit_qty": 1, "attributes": {}, "facts": [], "manual_ref": None,
        }
        base.update(kw)
        return base

    fixtures = []

    # Exact RAG fixture identity — must byte-match data/synthetic_manuals/stroller_example.json.
    fixtures.append(rec(
        product_key="SYN-STROLLER-001", variant_key="SYN-STROLLER-001-GREY",
        name="가상브랜드_새봄 SYN-LITE-A", brand="가상브랜드_새봄",
        category_code="stroller", slot_key="stroller",
        attributes={"specs": {
            "type": "compact", "assembled_weight_kg": 6.5,
            "folded_cm": {"width": 45, "depth": 25, "height": 55},
            "unfolded_cm": {"width": 55, "depth": 85, "height": 105},
            "seat_max_kg": 22, "basket_max_kg": 3, "newborn_setup": "not_supported",
            "one_hand_fold": True, "self_standing_folded": False,
            "compatible_adapter_ids": [],
        }, "eligibility": [{
            "mode": "seat", "min_age_months": 6, "max_weight_kg": 22,
            "requires": ["independent_sitting"], "stop_when_any": ["weight_over_22kg"],
        }]},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-STROLLER-001-GREY",
               "price": 290000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
        manual_ref="SYN-MAN-SYN-STROLLER-001",
    ))

    # 1) valid alternative — in-budget, different profile, same slot as the exact fixture.
    fixtures.append(rec(
        product_key="SYN-STROLLER-002", variant_key="SYN-STROLLER-002-NAVY",
        name="가상브랜드_도담 SYN-STANDARD-B", brand="가상브랜드_도담",
        category_code="stroller", slot_key="stroller",
        attributes={"specs": {"type": "standard", "assembled_weight_kg": 10.5,
                               "seat_max_kg": 22, "newborn_setup": "not_supported"},
                    "eligibility": [{"mode": "seat", "min_age_months": 6, "max_weight_kg": 22,
                                      "requires": ["independent_sitting"]}]},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-STROLLER-002-NAVY",
               "price": 260000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
    ))

    # 2) missing identifier — no GTIN/manual_ref, identifier completeness explicitly unknown.
    fixtures.append(rec(
        product_key="SYN-CARSEAT-NOID-001", variant_key="SYN-CARSEAT-NOID-001-DEFAULT",
        name="가상브랜드_모아 SYN-NOID-CS", brand="가상브랜드_모아",
        category_code="car_seat", slot_key="car_seat",
        attributes={"specs": {"seat_type": "convertible", "installation": "isofix"}},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-CARSEAT-NOID-001-DEFAULT",
               "price": 320000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
        facts=[{"key": "product_identifier_completeness", "value": "missing_gtin",
                "unit": None, "verification_status": "unknown"}],
    ))

    # 3) over-budget — priced above the CA02 fixture's budget_max (300000).
    fixtures.append(rec(
        product_key="SYN-STROLLER-003", variant_key="SYN-STROLLER-003-BLACK",
        name="가상브랜드_새봄 SYN-PREMIUM-C", brand="가상브랜드_새봄",
        category_code="stroller", slot_key="stroller",
        attributes={"specs": {"type": "standard", "assembled_weight_kg": 12.5,
                               "seat_max_kg": 22, "newborn_setup": "not_supported"},
                    "eligibility": [{"mode": "seat", "min_age_months": 6, "max_weight_kg": 22,
                                      "requires": ["independent_sitting"]}]},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-STROLLER-003-BLACK",
               "price": 1200000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
    ))

    # CA03 exact case: 2 packs of 40 diapers → pack_quantity=2, unit_qty=40, never 80
    # charged packs, and independently queryable from any other diaper variant.
    fixtures.append(rec(
        product_key="SYN-DIAPER-CA03-001", variant_key="SYN-DIAPER-CA03-001-M",
        name="가상브랜드_새봄 SYN-DIAPER-2PACK-M", brand="가상브랜드_새봄",
        category_code="diaper", slot_key="diaper", pack_quantity=2, unit_code="pack", unit_qty=40,
        attributes={"specs": {"type": "disposable", "size_label": "SYN-M",
                               "weight_range_kg": {"min": 6, "max": 11}}},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-DIAPER-CA03-001-M",
               "price": 24000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
    ))

    # 4) active synthetic recall — feeding slot, explicitly labeled synthetic recall (not real).
    fixtures.append(rec(
        product_key="SYN-BOTTLE-RECALL-001", variant_key="SYN-BOTTLE-RECALL-001-240ML",
        name="가상브랜드_도담 SYN-RECALLED-BOTTLE", brand="가상브랜드_도담",
        category_code="bottle", slot_key="bottle",
        attributes={"specs": {"flow_grade": "medium", "nipple_material": "silicone"}},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-BOTTLE-RECALL-001-240ML",
               "price": 18000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
        facts=[{"key": "recall_status", "value": "active_synthetic_recall",
                "unit": None, "verification_status": "verified"}],
    ))

    # 5) unknown certification — explicitly no fabricated real KC number.
    fixtures.append(rec(
        product_key="SYN-CARSEAT-CERT-001", variant_key="SYN-CARSEAT-CERT-001-DEFAULT",
        name="가상브랜드_모아 SYN-UNVERIFIED-CS", brand="가상브랜드_모아",
        category_code="car_seat", slot_key="car_seat",
        attributes={"specs": {"seat_type": "convertible", "installation": "isofix"}},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-CARSEAT-CERT-001-DEFAULT",
               "price": 340000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
        facts=[{"key": "kc_certification_number", "value": None,
                "unit": None, "verification_status": "unknown"}],
    ))

    # 6) newborn-inapplicable seat — convertible only, no newborn insert, min height excludes 0mo.
    fixtures.append(rec(
        product_key="SYN-CARSEAT-CONV-001", variant_key="SYN-CARSEAT-CONV-001-DEFAULT",
        name="가상브랜드_새봄 SYN-CONVERTIBLE-CS", brand="가상브랜드_새봄",
        category_code="car_seat", slot_key="car_seat",
        attributes={"specs": {"seat_type": "convertible", "installation": "isofix",
                               "newborn_insert_included": False},
                    "eligibility": [{"mode": "rear_facing", "min_height_cm": 60,
                                      "max_height_cm": 105, "max_weight_kg": 19}]},
        offer={"merchant_key": "baby-demo-synthetic", "external_offer_id": "SYN-CARSEAT-CONV-001-DEFAULT",
               "price": 300000, "currency": "KRW", "observed_at": "2026-09-13T00:00:00Z",
               "stock_status": "available", "purchase_url": None},
        facts=[{"key": "newborn_applicable", "value": False,
                "unit": None, "verification_status": "verified"}],
    ))

    return fixtures


def build() -> dict:
    dictionary = load_dictionary()
    bundle = generate_dataset(count=PER_CATEGORY * len(CATEGORIES_FOR_DEMO), seed=GENERATOR_SEED,
                              categories=CATEGORIES_FOR_DEMO, dictionary=dictionary)
    records = [generator_record_to_catalog_record(p) for p in bundle["products"]]
    records.extend(curated_fixtures())
    keys = [(r["product_key"], r["variant_key"]) for r in records]
    assert len(keys) == len(set(keys)), "duplicate product_key/variant_key in demo catalog"
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest = {
        "dataset_version": DATASET_VERSION,
        "generator_seed": GENERATOR_SEED,
        "generator_categories": CATEGORIES_FOR_DEMO,
        "dictionary_sha256": bundle["metadata"]["dictionary_sha256"],
        "records_sha256": hashlib.sha256(canonical).hexdigest(),
        "record_count": len(records),
        "is_synthetic": True,
        "notice": "가상 데이터. 실제 상품·가격·인증·리콜 정보가 아님. KC 인증번호를 조작하지 않음.",
    }
    return {"manifest": manifest, "records": records}


def main() -> int:
    out = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} — {out['manifest']['record_count']} records, "
          f"records_sha256={out['manifest']['records_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
