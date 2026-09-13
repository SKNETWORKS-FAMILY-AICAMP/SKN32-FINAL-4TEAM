"""단일 프로세스 인메모리 rate limiter.

배포 제약: 이 카운터는 프로세스 로컬 메모리에만 있다 — 여러 워커/인스턴스로 수평
확장하면 인스턴스별로 따로 세므로 실제 허용량이 설정값의 배수가 될 수 있다. 로그인
잠금(계정 상태 컬럼 기반, `UserRepo.increment_failed_login`)과 달리 이 한도는 진짜
분산 한도가 아니다 — 초기 단일 인스턴스 배포 전용이며, 공유 스토어(Redis 등)로
교체하기 전까지의 문서화된 제약이다.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def allow(key: str, *, limit: int, window_seconds: float) -> bool:
    """`key` 가 최근 `window_seconds` 안에 `limit` 회 미만 호출했으면 True 를 반환하고 기록한다."""
    now = time.monotonic()
    with _lock:
        hits = [t for t in _hits.get(key, ()) if now - t < window_seconds]
        if len(hits) >= limit:
            _hits[key] = hits
            return False
        hits.append(now)
        _hits[key] = hits
        return True


def reset_all() -> None:
    """테스트 전용: 누적된 카운터를 비운다."""
    with _lock:
        _hits.clear()
