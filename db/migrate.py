#!/usr/bin/env python3
"""얇은 마이그레이션 러너 (Truefit).

db/migrations/*.sql 을 파일명 순서로 적용하고 _migrations.schema_migrations 에 기록한다.
로컬 컨테이너 PG 와 RDS/Aurora 에 동일하게 동작 (네트워크 DSN). forward-only.

사용:
    python db/migrate.py up            # 미적용 마이그레이션 전부 적용 (기본)
    python db/migrate.py status        # 적용 현황
    python db/migrate.py dry-run       # 무엇이 적용될지만 출력

DSN: 환경변수 DATABASE_URL (기본 postgresql://truefit:truefit@localhost:5432/truefit)
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIG_DIR = Path(__file__).resolve().parent / "migrations"
DSN = os.environ.get("DATABASE_URL", "postgresql://truefit:truefit@localhost:5432/truefit")


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _ensure_tracking(conn: psycopg.Connection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS _migrations")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations.schema_migrations (
          version     text PRIMARY KEY,
          checksum    text NOT NULL,
          applied_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def _applied(conn: psycopg.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT version, checksum FROM _migrations.schema_migrations"
    ).fetchall()
    return {v: c for v, c in rows}


def main() -> int:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "up").lower()
    if cmd not in ("up", "status", "dry-run"):
        print(__doc__)
        return 2

    files = sorted(MIG_DIR.glob("*.sql"))
    if not files:
        print(f"마이그레이션 파일 없음: {MIG_DIR}")
        return 1

    try:
        conn_cm = psycopg.connect(DSN, autocommit=False, connect_timeout=10)
    except psycopg.OperationalError as e:
        print(f"DB 연결 실패 ({DSN}): {str(e).strip()}")
        print("컨테이너를 띄우거나 DATABASE_URL 을 확인하세요:  docker compose up -d")
        return 1
    with conn_cm as conn:
        _ensure_tracking(conn)
        done = _applied(conn)

        if cmd == "status":
            print(f"DSN: {DSN}")
            for f in files:
                ver, cs = f.stem, _checksum(f.read_text(encoding="utf-8"))
                if ver in done:
                    mark = "OK " if done[ver] == cs else "CHECKSUM MISMATCH "
                else:
                    mark = "pending "
                print(f"  [{mark:<18}] {ver}")
            return 0

        pending = [f for f in files if f.stem not in done]
        for f in files:
            ver, cs = f.stem, _checksum(f.read_text(encoding="utf-8"))
            if ver in done and done[ver] != cs:
                print(f"경고: 이미 적용된 {ver} 의 체크섬이 변경됨 (마이그레이션은 forward-only)")

        if not pending:
            print("적용할 마이그레이션 없음.")
            return 0

        for f in pending:
            ver = f.stem
            sql = f.read_text(encoding="utf-8")
            if cmd == "dry-run":
                print(f"  적용 예정: {ver}")
                continue
            print(f"적용 중: {ver} ...")
            try:
                with conn.transaction():
                    conn.execute(sql)  # 파라미터 없음 → 다중 문장 허용 (simple protocol)
                    conn.execute(
                        "INSERT INTO _migrations.schema_migrations (version, checksum) VALUES (%s, %s)",
                        (ver, _checksum(sql)),
                    )
                print(f"  완료: {ver}")
            except Exception as e:  # noqa: BLE001
                print(f"  실패: {ver} — {e}")
                return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
