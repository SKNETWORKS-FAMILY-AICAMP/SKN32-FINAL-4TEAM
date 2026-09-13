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

    def attach_user(self, guest_session_hash: str, user_id: UUID) -> None:
        """게스트 소유 대화·리스트를 로그인 계정으로 귀속(§A-3 5번). guest 토큰은 폐기."""
        self._exec(
            "UPDATE identity.conversation SET user_id=%s, guest_session_hash=NULL "
            "WHERE guest_session_hash=%s AND user_id IS NULL",
            (user_id, guest_session_hash),
        )
        self._exec(
            "UPDATE planning.plan SET owner_user_id=%s WHERE owner_user_id IS NULL "
            "AND conversation_id IN (SELECT id FROM identity.conversation WHERE user_id=%s)",
            (user_id, user_id),
        )


class UserRepo(Repo):
    """identity.app_user — password_hash는 get_for_login()에서만 돌려준다(§A-1)."""

    _PUBLIC_COLUMNS = (
        "id, email_normalized AS email, display_name, "
        "(marketing_agreed_at IS NOT NULL) AS marketing_agreed, created_at, "
        "status, password_updated_at"
    )

    def is_email_taken(self, email_normalized: str) -> bool:
        row = self._one(
            "SELECT 1 FROM identity.app_user WHERE email_normalized=%s AND status != 'deleted'",
            (email_normalized,),
        )
        return row is not None

    def create_local_user(self, *, email_normalized: str, password_hash: str, display_name: str,
                           terms_version: str, terms_agreed_at, privacy_agreed_at,
                           marketing_agreed_at) -> dict:
        user_id = uuid.uuid4()
        row = self._one(
            "INSERT INTO identity.app_user "
            "(id, email_normalized, auth_subject, display_name, password_hash, password_updated_at, "
            " terms_version, terms_agreed_at, privacy_agreed_at, marketing_agreed_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), %s, %s, %s, %s) "
            f"RETURNING {self._PUBLIC_COLUMNS}",
            (user_id, email_normalized, f"local:{user_id}", display_name, password_hash,
             terms_version, terms_agreed_at, privacy_agreed_at, marketing_agreed_at),
        )
        return row

    def get_for_login(self, email_normalized: str) -> dict | None:
        """password_hash 포함 — 로그인 검증 전용. 다른 조회에는 쓰지 않는다."""
        return self._one(
            "SELECT id, email_normalized AS email, display_name, password_hash, status, "
            "failed_login_count, locked_until, password_updated_at "
            "FROM identity.app_user WHERE email_normalized=%s",
            (email_normalized,),
        )

    def get(self, user_id: UUID) -> dict | None:
        return self._one(
            f"SELECT {self._PUBLIC_COLUMNS} FROM identity.app_user WHERE id=%s", (user_id,)
        )

    def record_login_success(self, user_id: UUID) -> None:
        self._exec(
            "UPDATE identity.app_user SET failed_login_count=0, locked_until=NULL, "
            "last_login_at=now() WHERE id=%s",
            (user_id,),
        )

    def record_login_failure(self, user_id: UUID, *, max_failures: int, lock_minutes: int) -> None:
        """max_failures번째 실패 시 잠그고 카운트를 0으로 되돌린다(§A-3 로그인 3번)."""
        self._exec(
            "UPDATE identity.app_user SET "
            "failed_login_count = CASE WHEN failed_login_count + 1 >= %s THEN 0 ELSE failed_login_count + 1 END, "
            "locked_until = CASE WHEN failed_login_count + 1 >= %s THEN now() + (%s || ' minutes')::interval "
            "ELSE locked_until END "
            "WHERE id=%s",
            (max_failures, max_failures, lock_minutes, user_id),
        )

    def update_profile(self, user_id: UUID, *, display_name: str | None = None,
                        email_normalized: str | None = None,
                        marketing_agreed: bool | None = None) -> dict:
        sets: list[str] = []
        params: list[object] = []
        if display_name is not None:
            sets.append("display_name=%s")
            params.append(display_name)
        if email_normalized is not None:
            sets.append("email_normalized=%s")
            sets.append("email_verified_at=NULL")
            params.append(email_normalized)
        if marketing_agreed is not None:
            sets.append("marketing_agreed_at = CASE WHEN %s THEN now() ELSE NULL END")
            params.append(marketing_agreed)
        if not sets:
            return self.get(user_id)
        params.append(user_id)
        return self._one(
            f"UPDATE identity.app_user SET {', '.join(sets)} WHERE id=%s "
            f"RETURNING {self._PUBLIC_COLUMNS}",
            params,
        )

    def update_password(self, user_id: UUID, password_hash: str) -> None:
        self._exec(
            "UPDATE identity.app_user SET password_hash=%s, password_updated_at=now() WHERE id=%s",
            (password_hash, user_id),
        )

    def withdraw(self, user_id: UUID) -> None:
        """소프트 삭제 + 개인정보 제거(§A-3 회원 탈퇴)."""
        self._exec(
            "UPDATE identity.app_user SET "
            "status='deleted', deleted_at=now(), "
            "email_normalized = 'deleted+' || id::text || '@deleted.invalid', "
            "display_name='탈퇴한 사용자', password_hash=NULL, password_updated_at=now(), "
            "email_verified_at=NULL, marketing_agreed_at=NULL, "
            "failed_login_count=0, locked_until=NULL, "
            "ui_settings='{}'::jsonb, notification_settings='{}'::jsonb "
            "WHERE id=%s AND status='active'",
            (user_id,),
        )
