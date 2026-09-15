#!/usr/bin/env python3
"""유아용품 카탈로그 시딩 — data/baby/catalog_demo_v1.json(기본) → catalog.*.

    DATABASE_URL=... uv run python scripts/seed_baby_catalog.py \\
        --corpus synthetic --dataset-version baby-demo-v1

--input 을 생략하면 커밋된 기본 시드 data/baby/catalog_demo_v1.json 을 쓴다
(P2_catalog_requirements.md "Deliver default seed input ... make the documented
seed CLI use it when --input is omitted"). 트랜잭션 하나로 전부 검증한 뒤
적재한다 — 입력이 잘못되면 DB에 아무것도 쓰지 않고 롤백한다(CA01/CA04).
같은 파일을 다시 실행해도 product/variant id 는 동일하고(product_key/variant_key
에서 결정적으로 파생), 가격이 그대로면 새 관측 행을 만들지 않으며, 가격이
바뀌면 과거 행을 덮어쓰지 않고 새 행을 추가한다(CA01).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "baby" / "catalog_demo_v1.json"

_REQUIRED_FIELDS = [
    "dataset_version", "is_synthetic", "product_key", "variant_key", "name", "brand",
    "category_code", "slot_key", "market", "language", "corpus", "pack_quantity",
    "unit_code", "unit_qty", "attributes", "offer", "facts",
]
_VALID_UNIT_CODES = {"each", "pack", "g", "mL", "kg"}
_VALID_STOCK_STATUS = {"available", "sold_out", "unknown"}
_VALID_VERIFICATION_STATUS = {None, "unknown", "verified", "proposed", "revoked"}


class SeedInputError(ValueError):
    """시드 입력이 DATA CONTRACT 를 위반함 — DB에 아무것도 쓰기 전에 발생해야 한다."""


@dataclass
class SeedReport:
    dataset_version: str
    corpus: str
    dry_run: bool = False
    products: int = 0
    variants: int = 0
    offers: int = 0
    observations_created: int = 0
    observations_unchanged: int = 0
    data_gap_records: list[str] = field(default_factory=list)
    product_ids: dict[str, str] = field(default_factory=dict)
    variant_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "dataset_version": self.dataset_version, "corpus": self.corpus, "dry_run": self.dry_run,
            "products": self.products, "variants": self.variants, "offers": self.offers,
            "observations_created": self.observations_created,
            "observations_unchanged": self.observations_unchanged,
            "data_gap_records": self.data_gap_records,
            "product_ids": self.product_ids, "variant_ids": self.variant_ids,
        }


def load_input(path: Path) -> tuple[dict, list[dict]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if "records" not in doc:
        raise SeedInputError(f"{path}: 최상위 'records' 없음")
    return doc.get("manifest", {}), doc["records"]


def validate_record(r: dict, *, dataset_version: str, corpus: str, index: int) -> None:
    missing = [k for k in _REQUIRED_FIELDS if k not in r]
    if missing:
        raise SeedInputError(f"record[{index}] ({r.get('product_key')!r}): 필수 필드 누락 {missing}")
    if r["dataset_version"] != dataset_version:
        raise SeedInputError(
            f"record[{index}]: dataset_version 불일치 {r['dataset_version']!r} != {dataset_version!r}")
    if r["corpus"] != corpus:
        raise SeedInputError(f"record[{index}]: corpus 불일치 {r['corpus']!r} != {corpus!r}")
    if bool(r["is_synthetic"]) != (corpus == "synthetic"):
        raise SeedInputError(f"record[{index}]: is_synthetic 이 corpus 와 모순됨")
    if not isinstance(r["product_key"], str) or not r["product_key"]:
        raise SeedInputError(f"record[{index}]: product_key 필요")
    if not isinstance(r["variant_key"], str) or not r["variant_key"]:
        raise SeedInputError(f"record[{index}]: variant_key 필요")
    if r["category_code"] is not None and not isinstance(r["category_code"], str):
        raise SeedInputError(f"record[{index}]: category_code 는 string 이거나 null")
    if r["unit_code"] not in _VALID_UNIT_CODES:
        raise SeedInputError(f"record[{index}]: 지원하지 않는 unit_code {r['unit_code']!r}")
    if not (isinstance(r["pack_quantity"], (int, float)) and r["pack_quantity"] > 0):
        raise SeedInputError(f"record[{index}]: pack_quantity 는 양수여야 함")
    if not (isinstance(r["unit_qty"], (int, float)) and r["unit_qty"] > 0):
        raise SeedInputError(f"record[{index}]: unit_qty 는 양수여야 함")
    offer = r.get("offer") or {}
    for k in ("merchant_key", "external_offer_id", "price", "currency", "observed_at", "stock_status"):
        if k not in offer:
            raise SeedInputError(f"record[{index}]: offer.{k} 없음")
    if offer["price"] is not None and (not isinstance(offer["price"], (int, float)) or offer["price"] < 0):
        raise SeedInputError(f"record[{index}]: offer.price 값이 잘못됨")
    if offer["stock_status"] not in _VALID_STOCK_STATUS:
        raise SeedInputError(f"record[{index}]: offer.stock_status 값이 잘못됨 {offer['stock_status']!r}")
    try:
        datetime.fromisoformat(offer["observed_at"].replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise SeedInputError(f"record[{index}]: offer.observed_at 파싱 실패: {exc}") from exc
    for fact in r.get("facts") or []:
        if "key" not in fact or "value" not in fact:
            raise SeedInputError(f"record[{index}]: facts[].key/value 없음")
        if fact.get("verification_status") not in _VALID_VERIFICATION_STATUS:
            raise SeedInputError(f"record[{index}]: 잘못된 verification_status {fact.get('verification_status')!r}")


def seed_catalog(conn, records: list[dict], *, dataset_version: str, corpus: str = "synthetic",
                 dry_run: bool = False) -> SeedReport:
    """records(DATA CONTRACT 레코드 목록) → catalog.* 멱등 적재.

    전체를 먼저 검증(잘못된 입력이면 DB에 아무것도 쓰지 않고 예외)한 뒤, 하나의
    트랜잭션으로 upsert 한다. 재실행해도 동일 product_key/variant_key 는 동일한
    id 를 얻는다(corpus=synthetic: stable_id 파생 / corpus=real: brand+model 조회).
    """
    seen_keys: set[tuple[str, str]] = set()
    for i, r in enumerate(records):
        validate_record(r, dataset_version=dataset_version, corpus=corpus, index=i)
        key = (r["product_key"], r["variant_key"])
        if key in seen_keys:
            raise SeedInputError(f"record[{i}]: product_key/variant_key 중복 {key}")
        seen_keys.add(key)

    report = SeedReport(dataset_version=dataset_version, corpus=corpus, dry_run=dry_run)
    if dry_run:
        report.products = len(records)
        return report

    repo = ProductRepo(conn)
    with conn.transaction():
        for r in records:
            if r["category_code"] is None:
                report.data_gap_records.append(r["product_key"])
                continue
            category_id = repo.resolve_category_id(r["category_code"])

            facts_by_key = {
                f["key"]: {"value": f.get("value"), "unit": f.get("unit"),
                          "verification_status": f.get("verification_status") or "unknown"}
                for f in r.get("facts") or []
            }
            attributes = {
                "corpus": r["corpus"], "market": r["market"], "language": r["language"],
                "product_key": r["product_key"], "specs": r["attributes"],
                "facts_by_key": facts_by_key, "manual_ref": r.get("manual_ref"),
            }

            # catalog.product_variant has no unit_qty column (only pack_quantity/unit_code),
            # so the pack-internal quantity (e.g. 40 pieces per pack) is carried in variant
            # attributes and must be read back exactly by ProductRepo.baby_candidates_by_category
            # — losing it here would silently turn "2 packs of 40" into "2 of 1" downstream (R4).
            variant_attributes = {"slot_key": r["slot_key"], "unit_qty": r["unit_qty"]}
            if corpus == "synthetic":
                product_id = repo.upsert_synthetic_product(
                    product_key=r["product_key"], name=r["name"], brand=r["brand"],
                    category_id=category_id, product_type=r["slot_key"], attributes=attributes)
                variant_id = repo.upsert_synthetic_variant(
                    product_id, r["variant_key"], attributes=variant_attributes,
                    pack_quantity=r["pack_quantity"], unit_code=r["unit_code"])
            else:
                product_id = repo.upsert_product(
                    name=r["name"], brand=r["brand"], model=r["product_key"],
                    product_type=r["slot_key"], attributes=attributes)
                variant_id = repo.upsert_variant(
                    product_id, r["variant_key"], attributes=variant_attributes,
                    pack_quantity=r["pack_quantity"], unit_code=r["unit_code"])

            report.product_ids[r["product_key"]] = str(product_id)
            report.variant_ids[r["variant_key"]] = str(variant_id)
            report.products += 1
            report.variants += 1

            merchant_id = repo.upsert_merchant(
                "baby-demo" if corpus == "synthetic" else "baby-real",
                r["offer"]["merchant_key"], "데모 유아용품 판매처" if corpus == "synthetic" else r["offer"]["merchant_key"])
            # 실제 판매 URL이 없는 합성 항목은 상품명으로 실제 쇼핑몰 검색 결과 페이지로
            # 연결한다 — db/seed_catalog.py(컴퓨터 카탈로그)와 같은 이유·같은 방식.
            purchase_url = r["offer"].get("purchase_url") or (
                f"https://www.amazon.com/s?k={quote_plus(r['name'])}")
            offer_id = repo.upsert_offer(
                variant_id, merchant_id, r["offer"]["external_offer_id"], purchase_url)
            report.offers += 1

            observed_at = datetime.fromisoformat(r["offer"]["observed_at"].replace("Z", "+00:00"))
            quality_status = "valid" if r["offer"]["price"] is not None else "failed"
            source_name = f"seed_baby_catalog:{dataset_version}"
            # evidence.source.source_type CHECK only allows manufacturer/public_registry/
            # merchant/external_review/first_party/derived — synthetic demo pricing is
            # not observed from any real source, so 'derived' fits both corpora.
            source_type = "derived"
            source = repo._one("SELECT id FROM evidence.source WHERE name = %s", (source_name,))
            if source is None:
                source = repo._one(
                    "INSERT INTO evidence.source (name, source_type) VALUES (%s, %s) RETURNING id",
                    (source_name, source_type),
                )
            _, created = repo.add_observation_if_changed(
                offer_id, source_id=source["id"],
                observed_at=observed_at, price=r["offer"]["price"], currency=r["offer"]["currency"],
                stock_status=r["offer"]["stock_status"], quality_status=quality_status,
            )
            if created:
                report.observations_created += 1
            else:
                report.observations_unchanged += 1
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=None,
                        help=f"시드 JSON 경로 (기본값: {DEFAULT_INPUT.relative_to(ROOT)})")
    parser.add_argument("--dataset-version", default=None,
                        help="생략하면 입력 파일의 manifest.dataset_version 사용")
    parser.add_argument("--corpus", choices=["synthetic", "real"], default="synthetic")
    parser.add_argument("--dry-run", action="store_true", help="검증만 하고 DB에 쓰지 않음")
    args = parser.parse_args(argv)

    input_path = args.input or DEFAULT_INPUT
    try:
        manifest, records = load_input(input_path)
        dataset_version = args.dataset_version or manifest.get("dataset_version")
        if not dataset_version:
            raise SeedInputError("--dataset-version 이 없고 manifest 에도 없음")
        if args.dry_run:
            report = seed_catalog(None, records, dataset_version=dataset_version,
                                  corpus=args.corpus, dry_run=True)
        else:
            with get_conn() as conn:
                report = seed_catalog(conn, records, dataset_version=dataset_version,
                                      corpus=args.corpus, dry_run=False)
    except (SeedInputError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Error: {exc}\n")
        return 2

    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
