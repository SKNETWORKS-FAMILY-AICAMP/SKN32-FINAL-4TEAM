"""리스트(계획) 서비스 — 사이드바 목록 · S5-a 확정 · S5-b 리포트 · 가격 알림 (§D-4-3).

확정 = plan_revision draft → confirmed (이름·구매예정일·목표가·메모). 비로그인은 로그인 요구.
확정 시점에 선택된 후보를 planning.purchase_line에 얼려서 남긴다 — 이후 추천 결과가 어떻게
바뀌어도(현재는 확정된 revision에 재추천을 막아 그럴 일이 없지만) 리포트는 확정 순간 그대로
보여준다. price_watch 생성은 확정 트랜잭션 이후, 확정된 target_amount를 기본값으로 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.auth.deps import Principal
from src.errors import Conflict, NotFound, ValidationFailed
from src.repo.engine_repo import EngineRepo
from src.repo.notification_repo import NotificationRepo
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import UserRepo
from src.services import auth_service, feedback_service, recommendation_service
from src.services.session_service import _owned, _token_hash

_DEFAULT_NAME_BY_CATEGORY = {"computer": "컴퓨터 장바구니", "baby": "유아용품 장바구니"}
_PLACEHOLDER_NAMES = {"새 추천", ""}
_PRICE_WATCH_WINDOW_DAYS = 90


def _display_name(name: str, category: str | None) -> str:
    if name not in _PLACEHOLDER_NAMES:
        return name
    return _DEFAULT_NAME_BY_CATEGORY.get(category or "", name)


def _stage(row: dict) -> str:
    if row["state"] == "confirmed":
        return "report"
    if row["has_result"]:
        return "results"
    if row["has_category"]:
        return "conditions"
    return "category"


def _require_login(conn, principal: Principal) -> UUID:
    """단순 user_id 유무만이 아니라 계정이 여전히 active인지까지 확인한다(§A-3).

    JWT 자체는 유효 기간 안이어도 그 사이 탈퇴·정지된 계정일 수 있어서, principal.user_id가
    채워져 있다는 사실만으로는 로그인 요구 엔드포인트(확정·리포트·알림)를 통과시킬 수 없다.
    """
    return auth_service.require_active_user(conn, principal)["id"]


def _price_watch_out(watch: dict | None, fallback_target_amount) -> dict:
    if watch is None:
        return {
            "enabled": False, "target_amount": fallback_target_amount,
            "status": "waiting", "latest_total": None, "observed_at": None,
        }
    target = int(watch["target_amount"]) if watch["target_amount"] is not None else fallback_target_amount
    if watch["state"] != "active":
        return {"enabled": False, "target_amount": target, "status": "waiting", "latest_total": None, "observed_at": None}
    status = {"unknown": "waiting", "above": "tracking", "reached": "reached"}.get(
        watch["last_condition_state"], "waiting"
    )
    return {"enabled": True, "target_amount": target, "status": status, "latest_total": None, "observed_at": None}


def list_conversations(conn, principal: Principal) -> list[dict]:
    """사이드바 "내 장바구니" — 로그인 사용자 또는 guest 쿠키 소유분(§D-4-3)."""
    guest_hash = _token_hash(principal.browser_token) if principal.browser_token else None
    rows = PlanRepo(conn).list_owned(user_id=principal.user_id, guest_session_hash=guest_hash)
    return [
        {
            "list_id": str(row["list_id"]),
            "name": _display_name(row["name"], row["category"]),
            "category": row["category"],
            "stage": _stage(row),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def rename(conn, list_id: UUID, principal: Principal, *, name: str) -> dict:
    prepo = PlanRepo(conn)
    _owned(prepo, list_id, principal)
    prepo.rename(list_id, name)
    row = prepo.get_summary(list_id)
    return {
        "list_id": str(row["list_id"]), "name": name, "category": row["category"],
        "stage": _stage(row), "updated_at": row["updated_at"],
    }


def delete(conn, list_id: UUID, principal: Principal) -> None:
    prepo = PlanRepo(conn)
    _owned(prepo, list_id, principal)
    prepo.soft_delete(list_id)


def _report_lang(prepo: PlanRepo, revision_id: UUID) -> str:
    from src.engine.lang import lang_of
    return lang_of({r["condition_key"]: r["value"].get("value") for r in prepo.load_full(revision_id)["conditions"]})


def confirm(conn, list_id: UUID, principal: Principal, *, name: str, planned_purchase_at: str | None,
            target_amount: int | None, memo: str, if_match: int | None = None) -> dict:
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    if revision["owner_user_id"] != user_id:
        raise NotFound("목록을 찾을 수 없습니다.")
    if revision["state"] == "confirmed":
        return get_report(conn, list_id, principal)
    if if_match is not None and if_match != revision["lock_version"]:
        raise Conflict("목록이 다른 곳에서 변경되었습니다.", code="stale_revision")

    stored = recommendation_service.get_stored_result(conn, revision["id"])
    if stored is None or stored["status"] != "done" or not stored["items"]:
        raise ValidationFailed("추천 결과가 아직 없습니다. 먼저 추천을 완료해 주세요.", code="no_items_selected")
    if stored["totals"]["over_budget"]:
        raise ValidationFailed("선택한 구성이 예산을 초과합니다.", code="over_budget")

    run = EngineRepo(conn).get_run(UUID(stored["run_id"]))
    full = prepo.load_full(revision["id"])
    current_values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    if (run or {}).get("input_snapshot", {}).get("values", {}) != current_values:
        raise Conflict("조건이 바뀌어 추천을 다시 받아야 합니다.", code="stale_recommendation")

    purchase_at = None
    if planned_purchase_at:
        try:
            purchase_at = datetime.fromisoformat(planned_purchase_at)
        except ValueError:
            raise ValidationFailed("구매 예정일 형식이 올바르지 않습니다.", field="planned_purchase_at") from None

    ok = prepo.confirm_revision(
        revision["id"], confirmed_total=stored["totals"]["selected_price"],
        planned_purchase_at=purchase_at, target_amount=target_amount, memo=memo,
    )
    if not ok:
        raise Conflict("이미 확정된 목록입니다.")
    prepo.rename(list_id, name)

    # stored["items"]가 이미 리뷰 배지를 계산해 뒀다 — 상품키로 다시 찾지 않고 item_id로 재사용해
    # 결과 화면과 확정 스냅샷의 리뷰 표시가 어긋나지 않게 한다.
    review_by_item_id = {item["item_id"]: item["review"] for item in stored["items"]}

    # 확정 성공(state가 draft→confirmed로 바뀐 요청)만 후보를 얼린다 — confirm_revision이
    # 이미 원자적 UPDATE라 동시 확정 요청 중 단 하나만 여기 도달한다.
    for row in EngineRepo(conn).get_candidates(UUID(stored["run_id"])):
        if not row["selected"]:
            continue
        if row["offer_id"] is None or row["offer_observation_id"] is None or row["price"] is None:
            continue  # 가격 관측이 없는 슬롯 — 구매 항목으로 얼릴 수 없다
        item_view = next((i for i in stored["items"] if i["item_id"] == str(row["id"])), None)
        snapshot = {
            "slot": row["slot"], "slot_label": (item_view or {}).get("slot_label") or row["slot_label"],  # 결과 화면과 같은 언어
            "qty": 1, "timing": "now",
            "review": review_by_item_id.get(str(row["id"])), "evidence_text": row["reason"] or "",
            "product": {
                "product_key": row["product_key"], "name": row["product_name"],
                "image_url": row["image_url"], "purchase_url": row["purchase_url"],
            },
        }
        prepo.add_purchase_line(
            revision["id"], row["offer_id"], row["offer_observation_id"], int(row["price"]), snapshot
        )

    # P8 FB03: draft→confirmed 전환에 성공한 요청만 여기 도달한다(위의 Conflict가 이미
    # 중복 확정을 막는다) — 실패한 확정 시도는 아무 것도 남기지 않는다.
    feedback_service.emit_confirmed(
        conn, plan_id=revision["plan_id"], revision_id=revision["id"],
        run_id=UUID(stored["run_id"]), version=revision["lock_version"], user_id=user_id,
    )
    return get_report(conn, list_id, principal)


def get_report(conn, list_id: UUID, principal: Principal) -> dict:
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    if revision["owner_user_id"] != user_id or revision["state"] != "confirmed":
        raise NotFound("확정된 목록을 찾을 수 없습니다.")
    lang = _report_lang(prepo, revision["id"])

    owner = UserRepo(conn).get(revision["owner_user_id"])
    items = []
    for line in prepo.list_purchase_lines(revision["id"]):
        snapshot = line["snapshot"] or {}
        items.append({
            "slot": snapshot.get("slot"), "slot_label": snapshot.get("slot_label"),
            "product": snapshot.get("product") or {},
            "price": int(line["line_amount"]), "qty": int(line["pack_count"]),
            "timing": snapshot.get("timing", "now"), "review": snapshot.get("review"),
            "evidence_text": snapshot.get("evidence_text", ""),
        })
    watch = NotificationRepo(conn).get_for_revision(revision["id"])

    # 조립 가이드 — 리포트를 열 때마다 그 자리에서 만든다(확정 시점에 미리 만들어 저장하지
    # 않는다 — 브라우저의 "리포트 인쇄/PDF"(window.print())가 이 섹션까지 그대로 PDF로
    # 담아주므로, 서버가 PDF를 따로 만들 필요가 없다는 게 이 기능의 핵심 결정이다).
    from src.agent.assembly_guide_agent import build_guide
    guide_items = [{"slot": it["slot"], "product": it["product"]} for it in items if it["product"]]
    care_guide = build_guide(guide_items, lang=lang)

    return {
        "list_id": str(list_id),
        # A confirmed report is a snapshot; later sidebar renames must not rewrite
        # the name shown on that historical purchase record.
        "name": _display_name(revision["name_snapshot"], revision["category"]),
        "category": revision["category"],
        "owner_display_name": owner["display_name"] if owner else "",
        "planned_purchase_at": revision["planned_purchase_at"].date().isoformat()
        if revision["planned_purchase_at"] else None,
        "target_amount": int(revision["target_amount"]) if revision["target_amount"] is not None else None,
        "memo": revision["memo"] or "",
        "total": int(revision["confirmed_total"]),
        "confirmed_at": revision["confirmed_at"].isoformat(),
        "items": items,
        "price_watch": _price_watch_out(
            watch, int(revision["target_amount"]) if revision["target_amount"] is not None else None
        ),
        "care_guide": care_guide,
        "data_notice": ("Products, prices and reviews are synthetic demo data." if lang == "en"
                        else "상품·가격·리뷰는 합성 데이터입니다."),
    }


def set_alert(conn, list_id: UUID, principal: Principal, *, enabled: bool, target_amount: int | None) -> dict:
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    if revision["owner_user_id"] != user_id or revision["state"] != "confirmed":
        raise NotFound("확정된 목록을 찾을 수 없습니다.")

    nrepo = NotificationRepo(conn)
    existing = nrepo.get_for_revision(revision["id"])
    confirmed_target = int(revision["target_amount"]) if revision["target_amount"] is not None else None

    if not enabled:
        if existing is not None and existing["state"] == "active":
            nrepo.pause(existing["id"])
            existing = nrepo.get_for_revision(revision["id"])
        return {"price_watch": _price_watch_out(existing, confirmed_target)}

    # target_amount 미지정 시 기존 watch에 이미 설정된 값 → 확정 스냅샷 목표가 순으로 fallback.
    amount = target_amount
    if amount is None and existing is not None:
        amount = existing["target_amount"]
    if amount is None:
        amount = revision["target_amount"]
    if amount is None:
        raise ValidationFailed("목표 금액을 입력해 주세요.", field="target_amount")
    ends_at = datetime.now(timezone.utc) + timedelta(days=_PRICE_WATCH_WINDOW_DAYS)
    watch = nrepo.upsert_active(revision["id"], target_amount=amount, ends_at=ends_at)
    return {"price_watch": _price_watch_out(watch, confirmed_target)}
