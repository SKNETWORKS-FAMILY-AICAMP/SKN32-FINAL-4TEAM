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

    def delete_messages(self, conversation_id: UUID) -> None:
        """POST /reset 계약: 대화 이력을 실제로 비운다(소프트 삭제 컬럼 없음)."""
        self._exec("DELETE FROM identity.message WHERE conversation_id=%s", (conversation_id,))

    def guest_identity_known(self, guest_session_hash: str) -> bool:
        """이 해시로 만들어진 대화가 이미 존재하는지 — 위조/미지 쿠키와 구분한다."""
        row = self._one(
            "SELECT 1 FROM identity.conversation WHERE guest_session_hash=%s LIMIT 1",
            (guest_session_hash,),
        )
        return row is not None

    def merge_guest_into_user(self, guest_session_hash: str, user_id: UUID) -> int:
        """이 게스트 해시로 만들어진 대화(및 그 대화가 소유한 plan)를 user_id 로 옮기고
        게스트 해시를 지워 이후 같은 쿠키로는 다시 접근할 수 없게 만든다.

        conversation.user_id/guest_session_hash 가 실제 소유권 판단 기준이다
        (`session_service.load_owned_draft`, `list_service`). 이 한 UPDATE 로
        전환+무효화가 원자적으로 끝난다(같은 트랜잭션 안에서 호출돼야 한다).
        반환값은 옮겨진 대화 수(0 이면 위조/미지 쿠키 — 아무것도 하지 않는다).
        """
        rows = self._all(
            "UPDATE identity.conversation SET user_id=%s, guest_session_hash=NULL "
            "WHERE guest_session_hash=%s RETURNING id",
            (user_id, guest_session_hash),
        )
        if rows:
            self._exec(
                "UPDATE planning.plan SET owner_user_id=%s, updated_at=now() "
                "WHERE owner_user_id IS NULL AND conversation_id = ANY(%s)",
                (user_id, [r["id"] for r in rows]),
            )
        return len(rows)


_USER_COLUMNS = (
    "id, email_normalized, auth_subject, display_name, status, created_at, updated_at, "
    "password_hash, password_updated_at, failed_login_count, locked_until, last_login_at, "
    "terms_version, terms_agreed_at, privacy_agreed_at, marketing_agreed_at, deleted_at, "
    "email_verified_at, auth_version"
)


