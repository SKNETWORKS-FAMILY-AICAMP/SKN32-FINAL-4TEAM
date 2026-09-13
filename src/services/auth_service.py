"""인증 서비스 — 코드 요청 · 검증 · JWT · browser_token 병합."""
from __future__ import annotations

from uuid import UUID

from src.auth import codes, jwt
from src.errors import Unauthorized


def request_login_code(email: str) -> None:
    """항상 성공 응답 (이메일 존재 노출 방지)."""
    codes.request_code(email)


def verify_and_issue(email: str, code: str, browser_token: str | None) -> str:
    """코드 검증 → 계정 upsert → JWT 발급 → 비로그인 대화·리스트를 user 로 병합."""
    if not codes.verify_code(email, code):
        raise Unauthorized("코드가 올바르지 않거나 만료되었습니다")
    # TODO: UserRepo.upsert_by_email → user_id
    # TODO: ConversationRepo.attach_user(browser_token 소유분) + guest 토큰 폐기
    # return jwt.issue(user_id, email)
    raise NotImplementedError
