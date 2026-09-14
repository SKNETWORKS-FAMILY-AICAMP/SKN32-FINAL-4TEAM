"""공유 append-only 이벤트 생산자 (CONTRACTS P5 EXECUTION ORDER 9, P7 재사용).

engine.feedback_event 는 이미 존재하는 테이블이다 (event_key UNIQUE 제약 — 0002_unique.sql).
그 제약을 그대로 idempotency key 로 쓴다: 같은 (run_id, item_id, lock_version, action)
조합은 두 번 이상 쌓이지 않는다 (ON CONFLICT DO NOTHING) — GET/폴링이 반복 호출돼도
recommendation_shown 이 중복되지 않는다 (CONTRACTS 9 "GET/poll must not duplicate").

event_type 은 DB CHECK 제약(recommendation_shown|item_replaced|item_removed|plan_confirmed)
을 따른다. action 은 event_key 조립에만 쓰는 논리적 이름(shown/replaced/removed/confirmed)이며
event_type 으로 매핑된다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

_ACTION_TO_EVENT_TYPE = {
    "shown": "recommendation_shown",
    "replaced": "item_replaced",
    "removed": "item_removed",
    "confirmed": "plan_confirmed",
}

# P8 IMPLEMENTATION7: "payload whitelist IDs/action/version/reason code; no body/
# email/token/private note." Keys must end in _id (identifiers), or be one of these
# scalar fields; values must be JSON scalars — never a nested dict/list, which is
# exactly how a body/email/token would otherwise be smuggled in through this "id".
_PAYLOAD_SCALAR_KEYS = {"action", "version", "reason_code", "source"}


def _validate_payload(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        allowed_key = key in _PAYLOAD_SCALAR_KEYS or key.endswith("_id")
        if not allowed_key:
            raise ValueError(f"feedback payload key not allowed: {key!r}")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"feedback payload value for {key!r} must be a scalar, got {type(value).__name__}")


def _event_key(*, run_id: UUID | str | None, item_id: UUID | str | None, version: int, action: str) -> str:
    """멱등성 키 — run/item/version(=plan_revision.lock_version)/action 에 결정적으로 묶는다."""
    return f"{run_id or 'norun'}:{item_id or 'noitem'}:{version}:{action}"


def emit(conn, *, plan_id: UUID, revision_id: UUID, run_id: UUID | str | None,
         item_id: UUID | str | None, version: int, action: str,
         user_id: UUID | None = None, payload: dict[str, Any] | None = None) -> bool:
    """이벤트 하나를 append-only 로 기록한다. 반환값 True = 새로 기록됨, False = 이미 있었음(중복 억제).

    P8 이 이 함수가 쓴 행을 그대로 읽는다 — event emission 을 P8 까지 미루지 않는다
    (CONTRACTS "P8 consumes and tests these events; do not postpone emission until P8").
    """
    if action not in _ACTION_TO_EVENT_TYPE:
        raise ValueError(f"unknown feedback action: {action}")
    _validate_payload(payload or {})
    event_type = _ACTION_TO_EVENT_TYPE[action]
    event_key = _event_key(run_id=run_id, item_id=item_id, version=version, action=action)
    row = conn.execute(
        """INSERT INTO engine.feedback_event
           (plan_id, revision_id, recommendation_run_id, user_id, event_type, event_key, payload, occurred_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (event_key) DO NOTHING
           RETURNING id""",
        (plan_id, revision_id, run_id, user_id, event_type, event_key,
         Jsonb(payload or {}), datetime.now(timezone.utc)),
    ).fetchone()
    return row is not None


def emit_shown(conn, *, plan_id: UUID, revision_id: UUID, run_id: UUID, version: int,
               user_id: UUID | None = None, payload: dict[str, Any] | None = None) -> bool:
    """추천 결과가 (처음으로) 사용자에게 보여졌음 — run 당 한 번만 기록된다."""
    return emit(conn, plan_id=plan_id, revision_id=revision_id, run_id=run_id, item_id=None,
               version=version, action="shown", user_id=user_id, payload=payload)


def emit_replaced(conn, *, plan_id: UUID, revision_id: UUID, run_id: UUID | None, item_id: UUID | str,
                  version: int, user_id: UUID | None = None, payload: dict[str, Any] | None = None) -> bool:
    return emit(conn, plan_id=plan_id, revision_id=revision_id, run_id=run_id, item_id=item_id,
               version=version, action="replaced", user_id=user_id, payload=payload)


def emit_removed(conn, *, plan_id: UUID, revision_id: UUID, run_id: UUID | None, item_id: UUID | str,
                 version: int, user_id: UUID | None = None, payload: dict[str, Any] | None = None) -> bool:
    return emit(conn, plan_id=plan_id, revision_id=revision_id, run_id=run_id, item_id=item_id,
               version=version, action="removed", user_id=user_id, payload=payload)


def emit_confirmed(conn, *, plan_id: UUID, revision_id: UUID, run_id: UUID | None, version: int,
                   user_id: UUID | None = None, payload: dict[str, Any] | None = None) -> bool:
    return emit(conn, plan_id=plan_id, revision_id=revision_id, run_id=run_id, item_id=None,
               version=version, action="confirmed", user_id=user_id, payload=payload)
