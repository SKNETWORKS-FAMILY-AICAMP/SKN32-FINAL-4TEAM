"""DB 커넥션 (psycopg 풀).

get_conn() 은 트랜잭션 1개를 열고 with 블록 종료 시 commit/rollback 한다.
커넥션 풀(PgBouncer/RDS Proxy) 전제이므로 세션 상태에 의존하지 않는다 (SET LOCAL 만).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL

_pool: ConnectionPool | None = None  # 지연 초기화


def get_pool() -> ConnectionPool:
    """전역 커넥션 풀 반환 (최초 호출 시 생성)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)
    return _pool


@contextmanager
def get_conn() -> Iterator["object"]:
    """트랜잭션 1개.  with get_conn() as conn: repo(conn).do(...)"""
    with get_pool().connection() as conn:
        with conn.transaction():
            yield conn


def close_pool() -> None:
    """앱 종료 시 풀을 닫는다 (FastAPI shutdown 이벤트에서 호출)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
