#!/usr/bin/env python3
"""최소 기준 데이터 seed — config.domain.

config/categories/*.yaml 을 그대로 domain.definition 에 적재한다 (P0 v3: domain_version
테이블은 제거됨, 현재 정의는 domain 컬럼에만 존재). 멱등(코드+content_hash 존재하면 건너뜀).

두 카테고리 모두 status='active' 로 게시한다 — 이 행은 "조건 대화 규칙의 게시본"이고
런타임(plan_revision.domain_snapshot)이 그대로 복사해 쓰는 유일한 출처다(P0 SR07).
baby 의 추천 엔진 미구현(yaml status: stub)은 별개 게이트이며 P5 까지 501 로 남는다.
이미 게시(active)된 도메인을 미게시 정의로 덮어쓰는 것은 거부한다(P0 SR08).

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
    ("baby", "유아용품", "active"),
]


class PublishedDomainDemotion(RuntimeError):
    """게시된 도메인을 미게시 상태/정의로 되돌리려 할 때."""


def _load(code: str) -> dict:
    return yaml.safe_load((CATEGORY_DIR / f"{code}.yaml").read_text(encoding="utf-8"))


def upsert_domain(cur, code: str, name: str, status: str, definition: dict) -> str:
    """도메인 1행 upsert. 반환값: 'created' | 'unchanged' | 'updated'.

    게시(active)된 행을 draft/disabled 로 끌어내리거나 빈 정의로 덮어쓰는 seed 는
    거부한다 — 미게시 정의가 게시본을 밀어내지 못하게 하는 SR08 게이트.
    """
    attribute_schema = definition.get("slot_schema", {})
    content = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    if status == "active" and not definition:
        raise PublishedDomainDemotion(f"{code}: 빈 정의는 게시할 수 없습니다")

    cur.execute("SELECT id, status, content_hash FROM config.domain WHERE code = %s", (code,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """INSERT INTO config.domain
               (code, name, status, current_version_no, definition, attribute_schema, content_hash)
               VALUES (%s, %s, %s, 1, %s::jsonb, %s::jsonb, %s) RETURNING id""",
            (code, name, status, json.dumps(definition, ensure_ascii=False),
             json.dumps(attribute_schema, ensure_ascii=False), content_hash),
        )
        cur.fetchone()
        return "created"

    if row["status"] == "active" and status != "active":
        raise PublishedDomainDemotion(
            f"{code}: 이미 게시된 도메인을 '{status}' 로 되돌릴 수 없습니다 (게시본 보호)"
        )
    if row["content_hash"] == content_hash and row["status"] == status:
        return "unchanged"
    cur.execute(
        """UPDATE config.domain SET status=%s, current_version_no=1, definition=%s::jsonb,
             attribute_schema=%s::jsonb, content_hash=%s WHERE id=%s""",
        (status, json.dumps(definition, ensure_ascii=False),
         json.dumps(attribute_schema, ensure_ascii=False), content_hash, row["id"]),
    )
    return "updated"


def main() -> int:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        for code, name, status in _DOMAINS:
            outcome = upsert_domain(cur, code, name, status, _load(code))
            if outcome == "created":
                print(f"domain 생성: {code} v1 ({status})")
            elif outcome == "unchanged":
                print(f"domain 변경 없음: {code} — content_hash 동일")
            else:
                print(f"domain 갱신: {code} ({status})")
    print("seed 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
