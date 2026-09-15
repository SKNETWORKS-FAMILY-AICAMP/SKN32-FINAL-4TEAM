"""리스트 확정·리포트·가격 알림 통합 테스트 (docs/frontend_외부수정요청.md §D-4-3).

실제 로컬 PostgreSQL(DATABASE_URL, db/setup_all.py로 준비)이 필요하다. 컴퓨터 카탈로그가
seed되어 있어야 한다(db/setup_all.py가 seed_catalog.py까지 실행한다).

tests/test_auth.py와 같은 이유로 autocommit 연결을 쓴다(각 서비스 호출이 실제 요청처럼
독립 커밋되어야 password_updated_at/now() 등이 제대로 갈린다). 계정은 탈퇴(익명화)로
정리하지만, 계획·대화·추천 실행 행은 FK RESTRICT 사슬이 길어 물리 삭제하지 않고
로컬 개발 DB에 남겨둔다 — 브라우저로 직접 검증할 때도 이미 그렇게 남기고 있다.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.errors import NotFound, Unauthorized, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import UserRepo
from src.services import auth_service, list_service, recommendation_service, session_service


class _Ctx:
    def __init__(self, connection):
        self.conn = connection
        self.created_ids: list[str] = []

    def signup(self, email: str, password: str = "abc12345") -> Principal:
        user, token = auth_service.signup(
            self.conn, Principal(user_id=None, browser_token=None),
            email=email, password=password, display_name="리스트테스트",
            terms_agreed=True, privacy_agreed=True, marketing_agreed=False,
        )
        self.created_ids.append(user["id"])
        payload_b64 = token.split(".")[1]
        import base64
        import json
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        iat = json.loads(base64.urlsafe_b64decode(padded))["iat"]
        return Principal(user_id=uuid.UUID(user["id"]), browser_token=None, session_iat=iat)

    def build_recommended_list(self, principal: Principal) -> str:
        """카테고리 선택 → 조건 직접 채움 → 추천 실행까지 마친 list_id."""
        list_id = session_service.create_session(self.conn, principal)["list_id"]
        list_uuid = uuid.UUID(list_id)
        session_service.choose_category(self.conn, list_uuid, "computer", "build", principal)
        for field, value in (("purpose", "game"), ("budget_max", 1500000), ("priority", "value")):
            session_service.patch_slot(self.conn, list_uuid, field, value, principal)
        revision_id = PlanRepo(self.conn).get_current_revision(list_uuid)["id"]
        accepted = recommendation_service.start_recommendation(self.conn, revision_id, strategy="default")
        recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
        return list_id


@pytest.fixture
def ctx():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    has_domain_version = connection.execute(
        "SELECT to_regclass('config.domain_version') IS NOT NULL"
    ).fetchone()[0]
    if not has_domain_version:
        connection.close()
        pytest.skip("develop DB 스키마가 아닙니다 — db/setup_all.py로 준비하세요.")
    context = _Ctx(connection)
    try:
        yield context
    finally:
        if context.created_ids:
            for user_id in context.created_ids:
                try:
                    UserRepo(connection).withdraw(uuid.UUID(user_id))
                except Exception:  # noqa: BLE001 — 정리 실패는 테스트 결과에 영향 주지 않음
                    pass
        connection.close()


def _unique_email() -> str:
    return f"list-test-{uuid.uuid4().hex}@example.com"


def test_confirm_requires_login(ctx):
    guest = Principal(user_id=None, browser_token=None)
    principal = ctx.signup(_unique_email())
    list_id = ctx.build_recommended_list(principal)

    with pytest.raises(Unauthorized):
        list_service.confirm(
            ctx.conn, uuid.UUID(list_id), guest,
            name="x", planned_purchase_at=None, target_amount=1000, memo="",
        )


def test_confirm_rejects_withdrawn_account_even_with_valid_token(ctx):
    """탈퇴 계정의 아직 안 만료된 토큰으로는 확정할 수 없다(발견된 버그의 회귀 테스트)."""
    principal = ctx.signup(_unique_email())
    list_id = ctx.build_recommended_list(principal)
    auth_service.withdraw(ctx.conn, principal, password="abc12345")

    with pytest.raises(Unauthorized):
        list_service.confirm(
            ctx.conn, uuid.UUID(list_id), principal,
            name="x", planned_purchase_at=None, target_amount=1000, memo="",
        )


def test_confirm_before_recommend_is_rejected(ctx):
    principal = ctx.signup(_unique_email())
    list_id = session_service.create_session(ctx.conn, principal)["list_id"]

    with pytest.raises(ValidationFailed) as exc:
        list_service.confirm(
            ctx.conn, uuid.UUID(list_id), principal,
            name="x", planned_purchase_at=None, target_amount=1000, memo="",
        )
    assert exc.value.code == "no_items_selected"


def test_confirm_then_report_round_trip(ctx):
    principal = ctx.signup(_unique_email())
    list_id = ctx.build_recommended_list(principal)

    report = list_service.confirm(
        ctx.conn, uuid.UUID(list_id), principal,
        name="나의 첫 컴퓨터", planned_purchase_at="2026-10-01", target_amount=1400000, memo="메모",
    )
    assert report["total"] > 0
    assert report["items"]
    assert report["price_watch"] == {
        "enabled": False, "target_amount": 1400000, "status": "waiting",
        "latest_total": None, "observed_at": None,
    }

    # 재확정 시도는 거부되지 않고 멱등하게 같은 리포트를 반환한다(이중 클릭 등 재시도 대비).
    again = list_service.confirm(
        ctx.conn, uuid.UUID(list_id), principal,
        name="나의 첫 컴퓨터", planned_purchase_at=None, target_amount=1400000, memo="",
    )
    assert again["total"] == report["total"]

    fetched = list_service.get_report(ctx.conn, uuid.UUID(list_id), principal)
    assert fetched["total"] == report["total"]

    summaries = list_service.list_conversations(ctx.conn, principal)
    assert any(item["list_id"] == list_id and item["stage"] == "report" for item in summaries)


def test_alert_reenable_without_amount_keeps_last_value(ctx):
    principal = ctx.signup(_unique_email())
    list_id = ctx.build_recommended_list(principal)
    list_service.confirm(
        ctx.conn, uuid.UUID(list_id), principal,
        name="x", planned_purchase_at=None, target_amount=1400000, memo="",
    )

    on = list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=1450000)
    assert on["price_watch"]["target_amount"] == 1450000

    on_again = list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=None)
    assert on_again["price_watch"]["target_amount"] == 1450000  # 확정 스냅샷(1400000)으로 되돌아가면 버그

    off = list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=False, target_amount=None)
    assert off["price_watch"] == {
        "enabled": False, "target_amount": 1450000, "status": "waiting",
        "latest_total": None, "observed_at": None,
    }


def test_delete_excludes_from_list_and_report(ctx):
    principal = ctx.signup(_unique_email())
    list_id = ctx.build_recommended_list(principal)
    list_service.confirm(
        ctx.conn, uuid.UUID(list_id), principal,
        name="x", planned_purchase_at=None, target_amount=1000000, memo="",
    )

    list_service.delete(ctx.conn, uuid.UUID(list_id), principal)

    with pytest.raises(NotFound):
        list_service.get_report(ctx.conn, uuid.UUID(list_id), principal)
    assert not any(item["list_id"] == list_id for item in list_service.list_conversations(ctx.conn, principal))
