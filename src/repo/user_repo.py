"""identity.* 저장소 — app_user / user_preference / conversation / message."""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class UserRepo(Repo):
    def upsert_by_email(self, email_normalized: str, auth_subject: str, display_name: str) -> UUID:
        """이메일 6자리 코드 검증 통과 시 계정 생성/조회 → user_id."""
        raise NotImplementedError

    def get(self, user_id: UUID) -> dict | None:
        raise NotImplementedError

    def get_preference(self, user_id: UUID) -> dict:
        raise NotImplementedError

    def set_preference(self, user_id: UUID, ui_settings: dict, notification_settings: dict) -> None:
        raise NotImplementedError


class ConversationRepo(Repo):
    def create(self, *, user_id: UUID | None, guest_session_hash: str | None) -> UUID:
        raise NotImplementedError

    def attach_user(self, conversation_id: UUID, user_id: UUID) -> None:
        """비로그인 대화를 계정에 귀속 (guest 토큰 폐기는 서비스 계층)."""
        raise NotImplementedError

    def list_for_user(self, user_id: UUID, limit: int = 30) -> list[dict]:
        raise NotImplementedError

    def add_message(self, conversation_id: UUID, role: str, content: str, client_message_id: str) -> UUID:
        raise NotImplementedError
