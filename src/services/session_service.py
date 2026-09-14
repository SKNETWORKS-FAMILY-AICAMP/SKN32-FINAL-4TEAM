"""세션 생성과 조건 대화 서비스 (계약: docs/frontend_외부수정요청.md §D-4-1)."""
from __future__ import annotations
import datetime as _dt
import hashlib, logging, re, secrets
from typing import TypedDict
from uuid import UUID
from src.agent import conditions_agent
from src.auth.deps import Principal
from src.categories import available_categories, load_category
from src.engine import slot_rules
from src.errors import Conflict, FileTooLarge, NotFound, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import ConversationRepo

log = logging.getLogger(__name__)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _category(name: str) -> dict:
    try:
        return load_category(name)
    except FileNotFoundError:
        raise ValidationFailed("지원하지 않는 카테고리입니다.", field="category") from None


class NormalizedConditions(TypedDict, total=False):
    category: str
    mode: str | None
    age_stage: dict | None
    due_date: str | None
    needs: list
    health_skin: list
    owned_items: list
    budget_max: int | None
    weight_kg: float | None
    independent_sitting: bool | None


def normalize_baby_conditions(values: dict) -> NormalizedConditions:
    """세션 조건을 유아 요구사항 엔진의 고정 입력 형태로 변환한다."""
    raw_age = values.get("age_months")
    months = raw_age.get("value") if isinstance(raw_age, dict) else raw_age
    exact = bool(raw_age.get("exact", True)) if isinstance(raw_age, dict) else True
    return {
        "category": "baby", "mode": values.get("mode"),
        "age_stage": {"months": months, "label": _age_stage_label(months), "exact": exact}
        if "age_months" in values else None,
        "due_date": values.get("due_date"), "needs": list(values.get("needs") or []),
        "health_skin": list(values.get("health_skin") or []),
        "owned_items": list(values.get("owned_items") or []),
        "budget_max": values.get("budget_max"), "weight_kg": values.get("weight_kg"),
        "independent_sitting": values.get("independent_sitting"),
    }


_NEEDS_ALLOWED = {"수유", "이유식·식사", "수면", "외출", "목욕·위생", "기저귀·배변", "의류", "놀이", "안전·건강"}


def _validate_baby_value(cat_def: dict, field: str, value, *, mode: str | None, none_token: str | None = None):
    schema = (cat_def.get("slot_schema") or {}).get(field)
    if schema is None:
        raise ValidationFailed("허용되지 않는 필드입니다.", field="field")
    if schema.get("mode_only") and schema["mode_only"] != mode:
        raise ValidationFailed(f"{mode} 모드에서는 사용할 수 없는 필드입니다.", field=field)
    kind = schema["type"]
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationFailed("0 이상의 정수여야 합니다.", field=field)
    elif kind == "money":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value <= 0:
            raise ValidationFailed("0보다 큰 정수 금액이어야 합니다.", field=field)
        value = int(value)
    elif kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValidationFailed("0보다 큰 숫자여야 합니다.", field=field)
        value = float(value)
    elif kind == "bool":
        if not isinstance(value, bool):
            raise ValidationFailed("true/false 값이어야 합니다.", field=field)
    elif kind == "date":
        try:
            _dt.date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValidationFailed("날짜 형식이 올바르지 않습니다.", field=field) from None
    elif kind == "list":
        if not isinstance(value, list):
            raise ValidationFailed("목록 형태여야 합니다.", field=field)
        if not value and schema.get("none_allowed"):
            return []
        if not value:
            raise ValidationFailed("최소 1개 이상 선택해야 합니다.", field=field)
        if field == "needs" and any(item not in _NEEDS_ALLOWED for item in value):
            raise ValidationFailed("허용되지 않는 값입니다.", field=field)
        if none_token and none_token in value:
            if len(value) != 1:
                raise ValidationFailed("'없음'은 다른 항목과 함께 선택할 수 없습니다.", field=field)
            return []
        value = list(value) if field == "owned_items" else list(dict.fromkeys(value))
    return value


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
    token = principal.browser_token
    reused = False
    if principal.user_id is None:
        if token and ConversationRepo(conn).guest_identity_known(_token_hash(token)):
            reused = True
        else:
            token = secrets.token_urlsafe(32)
    conversation_id = ConversationRepo(conn).create(
        user_id=principal.user_id,
        guest_session_hash=None if principal.user_id is not None else _token_hash(token),
    )
    plan = PlanRepo(conn).create_plan(conversation_id, "새 추천", principal.user_id)
    version = PlanRepo(conn)._one(
        "SELECT dv.id FROM config.domain_version dv "
        "JOIN config.domain d ON d.id = dv.domain_id "
        "WHERE d.status = 'active' AND d.code = ANY(%s) ORDER BY d.code, dv.version_no DESC LIMIT 1",
        (available_categories(),),
    )
    if version is None:
        raise ValidationFailed("게시된 도메인 버전이 없습니다.")
    revision = PlanRepo(conn).new_revision(plan, version["id"], "새 추천")
    PlanRepo(conn).set_current_revision(plan, revision)
    return {"list_id": str(plan), "browser_token": None if principal.user_id is not None else token, "reused": reused}


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
        raw = values.get(meta["computed"])
        months = raw.get("value") if isinstance(raw, dict) else raw
        exact = bool(raw.get("exact", True)) if isinstance(raw, dict) else True
        return {"months": months, "label": _age_stage_label(months), "exact": exact}
    return values.get(meta["key"])


