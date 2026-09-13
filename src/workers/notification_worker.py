"""이메일 발송 워커.

notification.notification_event(delivery_state='pending') 를 잡아 메일 발송 →
sent/failed 갱신. dedupe_key 로 중복 방지. 데모는 SES 샌드박스 + 콘솔 로그.
"""
from __future__ import annotations


def run() -> None:
    raise NotImplementedError
