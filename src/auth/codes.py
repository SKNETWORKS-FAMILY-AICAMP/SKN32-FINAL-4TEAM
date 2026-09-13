"""이메일 6자리 코드 발급·검증.

코드는 해시로 저장. 유효 10분, 검증 5회 초과 시 무효, 재요청 rate limit(이메일당 60초/시간당 5회).
이메일 존재 여부를 응답으로 노출하지 않음 (요청은 항상 성공 응답).

명세서 v4 의 identity 스키마에는 auth_codes 테이블이 없다 → 별도 저장소가 필요하다.
결정 필요: (a) 마이그레이션에 identity.auth_code 추가  (b) Redis/DB TTL 스토어
"""
from __future__ import annotations


def request_code(email: str) -> None:
    """코드 생성 → 해시 저장 → 메일 발송 큐. rate limit 초과 시 조용히 무시."""
    raise NotImplementedError


def verify_code(email: str, code: str) -> bool:
    """해시 비교 · 만료 · 시도횟수 확인. 성공 시 코드 소비(1회용)."""
    raise NotImplementedError