def _display(meta: dict, value, values: dict | None = None) -> str | None:
    values = values or {}
    if value in (None, [], ""):
        return None
    if meta.get("computed"):
        return value["label"]
    disp_map = meta.get("display")
    if values.get("language") == "en" and meta.get("display_en"):   # 영어 사용자 — 패널·조건 요약의 표시값 (라벨은 프론트 i18n)
        disp_map = meta["display_en"]
    if disp_map:
        return disp_map.get(value, disp_map.get(str(value), str(value)))
    if isinstance(value, list):
        return " · ".join("없음" if v == "none" else str(v) for v in value)
    if isinstance(value, dict):
        return " · ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if meta["key"] == "budget_max" and isinstance(value, (int, float)):
        if values.get("currency") == "USD":   # 달러로 말한 사용자 — 달러만 (고정 환율 src/config.USD_KRW_RATE)
            from src.agent.conditions_agent import usd
            return usd(int(value))
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
        source_key = meta.get("computed") or meta["key"]
        status = "confirmed" if source_key in values and raw is not None else "missing"
        out.append({
            "key": meta["key"], "label": meta["label"], "value": value,
            "display": _display(meta, value, values), "status": status, "editable": True,
        })
    return out


def _required_keys(cat_def: dict, values: dict) -> list[str]:
    req = list(cat_def.get("required_inputs", []))
    for mode, extra in (cat_def.get("required_inputs_by_mode") or {}).items():
        if values.get("mode") == mode:
            req += extra
    return req


def compute_missing(cat_def: dict, values: dict) -> list[str]:
    return [k for k in _required_keys(cat_def, values) if k not in values or values[k] is None]


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


def _canonicalize_answer_values(question: dict, selected: list) -> list:
    """질문 선택지를 API에 정의된 원래 타입으로 되돌린다.

    HTML의 ``data-*`` 속성은 숫자와 불리언도 문자열로 만든다. ``values``가 있는
    선택지는 표시 라벨이나 문자열화된 값을 받아도 YAML의 원래 값으로 정규화한다.
    """
    options = question.get("options") or []
    values = question.get("values") or []
    if not values:
        return list(selected)

    normalized = []
    for item in selected:
        canonical = next(
            (value for option, value in zip(options, values)
             if item == option or item == value or str(item).casefold() == str(value).casefold()),
            item,
        )
        normalized.append(canonical)
    return normalized


def _messages_out(rows: list[dict]) -> list[dict]:
    return [{"id": str(r["id"]), "role": r["role"], "text": r["content"], "created_at": r["created_at"].isoformat()} for r in rows]


