"""DB 커넥션 (psycopg 풀).

get_conn() 은 트랜잭션 1개를 열고 with 블록 종료 시 commit/rollback 한다.
커넥션 풀(PgBouncer/RDS Proxy) 전제이므로 세션 상태에 의존하지 않는다 (SET LOCAL 만).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from src.config import DATABASE_URL

_pool = None  # psycopg_pool.ConnectionPool — 지연 초기화


def get_pool():
    """전역 커넥션 풀 반환 (최초 호출 시 생성)."""
    # TODO: 실제 로직 구현 필요
    #   from psycopg_pool import ConnectionPool
    #   global _pool
    #   if _pool is None:
    #       _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)
    #   return _pool
    raise NotImplementedError("DB 풀 미구현 (psycopg_pool)")


@contextmanager
def get_conn() -> Iterator["object"]:
    """트랜잭션 1개.  with get_conn() as conn: repo(conn).do(...)"""
    # TODO: 실제 로직 구현 필요
    #   with get_pool().connection() as conn:
    #       with conn.transaction():
    #           yield conn
    raise NotImplementedError("DB 커넥션 미구현")