class UserRepo(Repo):
    def get_by_email(self, email_normalized: str) -> dict | None:
        return self._one(
            f"SELECT {_USER_COLUMNS} FROM identity.app_user WHERE email_normalized=%s",
            (email_normalized,),
        )

    def get_by_id(self, user_id: UUID) -> dict | None:
        return self._one(
            f"SELECT {_USER_COLUMNS} FROM identity.app_user WHERE id=%s",
            (user_id,),
        )

    def email_taken(self, email_normalized: str, *, exclude_user_id: UUID | None = None) -> bool:
        row = self._one(
            "SELECT 1 FROM identity.app_user WHERE email_normalized=%s AND id IS DISTINCT FROM %s",
            (email_normalized, exclude_user_id),
        )
        return row is not None

    def create(
        self, *, user_id: UUID, email_normalized: str, display_name: str, password_hash: str,
        terms_version: str, marketing_agreed: bool,
    ) -> dict:
        """UUID/auth_subject=local:<uuid> 로 활성 계정 1행을 만든다 (P6 RULES #2).

        고유성 위반(동시 가입 경쟁)은 여기서 잡지 않는다 — 호출자가 트랜잭션 안에서
        psycopg UniqueViolation 을 잡아 email_taken(409) 로 변환한다."""
        auth_subject = f"local:{user_id}"
        return self._one(
            f"""INSERT INTO identity.app_user
                (id, email_normalized, auth_subject, display_name, status,
                 password_hash, password_updated_at, terms_version, terms_agreed_at,
                 privacy_agreed_at, marketing_agreed_at)
                VALUES (%s, %s, %s, %s, 'active', %s, now(), %s, now(), now(), {"now()" if marketing_agreed else "NULL"})
                RETURNING {_USER_COLUMNS}""",
            (user_id, email_normalized, auth_subject, display_name, password_hash, terms_version),
        )

    def increment_failed_login(self, user_id: UUID) -> int:
        """실패 카운트를 원자적으로 1 올린다. 같은 행에 대한 동시 UPDATE 는 Postgres 행
        잠금으로 직렬화되어 동시 실패가 유실되지 않는다(AU03)."""
        row = self._one(
            "UPDATE identity.app_user SET failed_login_count = failed_login_count + 1 "
            "WHERE id=%s RETURNING failed_login_count",
            (user_id,),
        )
        return row["failed_login_count"]

    def lock_and_reset_count(self, user_id: UUID, *, locked_until) -> None:
        """5번째 실패: 잠그고 카운트를 0으로 되돌려 잠금 해제 후 다시 5회부터 센다."""
        self._exec(
            "UPDATE identity.app_user SET locked_until=%s, failed_login_count=0 WHERE id=%s",
            (locked_until, user_id),
        )

    def record_login_success(self, user_id: UUID, *, rehashed_password: str | None) -> None:
        if rehashed_password is not None:
            self._exec(
                "UPDATE identity.app_user SET failed_login_count=0, locked_until=NULL, "
                "last_login_at=now(), password_hash=%s, password_updated_at=now() WHERE id=%s",
                (rehashed_password, user_id),
            )
        else:
            self._exec(
                "UPDATE identity.app_user SET failed_login_count=0, locked_until=NULL, "
                "last_login_at=now() WHERE id=%s",
                (user_id,),
            )

    def update_password(self, user_id: UUID, password_hash: str) -> int:
        """비밀번호 교체 + auth_version 증가(발급 세대 전진) → 반환값이 새 세대."""
        row = self._one(
            "UPDATE identity.app_user SET password_hash=%s, password_updated_at=now(), "
            "auth_version=auth_version+1 WHERE id=%s RETURNING auth_version",
            (password_hash, user_id),
        )
        return row["auth_version"]

    def update_profile(
        self, user_id: UUID, *, display_name: str | None, email_normalized: str | None,
        marketing_agreed: bool | None,
    ) -> dict:
        sets, params = [], []
        if display_name is not None:
            sets.append("display_name=%s")
            params.append(display_name)
        if email_normalized is not None:
            sets.append("email_normalized=%s")
            sets.append("email_verified_at=NULL")
            params.append(email_normalized)
        if marketing_agreed is not None:
            sets.append("marketing_agreed_at=" + ("now()" if marketing_agreed else "NULL"))
        if not sets:
            return self.get_by_id(user_id)
        params.append(user_id)
        return self._one(
            f"UPDATE identity.app_user SET {', '.join(sets)} WHERE id=%s RETURNING {_USER_COLUMNS}",
            tuple(params),
        )

    def withdraw(self, user_id: UUID, *, anonymized_email: str, anonymized_name: str) -> int:
        """탈퇴: 상태/시각을 기록하고 비밀번호·동의·마케팅을 지운다. 이력 참조(FK RESTRICT
        걸린 plan/conversation 등)는 남긴다 — CONTRACTS "연쇄 삭제 금지". auth_version 을
        올려 남아 있던 토큰을 즉시 무효화한다."""
        row = self._one(
            """UPDATE identity.app_user SET
                 status='deleted', deleted_at=now(),
                 email_normalized=%s, display_name=%s,
                 password_hash=NULL, failed_login_count=0, locked_until=NULL,
                 terms_version=NULL, terms_agreed_at=NULL, privacy_agreed_at=NULL,
                 marketing_agreed_at=NULL, email_verified_at=NULL,
                 auth_version=auth_version+1
               WHERE id=%s RETURNING auth_version""",
            (anonymized_email, anonymized_name, user_id),
        )
        return row["auth_version"]
