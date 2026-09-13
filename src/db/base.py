"""repo 공통 베이스.

각 repo 는 스키마 하나(또는 애그리게잇 하나)를 담당하고, 커넥션을 주입받는다.
    with get_conn() as conn:
        PlanRepo(conn).create_plan(...)
"""

from __future__ import annotations

from typing import Any, Sequence


class Repo:
    def __init__(self, conn: Any):
        self.conn = conn

    # 편의 헬퍼 (실제 구현 시 psycopg cursor 사용)
    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        """단일 행 dict 또는 None."""
        from psycopg.rows import dict_row

        with self.conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        """행 리스트."""
        from psycopg.rows import dict_row

        with self.conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> None:
        """반환 없는 실행."""
        self.conn.execute(sql, params)
