"""세션 생성과 조건 대화 서비스 (계약: docs/frontend_외부수정요청.md §D-4-1)."""
from __future__ import annotations
import hashlib, secrets
from uuid import UUID
from src.auth.deps import Principal
from src.categories import load_category
from src.engine import slot_rules
from src.errors import Conflict, NotFound, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import ConversationRepo


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _category(name: str) -> dict:
    try:
        return load_category(name)
    except FileNotFoundError:
        raise ValidationFailed("지원하지 않는 카테고리입니다.", field="category") from None


def _owned(repo: PlanRepo, list_id: UUID, principal: Principal) -> dict:
    revision = repo.get_current_revision(list_id)
    if revision is None:
        raise NotFound("목록을 찾을 수 없습니다.")
    user_ok = principal.user_id is not None and revision["user_id"] == principal.user_id
    guest_ok = principal.browser_token is not None and revision["guest_session_hash"] == _token_hash(principal.browser_token)
    if not (user_ok or guest_ok):
        raise NotFound("목록을 찾을 수 없습니다.")
    return revision


def create_session(conn, principal: Principal) -> dict:
    token = secrets.token_urlsafe(32)
    conversation_id = ConversationRepo(conn).create(user_id=principal.user_id, guest_session_hash=_token_hash(token))
    plan = PlanRepo(conn).create_plan(conversation_id, "새 추천", principal.user_id)
    version = PlanRepo(conn)._one(
        "SELECT dv.id FROM config.domain_version dv "
        "JOIN config.domain d ON d.id = dv.domain_id "
        "WHERE d.status = 'active' ORDER BY dv.version_no DESC LIMIT 1"
    )
    if version is None:
        raise ValidationFailed("게시된 도메인 버전이 없습니다.")
    revision = PlanRepo(conn).new_revision(plan, version["id"], "새 추천")
    PlanRepo(conn).set_current_revision(plan, revision)
    return {"list_id": str(plan), "browser_token": token}


# ── ConditionState 조립 ──────────────────────────────────────────────────
def _age_stage_label(months: int | None) -> str:
    if months is None:
        return "출산 예정"    # 아직 안 물어봤거나 응답 대기 — _build_fields 가 missing 처리
    if months == 0:
        return "출산 예정"    # 실제로 확정된 선택값 (q_age 의 값 0)
    if months <= 3:
        return "신생아기"
    if months <= 6:
        return "영아 초기"
    if months <= 12:
        return "영아기"
    if months <= 24:
        return "유아 초기"
    return "유아기"


def _field_value(meta: dict, values: dict):
    if meta.get("computed"):
        months = values.get(meta["computed"])
        return {"months": months, "label": _age_stage_label(months)}
    return values.get(meta["key"])


def _display(meta: dict, value) -> str | None:
    if value in (None, [], ""):
        return None
    if meta.get("computed"):
        return value["label"]
    disp_map = meta.get("display")
    if disp_map:
        return disp_map.get(value, disp_map.get(str(value), str(value)))
    if isinstance(value, list):
        return " · ".join("없음" if v == "none" else str(v) for v in value)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if meta["key"] == "budget_max" and isinstance(value, (int, float)):
        return f"{int(value):,}원"
    return str(value)


def _build_fields(cat_def: dict, values: dict) -> list[dict]:
    mode = values.get("mode")
    out = []
    for meta in cat_def.get("fields", []):
        if meta.get("mode_only") and meta["mode_only"] != mode:
            continue
        value = _field_value(meta, values)
        raw = values.get(meta["computed"]) if meta.get("computed") else value
        status = "confirmed" if raw not in (None, [], "") else "missing"
        out.append({
            "key": meta["key"], "label": meta["label"], "value": value,
            "display": _display(meta, value), "status": status, "editable": True,
        })
    return out


def _required_keys(cat_def: dict, values: dict) -> list[str]:
    req = list(cat_def.get("required_inputs", []))
    for mode, extra in (cat_def.get("required_inputs_by_mode") or {}).items():
        if values.get("mode") == mode:
            req += extra
    return req


def compute_missing(cat_def: dict, values: dict) -> list[str]:
    return [k for k in _required_keys(cat_def, values) if values.get(k) in (None, [], "")]


