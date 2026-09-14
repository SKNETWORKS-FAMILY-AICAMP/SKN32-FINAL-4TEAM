"""결과 화면 상호작용 통합 테스트 — 담기/빼기·수량·구매시점, 후보 교체, 결과 대화.

tests/test_list_service.py와 같은 전제(로컬 PostgreSQL, db/setup_all.py로 카탈로그 seed).
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.errors import NotFound, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service, session_service


class _Ctx:
    def __init__(self, connection):
        self.conn = connection

    def build_recommended_list(self, *, locale: str = "ko-KR") -> tuple[str, dict]:
        created = session_service.create_session(self.conn, Principal(user_id=None, browser_token=None))
        principal = Principal(user_id=None, browser_token=created["browser_token"])
        list_id = created["list_id"]
        list_uuid = uuid.UUID(list_id)
        session_service.choose_category(self.conn, list_uuid, "computer", "build", principal)
        for field, value in (("purpose", "game"), ("budget_max", 1500000), ("priority", "value")):
            session_service.patch_slot(self.conn, list_uuid, field, value, principal)
        revision_id = PlanRepo(self.conn).get_current_revision(list_uuid)["id"]
        accepted = recommendation_service.start_recommendation(
            self.conn,
            revision_id,
            strategy="default",
            locale=locale,
        )
        recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
        return revision_id, principal


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
    try:
        yield _Ctx(connection)
    finally:
        connection.close()


def test_result_preserves_generation_language(ctx):
    revision_id, _ = ctx.build_recommended_list(locale="en-US")

    result = recommendation_service.get_stored_result(ctx.conn, revision_id)

    assert result is not None
    assert result["content_language"] == "en-US"


def test_patch_item_deselect_and_qty(ctx):
    revision_id, _ = ctx.build_recommended_list()
    result = recommendation_service.get_stored_result(ctx.conn, revision_id)
    item = result["items"][0]
    item_id = uuid.UUID(item["item_id"])

    updated = recommendation_service.patch_item(
        ctx.conn, revision_id, item_id, selected=False, qty=2, timing="soon",
    )
    patched = next(i for i in updated["items"] if i["item_id"] == item["item_id"])
    assert patched["selected"] is False and patched["qty"] == 2 and patched["timing"] == "soon"
    # 선택 해제된 품목은 합계에서 빠진다.
    assert updated["totals"]["selected_price"] < result["totals"]["selected_price"]


def test_patch_item_rejects_unknown_item(ctx):
    revision_id, _ = ctx.build_recommended_list()
    with pytest.raises(NotFound):
        recommendation_service.patch_item(
            ctx.conn, revision_id, uuid.uuid4(), selected=True, qty=None, timing=None,
        )


def test_alternatives_and_swap_keep_item_id_stable(ctx):
    revision_id, _ = ctx.build_recommended_list()
    result = recommendation_service.get_stored_result(ctx.conn, revision_id)
    item = next(i for i in result["items"] if i["alternatives_count"] > 0)
    item_id = uuid.UUID(item["item_id"])

    alts = recommendation_service.list_alternatives(ctx.conn, revision_id, item_id)
    assert alts["items"]
    target = alts["items"][0]
    assert target["candidate_id"] != item["product"]["variant_id"]

    swapped = recommendation_service.swap_item(ctx.conn, revision_id, item_id, uuid.UUID(target["candidate_id"]))
    swapped_item = next(i for i in swapped["items"] if i["item_id"] == item["item_id"])
    assert swapped_item["item_id"] == item["item_id"]  # 계약: item_id 고정
    assert swapped_item["product"]["variant_id"] == target["candidate_id"]
    assert swapped_item["price"] == target["price"]


def test_swap_rejects_candidate_from_another_slot(ctx):
    revision_id, _ = ctx.build_recommended_list()
    result = recommendation_service.get_stored_result(ctx.conn, revision_id)
    items = result["items"]
    item_a, item_b = items[0], items[1]
    with pytest.raises(NotFound):
        recommendation_service.swap_item(
            ctx.conn, revision_id, uuid.UUID(item_a["item_id"]),
            uuid.UUID(item_b["product"]["variant_id"]),
        )


def test_result_message_swaps_for_cheaper(ctx):
    revision_id, _ = ctx.build_recommended_list()
    before = recommendation_service.get_stored_result(ctx.conn, revision_id)
    gpu_before = next(i for i in before["items"] if i["slot"] == "GPU")

    out = recommendation_service.handle_result_message(ctx.conn, revision_id, "그래픽카드를 더 저렴한 걸로 바꿔줘")
    gpu_after = next(i for i in out["result"]["items"] if i["slot"] == "GPU")
    assert gpu_after["item_id"] == gpu_before["item_id"]
    assert gpu_after["price"] <= gpu_before["price"]
    assert "그래픽카드" not in out["reply"] or "GPU" not in out["reply"]  # 자리표시자 문구 아님 (실제 응답 문장)


def test_result_message_unrecognized_text_leaves_result_unchanged(ctx):
    revision_id, _ = ctx.build_recommended_list()
    before = recommendation_service.get_stored_result(ctx.conn, revision_id)
    out = recommendation_service.handle_result_message(ctx.conn, revision_id, "안녕하세요")
    assert out["result"]["items"] == before["items"]
    assert "이해하지 못" in out["reply"]


def test_spec_file_upload_extracts_current_specs(ctx):
    created = session_service.create_session(ctx.conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(ctx.conn, list_uuid, "computer", "upgrade", principal)

    state = session_service.attach_spec_file(
        ctx.conn, list_uuid, "my-pc.txt", "CPU: i5-13600K\nGPU: RTX 3060\nRAM: 32GB\n", principal,
    )
    fields = {f["key"]: f["value"] for f in state["fields"]}
    assert fields["current_specs"] == {"CPU": "i5-13600K", "GPU": "RTX 3060", "RAM": "32GB"}
    assert fields["spec_file_name"] == "my-pc.txt"


def test_spec_file_rejects_bad_extension(ctx):
    created = session_service.create_session(ctx.conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(ctx.conn, list_uuid, "computer", "upgrade", principal)

    with pytest.raises(ValidationFailed) as exc:
        session_service.attach_spec_file(ctx.conn, list_uuid, "virus.exe", "hello", principal)
    assert exc.value.code == "unsupported_file"
