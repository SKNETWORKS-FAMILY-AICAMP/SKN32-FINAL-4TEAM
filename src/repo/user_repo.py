"""identity.* 저장소."""
from __future__ import annotations
import uuid
from uuid import UUID
from src.db.base import Repo

class ConversationRepo(Repo):
    def create(self, *, user_id: UUID | None, guest_session_hash: str | None) -> UUID:
        row = self._one("INSERT INTO identity.conversation (user_id, guest_session_hash) VALUES (%s, %s) RETURNING id", (user_id, guest_session_hash))
        return row["id"]

    def add_message(self, conversation_id: UUID, role: str, content: str) -> UUID:
        row = self._one(
            "INSERT INTO identity.message (conversation_id, role, content, client_message_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (conversation_id, role, content, str(uuid.uuid4())),
        )
        return row["id"]

    def messages(self, conversation_id: UUID) -> list[dict]:
        return self._all(
            "SELECT id, role, content, created_at FROM identity.message "
            "WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        )

class UserRepo(Repo):
    pass
