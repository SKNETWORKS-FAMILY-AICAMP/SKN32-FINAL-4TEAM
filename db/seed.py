#!/usr/bin/env python3
"""최소 기준 데이터 seed — config.domain / config.domain_version.

config/categories/*.yaml 을 그대로 domain_version.definition 에 적재한다. 멱등
(코드 존재하면 건너뜀). computer 는 status='active'(게시), baby 는 'draft'(스텁).

P0 develop 정렬 v3: shared.unit 은 0012_schema_reduction_safe_subset.sql 이 이미
제거했다(단위 코드값은 catalog/planning 각 unit_code 컬럼에 문자열로만 남는다) —
더 이상 존재하지 않는 테이블에 INSERT하지 않는다.

    DATABASE_URL=... python db/seed.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from psycopg.rows import dict_row

from src.config import CATEGORY_DIR  # noqa: E402
from src.db import get_conn  # noqa: E402

_DOMAINS = [
    ("computer", "컴퓨터 (PC 본체 조립)", "active"),
    ("baby", "유아용품", "draft"),
]


def _load(code: str) -> dict:
    return yaml.safe_load((CATEGORY_DIR / f"{code}.yaml").read_text(encoding="utf-8"))


def main() -> int:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        for code, name, status in _DOMAINS:
            cur.execute("SELECT id, status FROM config.domain WHERE code = %s", (code,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO config.domain (code, name, status) VALUES (%s, %s, %s) RETURNING id",
                    (code, name, status),
                )
                domain_id = cur.fetchone()["id"]
                print(f"domain 생성: {code} ({status})")
            else:
                domain_id = row["id"]
                if row["status"] != status:
                    cur.execute("UPDATE config.domain SET status = %s WHERE id = %s", (status, domain_id))
                    print(f"domain 갱신: {code} status → {status}")

            cur.execute(
                "SELECT id FROM config.domain_version WHERE domain_id = %s ORDER BY version_no DESC LIMIT 1",
                (domain_id,),
            )
            if cur.fetchone() is not None:
                print(f"domain_version 이미 있음: {code} — 건너뜀")
                continue

            definition = _load(code)
            attribute_schema = definition.get("slot_schema", {})
            content = json.dumps(definition, ensure_ascii=False, sort_keys=True)
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            cur.execute(
                """
                INSERT INTO config.domain_version
                  (domain_id, version_no, definition, attribute_schema, content_hash)
                VALUES (%s, 1, %s::jsonb, %s::jsonb, %s)
                """,
                (domain_id, json.dumps(definition, ensure_ascii=False),
                 json.dumps(attribute_schema, ensure_ascii=False), content_hash),
            )
            print(f"domain_version 생성: {code} v1")
    print("seed 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
