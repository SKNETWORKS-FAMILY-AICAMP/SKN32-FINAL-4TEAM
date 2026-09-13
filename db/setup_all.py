#!/usr/bin/env python3
"""DB 셋업 한 번에 — 마이그레이션 + 기준 데이터 + 카탈로그 시드.

새 PostgreSQL(로컬 conda/Docker 또는 RDS)에 DATABASE_URL만 맞추고 이 파일 하나만
실행하면 팀원 누구나 동일한 상태(58개 테이블 + 기준 데이터 + 컴퓨터 부품 51개)를
갖게 된다. 각 단계는 멱등이라 여러 번 실행해도 안전하다.

    DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/setup_all.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}
STEPS = [
    ("스키마 마이그레이션", [sys.executable, "db/migrate.py", "up"]),
    ("기준 데이터 (도메인·단위)", [sys.executable, "db/seed.py"]),
    ("컴퓨터 부품 카탈로그", [sys.executable, "db/seed_catalog.py"]),
]


def main() -> int:
    for label, cmd in STEPS:
        print(f"\n=== {label} ===", flush=True)
        result = subprocess.run(cmd, cwd=ROOT, env=_ENV)
        if result.returncode != 0:
            print(f"\n실패: {label} (종료 코드 {result.returncode}) — 여기서 중단합니다.")
            return result.returncode
    print("\n전부 완료. 앱을 실행하세요:  uvicorn src.api:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
