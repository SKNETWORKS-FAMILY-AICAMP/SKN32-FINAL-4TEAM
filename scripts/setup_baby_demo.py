#!/usr/bin/env python3
"""Full synthetic baby demo setup, one command (P3 execution doc phase 5 step 1).

    DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/<disposable> \\
      uv run python scripts/setup_baby_demo.py

migrate -> baseline seed -> synthetic catalog -> synthetic verification evidence,
in that order (each downstream step reads what the one before it wrote). Every
step is idempotent — safe to re-run against the same DB.

Never point this at a shared/production DATABASE_URL: it seeds the fully synthetic
demo catalog and marks every candidate is_synthetic=true, scope=synthetic_demo. It
does not touch, migrate, or read real product evidence.
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
    ("유아 합성 카탈로그", [sys.executable, "scripts/seed_baby_catalog.py"]),
    ("유아 합성 검증 증빙 (P3)", [sys.executable, "scripts/seed_baby_synthetic_evidence.py"]),
]


def main() -> int:
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is required — point it at a disposable database, never a shared one.", file=sys.stderr)
        return 2
    for label, cmd in STEPS:
        print(f"\n=== {label} ===", flush=True)
        result = subprocess.run(cmd, cwd=ROOT, env=_ENV)
        if result.returncode != 0:
            print(f"\n실패: {label} (종료 코드 {result.returncode}) — 여기서 중단합니다.")
            return result.returncode
    print(
        "\n전부 완료. 앱을 실행하세요:  uvicorn src.api:app --reload\n"
        "이 DB의 유아 추천 결과는 synthetic_demo 범위입니다 — production_readiness는 항상 blocked입니다."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