def _state(conn, list_id: UUID, principal: Principal) -> dict:
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    full = prepo.load_full(revision["id"])
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
    category = values.get("category")
    messages = _messages_out(ConversationRepo(conn).messages(revision["conversation_id"]))
    if category is None:
        return {"list_id": str(list_id), "category": None, "mode": None, "messages": messages, "fields": [],
                "next_question": None, "can_recommend": False, "accepts_spec_file": False,
                "revision_id": str(revision["id"]), "lock_version": revision["lock_version"]}
    cat_def = _category(category)
    return {
        "list_id": str(list_id), "category": category, "mode": values.get("mode"), "messages": messages,
        "fields": _build_fields(cat_def, values),
        "next_question": _next_question(cat_def, values),
        "can_recommend": not compute_missing(cat_def, values),
        "accepts_spec_file": category == "computer" and values.get("mode") == "upgrade",
        "revision_id": str(revision["id"]), "lock_version": revision["lock_version"],
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
    values, previous_category = _current_values(repo, current["id"])
    previous_mode = values.get("mode")
    repo.bind_domain_version(current["id"], category)
    repo.upsert_condition(current["id"], "category", {"value": category}, "explicit")
    repo.upsert_condition(current["id"], "mode", {"value": mode}, "explicit")
    if previous_category is not None and previous_category != category:
        for key in values:
            if key not in {"category", "mode"}:
                repo.clear_condition(current["id"], key)
    elif category == "baby" and previous_mode is not None and previous_mode != mode:
        keys = ("due_date",) if mode == "born" else ("age_months", "weight_kg", "independent_sitting")
        for key in keys:
            repo.clear_condition(current["id"], key)
    nq = _next_question(cat_def, {"mode": mode})
    if nq:
        ConversationRepo(conn).add_message(current["conversation_id"], "assistant", nq["text"])
    return _state(conn, list_id, principal)


def patch_slot(conn, list_id: UUID, field: str, value, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category == "baby":
        cat_def = _category(category)
        if value is None:
            if field not in (cat_def.get("slot_schema") or {}):
                raise ValidationFailed("허용되지 않는 필드입니다.", field="field")
            repo.clear_condition(current["id"], field)
            return _state(conn, list_id, principal)
        value = _validate_baby_value(cat_def, field, value, mode=values.get("mode"))
    repo.upsert_condition(current["id"], field, {"value": value}, "explicit")
    return _state(conn, list_id, principal)


def _current_values(repo: PlanRepo, revision_id: UUID) -> tuple[dict, str | None]:
    full = repo.load_full(revision_id)
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
    return values, values.get("category")


_ALL_SET = "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."


def handle_message(conn, list_id: UUID, text: str, principal: Principal) -> dict:
    """자유 텍스트 한 턴. 에이전트가 있으면 도구 호출로 조건을 뽑고 답변 문장까지 만든다.

    에이전트가 없거나(MOCK_MODE·키 없음) 호출이 실패하면 규칙 추출(slot_rules)로 이번 턴을
    처리한다. 실패는 로그에만 남는다 — 화면에서는 규칙 경로와 구분되지 않는다.
    """
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    convo = ConversationRepo(conn)
    history = convo.messages(current["conversation_id"])     # 이번 메시지를 넣기 전
    msg_id = convo.add_message(current["conversation_id"], "user", text)

    reply: str | None = None
    extracted: dict = {}
    if conditions_agent.available():
        try:
            turn = conditions_agent.run_turn(
                category, cat_def, values, history, text,
                missing_fn=lambda v: compute_missing(cat_def, v),
                next_question_fn=lambda v: _next_question(cat_def, v))
            extracted, reply = turn.patches, turn.reply
            log.info("conditions agent [%s]: %s", list_id, " | ".join(turn.trace) or "(도구 호출 없음)")
        except Exception as exc:  # 모델·네트워크 오류 — 이번 턴만 규칙으로
            log.warning("conditions agent failed, falling back to slot_rules: %s", exc)
    if reply is None:
        extracted = slot_rules.extract(category, text)

    for key, value in extracted.items():
        repo.upsert_condition(current["id"], key, {"value": value}, "extracted", msg_id)
    values.update(extracted)

    nq = _next_question(cat_def, values)
    if reply is None:
        if nq:
            reply = nq["text"] if extracted else "죄송해요, 이해하지 못했어요. " + nq["text"]
        else:
            reply = _ALL_SET
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

    raw_selected = list(selected)
    selected = _canonicalize_answer_values(q, raw_selected)
    key = q["maps_to"]
    none_opt = q.get("none_option")
    if none_opt and list(selected) == [none_opt]:
        value = [] if category == "baby" else ["none"]
    elif q["select"] == "multi":
        value = list(selected)
    else:
        value = selected[0] if selected else None

    convo = ConversationRepo(conn)
    user_text = ", ".join(str(s) for s in raw_selected) if raw_selected else "(선택 없음)"
    msg_id = convo.add_message(current["conversation_id"], "user", user_text)
    if category == "baby":
        value = _validate_baby_value(cat_def, key, value, mode=values.get("mode"), none_token=none_opt)
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


# ── 업그레이드 사양 파일 첨부 (§D-4-1: current_specs · spec_file_name) ──
_ALLOWED_SPEC_EXTENSIONS = {"txt", "json", "csv", "md", "log", "nfo", "xml"}
_MAX_SPEC_FILE_BYTES = 1_000_000
_SPEC_LINE = re.compile(r"(?im)^\s*(cpu|프로세서|gpu|그래픽카드|그래픽|ram|메모리)\s*[:=]\s*(.+?)\s*$")
_SPEC_KEY_MAP = {"cpu": "CPU", "프로세서": "CPU", "gpu": "GPU", "그래픽카드": "GPU", "그래픽": "GPU",
                 "ram": "RAM", "메모리": "RAM"}


def _parse_spec_file(content: str) -> dict:
    """'CPU: i5-13600K' 같은 key: value 줄만 규칙 기반으로 뽑는다. 매칭 안 되면 빈 dict."""
    specs: dict[str, str] = {}
    for m in _SPEC_LINE.finditer(content):
        specs[_SPEC_KEY_MAP[m.group(1).lower()]] = m.group(2).strip()
    return specs


def attach_spec_file(conn, list_id: UUID, file_name: str, content: str, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext not in _ALLOWED_SPEC_EXTENSIONS:
        raise ValidationFailed("지원하지 않는 파일 형식입니다.", field="file_name", code="unsupported_file")
    if len(content.encode("utf-8")) > _MAX_SPEC_FILE_BYTES:
        raise FileTooLarge("파일이 너무 큽니다(1MB 이하).", field="content")
    specs = _parse_spec_file(content)
    repo.upsert_condition(current["id"], "spec_file_name", {"value": file_name}, "explicit")
    if specs:
        repo.upsert_condition(current["id"], "current_specs", {"value": specs}, "extracted")
    return _state(conn, list_id, principal)