def _next_question(cat_def: dict, values: dict) -> dict | None:
    mode = values.get("mode")
    missing = set(compute_missing(cat_def, values))
    for q in cat_def.get("question_sets", []):
        if q.get("mode_only") and q["mode_only"] != mode:
            continue
        if q["maps_to"] not in missing:
            continue
        options = q.get("options") or []
        qvalues = q.get("values") or options
        return {
            "id": q["id"], "field": q["maps_to"], "text": q["label"], "select": q["select"],
            "options": [{"value": v, "label": o} for o, v in zip(options, qvalues)],
        }
    return None


def _messages_out(rows: list[dict]) -> list[dict]:
    return [{"id": str(r["id"]), "role": r["role"], "text": r["content"], "created_at": r["created_at"].isoformat()} for r in rows]


def _state(conn, list_id: UUID, principal: Principal) -> dict:
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    full = prepo.load_full(revision["id"])
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    category = values.get("category")
    messages = _messages_out(ConversationRepo(conn).messages(revision["conversation_id"]))
    if category is None:
        return {"list_id": str(list_id), "category": None, "messages": messages, "fields": [],
                "next_question": None, "can_recommend": False, "accepts_spec_file": False}
    cat_def = _category(category)
    return {
        "list_id": str(list_id), "category": category, "messages": messages,
        "fields": _build_fields(cat_def, values),
        "next_question": _next_question(cat_def, values),
        "can_recommend": not compute_missing(cat_def, values),
        "accepts_spec_file": False,  # TODO: 사양 파일 업로드 — §D-4-1 "결정 필요", 미구현
    }


def get_session_state(conn, list_id: UUID, principal: Principal) -> dict:
    return _state(conn, list_id, principal)


def choose_category(conn, list_id: UUID, category: str, mode: str | None, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    cat_def = _category(category)
    if mode is not None and mode not in cat_def["modes"]:
        raise ValidationFailed("카테고리에 맞지 않는 mode입니다.", field="mode")
    mode = mode or cat_def["modes"][0]
    repo.upsert_condition(current["id"], "category", {"value": category}, "explicit")
    repo.upsert_condition(current["id"], "mode", {"value": mode}, "explicit")
    nq = _next_question(cat_def, {"mode": mode})
    if nq:
        ConversationRepo(conn).add_message(current["conversation_id"], "assistant", nq["text"])
    return _state(conn, list_id, principal)


def patch_slot(conn, list_id: UUID, field: str, value, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    repo.upsert_condition(current["id"], field, {"value": value}, "explicit")
    return _state(conn, list_id, principal)


def _current_values(repo: PlanRepo, revision_id: UUID) -> tuple[dict, str | None]:
    full = repo.load_full(revision_id)
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    return values, values.get("category")


def handle_message(conn, list_id: UUID, text: str, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    convo = ConversationRepo(conn)
    msg_id = convo.add_message(current["conversation_id"], "user", text)

    extracted = slot_rules.extract(category, text)
    for key, value in extracted.items():
        repo.upsert_condition(current["id"], key, {"value": value}, "extracted", msg_id)
    values.update(extracted)

    nq = _next_question(cat_def, values)
    if nq:
        reply = nq["text"] if extracted else "죄송해요, 이해하지 못했어요. " + nq["text"]
    else:
        reply = "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def handle_answer(conn, list_id: UUID, question_id: str, selected: list, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    q = next((q for q in cat_def.get("question_sets", []) if q["id"] == question_id), None)
    if q is None:
        raise ValidationFailed("알 수 없는 질문입니다.", field="question_id")

    key = q["maps_to"]
    none_opt = q.get("none_option")
    if none_opt and list(selected) == [none_opt]:
        value = ["none"]
    elif q["select"] == "multi":
        value = list(selected)
    else:
        value = selected[0] if selected else None

    convo = ConversationRepo(conn)
    user_text = ", ".join(str(s) for s in selected) if selected else "(선택 없음)"
    msg_id = convo.add_message(current["conversation_id"], "user", user_text)
    repo.upsert_condition(current["id"], key, {"value": value}, "explicit", msg_id)
    values[key] = value

    nq = _next_question(cat_def, values)
    reply = nq["text"] if nq else "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def reset_conditions(conn, list_id: UUID, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    full = repo.load_full(current["id"])
    for row in full["conditions"]:
        if row["condition_key"] not in ("category", "mode"):
            repo.upsert_condition(current["id"], row["condition_key"], {"value": None}, "explicit")
    ConversationRepo(conn).add_message(current["conversation_id"], "system", "조건을 초기화했어요.")
    return _state(conn, list_id, principal)
