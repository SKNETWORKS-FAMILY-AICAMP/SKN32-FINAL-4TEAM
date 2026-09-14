#!/usr/bin/env python3
"""가상 유아용품 생성·검증·DB upsert를 한 번에 실행한다.

기본 실행은 결정적 생성기와 큐레이션 규칙으로 카탈로그 레코드를 메모리에서 만든 뒤,
기존 ``seed_baby_catalog.seed_catalog`` 경로로 실제 DB에 upsert 한다. 따라서 상품,
옵션, 판매처, 가격 관측값의 안정 ID·이력 보존·멱등성 규칙은 별도 시더를 실행할 때와
동일하다.

    uv run python scripts/generate_and_seed_baby_catalog.py
    uv run python scripts/generate_and_seed_baby_catalog.py --dry-run
    uv run python scripts/generate_and_seed_baby_catalog.py --write-catalog /tmp/baby.json

``DATABASE_URL``은 ``src.config``이 프로젝트 루트의 .env에서 읽는다. ``--dry-run``은
DB에 연결하거나 쓰지 않고 생성물과 시드 입력 계약만 검증한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_baby_catalog_demo import build  # noqa: E402
from seed_baby_catalog import seed_catalog  # noqa: E402


def generate_and_seed(*, dry_run: bool = False) -> tuple[dict, object]:
    """Build the canonical synthetic dataset and validate/upsert it atomically."""
    catalog = build()
    manifest = catalog["manifest"]
    records = catalog["records"]
    if dry_run:
        return catalog, seed_catalog(
            None, records, dataset_version=manifest["dataset_version"],
            corpus="synthetic", dry_run=True,
        )

    # Import lazily so --dry-run works without a configured database or driver.
    from src.db import get_conn

    with get_conn() as conn:
        report = seed_catalog(
            conn, records, dataset_version=manifest["dataset_version"], corpus="synthetic",
        )
    return catalog, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="생성·입력 검증만 하고 DB에 쓰지 않음")
    parser.add_argument("--write-catalog", type=Path, help="생성한 DB 입력 JSON을 함께 저장할 경로")
    args = parser.parse_args(argv)

    catalog, report = generate_and_seed(dry_run=args.dry_run)
    if args.write_catalog:
        args.write_catalog.parent.mkdir(parents=True, exist_ok=True)
        args.write_catalog.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = report.to_dict()
    result["generated_record_count"] = catalog["manifest"]["record_count"]
    result["records_sha256"] = catalog["manifest"]["records_sha256"]
    if args.write_catalog:
        result["catalog_output"] = str(args.write_catalog.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
