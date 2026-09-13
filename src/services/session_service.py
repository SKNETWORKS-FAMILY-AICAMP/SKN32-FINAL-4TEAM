"""세션 생성과 조건 대화 서비스 (계약: docs/frontend_외부수정요청.md §D-4-1, docs/agent-tasks/baby/CONTRACTS.md).

P5/P7 이 재사용하는 공유 진입점:
  - `load_owned_draft(conn, list_id, principal)` — 소유권 검증 후 현재 리비전 행.
  - `normalize_baby_conditions(values)` — CONTRACTS 조건 목표 스키마로 정규화한 baby 조건 스냅샷.
"""
from __future__ import annotations
import datetime as _dt
import hashlib, re, secrets
from typing import TypedDict
from uuid import UUID
from src.auth.deps import Principal
from src.categories import available_categories, load_category
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


def load_owned_draft(conn, list_id: UUID, principal: Principal) -> dict:
    """소유권 확인 후 목록의 현재 리비전 행을 반환한다.

    다른 사람 소유이거나 존재하지 않는 목록은 동일하게 404 — 존재 여부를 노출하지 않는다.
    게스트 쿠키가 없거나 다른 목록의 것이면(=해시 불일치) 접근할 수 없다.
    P5(추천 시작)·P7 이 여기 재사용해야 계정/게스트 경계가 하나로 유지된다.
    """
    revision = PlanRepo(conn).get_current_revision(list_id)
    if revision is None:
        raise NotFound("목록을 찾을 수 없습니다.")
    user_ok = principal.user_id is not None and revision["user_id"] == principal.user_id
    guest_ok = principal.browser_token is not None and revision["guest_session_hash"] == _token_hash(principal.browser_token)
    if not (user_ok or guest_ok):
        raise NotFound("목록을 찾을 수 없습니다.")
    return revision


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
    """`_current_values`가 반환한 원시 revision 조건을 CONTRACTS 조건 목표 스키마로 정규화한다.

    P5(추천 시작 전 조건 스냅샷)·P7 이 이 함수 하나만 재사용하면 age_months 의
    구간대표/정확 구분(`_unwrap_age`) 이나 "none" 내부 표현을 각자 다시 구현하지 않는다.
    """
    months, exact = _unwrap_age(values.get("age_months"))
    return {
        "category": "baby",
        "mode": values.get("mode"),
        "age_stage": {"months": months, "label": _age_stage_label(months), "exact": exact} if "age_months" in values else None,
        "due_date": values.get("due_date"),
        "needs": list(values.get("needs") or []),
        "health_skin": list(values.get("health_skin") or []),
        "owned_items": list(values.get("owned_items") or []),
        "budget_max": values.get("budget_max"),
        "weight_kg": values.get("weight_kg"),
        "independent_sitting": values.get("independent_sitting"),
    }


def create_session(conn, principal: Principal) -> dict:
    """세션 생성. 유효한 게스트 쿠키가 있으면 재사용해 여러 목록이 같은 정체성을 공유하게 한다.

    매번 새 토큰을 발급하면 쿠키가 회전해 이전 목록이 404 가 된다(P0 sync 감사에 기록된 버그).
    미지·위조 쿠키는 새 토큰으로 대체한다(다른 사람 정체성을 훔쳐 붙는 것을 막는다).
    """
    reused = False
    token = principal.browser_token
    if principal.user_id is None:
        if token and ConversationRepo(conn).guest_identity_known(_token_hash(token)):
            reused = True
        else:
            token = secrets.token_urlsafe(32)
    guest_hash = None if principal.user_id is not None else _token_hash(token)
    conversation_id = ConversationRepo(conn).create(user_id=principal.user_id, guest_session_hash=guest_hash)
    plan = PlanRepo(conn).create_plan(conversation_id, "새 추천", principal.user_id)
    # 세션 생성 시점에는 카테고리가 아직 없다. 임의의 "가장 최근 active 도메인"을 집으면
    # RAG 평가용 같은 런타임 외 도메인이 섞여 들어오므로, 실제 카테고리 정의 파일이 있는
    # 코드만 후보로 두고 결정적으로 고른다. 실제 규칙은 choose_category 가 다시 묶는다.
    domain_version = PlanRepo(conn)._one(
        "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id = dv.domain_id "
        "WHERE d.status = 'active' AND d.code = ANY(%s) ORDER BY d.code, dv.version_no DESC LIMIT 1",
        (available_categories(),),
    )
    if domain_version is None:
        raise ValidationFailed("게시된 도메인 버전이 없습니다.")
    revision = PlanRepo(conn).new_revision(plan, domain_version["id"], "새 추천")
    PlanRepo(conn).set_current_revision(plan, revision)
    return {
        "list_id": str(plan),
        "browser_token": None if principal.user_id is not None else token,
        "reused": reused,
    }


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


def _unwrap_age(raw) -> tuple[int | None, bool]:
    """age_months 는 {"value": int, "exact": bool} 로 저장될 수 있다(칩=대표값 vs 자유입력=정확값).

    다른 필드는 평범한 스칼라/리스트라 그대로 통과한다."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value"), bool(raw.get("exact", True))
    return raw, True


def _field_value(meta: dict, values: dict):
    if meta.get("computed"):
        months, exact = _unwrap_age(values.get(meta["computed"]))
        return {"months": months, "label": _age_stage_label(months), "exact": exact}
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
        return " · ".join("없음" if v in ("none", "없음") else str(v) for v in value)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if meta["key"] in ("budget_max",) and isinstance(value, (int, float)):
        return f"{int(value):,}원"
    if meta["key"] == "weight_kg" and isinstance(value, (int, float)):
        return f"{value:g}kg"
    return str(value)


def _build_fields(cat_def: dict, values: dict) -> list[dict]:
    mode = values.get("mode")
    out = []
    for meta in cat_def.get("fields", []):
        if meta.get("mode_only") and meta["mode_only"] != mode:
            continue
        key = meta.get("computed") or meta["key"]
        present = key in values
        value = _field_value(meta, values)
        if not present:
            status = "missing"
        elif meta.get("computed"):
            _, exact = _unwrap_age(values.get(key))
            status = "confirmed" if exact else "assumed"
        else:
            status = "confirmed"
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
    """행이 존재(=응답함)하는지로 판단한다 — 빈 리스트([]) 는 명시적 "없음" 응답이라 missing 이 아니다.

    행이 아예 없거나 값이 None(직접 clear 된 스칼라)인 경우만 missing."""
    return [k for k in _required_keys(cat_def, values) if k not in values or values[k] is None]


def _question_out(q: dict) -> dict:
    options = q.get("options") or []
    qvalues = q.get("values") or options
    return {
        "id": q["id"], "field": q["maps_to"], "text": q["label"], "select": q["select"],
        "options": [{"value": v, "label": o} for o, v in zip(options, qvalues)],
    }


def _next_question(cat_def: dict, values: dict) -> dict | None:
    mode = values.get("mode")
    missing = set(compute_missing(cat_def, values))
    for q in cat_def.get("question_sets", []):
        if q.get("mode_only") and q["mode_only"] != mode:
            continue
        if q.get("requires_need"):
            continue  # 선택 안전질문은 필수 항목을 다 채운 뒤 아래에서 별도 처리
        if q["maps_to"] not in missing:
            continue
        return _question_out(q)
    if missing:
        return None
    # 필수 항목을 모두 채운 뒤에만, 관련 need 가 확인된 선택 안전질문을 물어본다.
    # (independent_sitting/weight_kg 를 나이만으로 추론하거나 관련 없는 사용자에게 강요하지 않는다.)
    needs = values.get("needs") or []
    for q in cat_def.get("question_sets", []):
        if q.get("mode_only") and q["mode_only"] != mode:
            continue
        req_need = q.get("requires_need")
        if not req_need or not any(n in needs for n in req_need):
            continue
        if q["maps_to"] in values:
            continue
        return _question_out(q)
    return None


def _messages_out(rows: list[dict]) -> list[dict]:
    return [{"id": str(r["id"]), "role": r["role"], "text": r["content"], "created_at": r["created_at"].isoformat()} for r in rows]


def _state(conn, list_id: UUID, principal: Principal) -> dict:
    prepo = PlanRepo(conn)
    revision = load_owned_draft(conn, list_id, principal)
    full = prepo.load_full(revision["id"])
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
    category = values.get("category")
    messages = _messages_out(ConversationRepo(conn).messages(revision["conversation_id"]))
    if category is None:
        return {
            "list_id": str(list_id), "category": None, "mode": None, "messages": messages, "fields": [],
            "next_question": None, "can_recommend": False, "accepts_spec_file": False,
            "revision_id": str(revision["id"]), "lock_version": revision["lock_version"],
        }
    cat_def = _category(category)
    return {
        "list_id": str(list_id), "category": category, "mode": values.get("mode"), "messages": messages,
        "fields": _build_fields(cat_def, values),
        "next_question": _next_question(cat_def, values),
        "can_recommend": not compute_missing(cat_def, values),
        "accepts_spec_file": False,  # TODO: 사양 파일 업로드 — §D-4-1 "결정 필요", 미구현
        "revision_id": str(revision["id"]), "lock_version": revision["lock_version"],
    }


def get_session_state(conn, list_id: UUID, principal: Principal) -> dict:
    return _state(conn, list_id, principal)


def choose_category(conn, list_id: UUID, category: str, mode: str | None, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = load_owned_draft(conn, list_id, principal)
    cat_def = _category(category)
    if mode is not None and mode not in cat_def["modes"]:
        raise ValidationFailed("카테고리에 맞지 않는 mode입니다.", field="mode")
    mode = mode or cat_def["modes"][0]
    values, prev_category = _current_values(repo, current["id"])
    prev_mode = values.get("mode")
    # 카테고리가 정해지는 유일한 지점 — 리비전을 그 카테고리의 게시 도메인 버전에 다시 묶는다.
    # 이후 recommendation_run 도 revision["domain_version_id"] 를 그대로 쓰므로 여기서 어긋나면
    # 실행 스냅샷까지 다른 카테고리 규칙이 된다(P0 SR07).
    repo.bind_domain_version(current["id"], category)
    repo.upsert_condition(current["id"], "category", {"value": category}, "explicit")
    repo.upsert_condition(current["id"], "mode", {"value": mode}, "explicit")
    if prev_category is not None and prev_category != category:
        # 카테고리 자체가 바뀌면 이전 카테고리 전용 필드는 전부 호환되지 않는다.
        for key in list(values.keys()):
            if key not in ("category", "mode"):
                repo.clear_condition(current["id"], key)
    elif category == "baby" and prev_mode is not None and mode != prev_mode:
        # 동일 카테고리에서 born<->prenatal 전환 — 서로 다른 필드 집합을 요구한다(CONTRACTS SS06).
        if mode == "born":
            repo.clear_condition(current["id"], "due_date")
        elif mode == "prenatal":
            for key in ("age_months", "weight_kg", "independent_sitting"):
                repo.clear_condition(current["id"], key)
    nq = _next_question(cat_def, {"mode": mode})
    if nq:
        ConversationRepo(conn).add_message(current["conversation_id"], "assistant", nq["text"])
    return _state(conn, list_id, principal)


# ── baby 조건 값 검증 (CONTRACTS: 허용 필드/타입/옵션/none, mode·date 일관성) ──
_NEEDS_ALLOWED = {"수유", "이유식·식사", "수면", "외출", "목욕·위생", "기저귀·배변", "의류", "놀이", "안전·건강"}
_NONE_TOKENS = {"none", "없음"}


def _validate_baby_value(cat_def: dict, field: str, value, *, mode: str | None, none_token: str | None = None):
    """`field`/`value` 를 baby.yaml 의 slot_schema 로 검증하고 저장 가능한 형태로 정규화한다.

    computer 카테고리는 이 함수를 타지 않는다 — 기존 PC 조건 경로를 그대로 보존한다(작업 지시서
    "Preserve working PC condition path")."""
    schema = (cat_def.get("slot_schema") or {}).get(field)
    if schema is None or field in ("category", "mode"):
        raise ValidationFailed(f"허용되지 않는 필드입니다: {field}", field="field")
    mode_only = schema.get("mode_only")
    if mode_only and mode is not None and mode_only != mode:
        raise ValidationFailed(f"{mode} 모드에서는 사용할 수 없는 필드입니다.", field=field)
    t = schema["type"]
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationFailed("정수여야 합니다.", field=field)
        if value < 0:
            raise ValidationFailed("0 이상의 정수여야 합니다.", field=field)
        return value
    if t == "money":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
            raise ValidationFailed("정수 금액이어야 합니다.", field=field)
        value = int(value)
        if value <= 0:
            raise ValidationFailed("0보다 큰 금액이어야 합니다.", field=field)
        return value
    if t == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationFailed("숫자여야 합니다.", field=field)
        value = float(value)
        if value <= 0:
            raise ValidationFailed("0보다 큰 값이어야 합니다.", field=field)
        return value
    if t == "bool":
        if not isinstance(value, bool):
            raise ValidationFailed("true/false 값이어야 합니다.", field=field)
        return value
    if t == "date":
        if not isinstance(value, str):
            raise ValidationFailed("날짜 형식이 올바르지 않습니다(YYYY-MM-DD).", field=field)
        try:
            _dt.date.fromisoformat(value)
        except ValueError:
            raise ValidationFailed("날짜 형식이 올바르지 않습니다(YYYY-MM-DD).", field=field) from None
        return value
    if t == "list":
        if not isinstance(value, list):
            raise ValidationFailed("목록 형태여야 합니다.", field=field)
        none_matches = _NONE_TOKENS | ({none_token} if none_token else set())
        if any(v in none_matches for v in value):
            if len(value) > 1:
                raise ValidationFailed("'없음'은 다른 항목과 함께 선택할 수 없습니다.", field=field)
            if not schema.get("none_allowed"):
                raise ValidationFailed("이 필드는 '없음'을 허용하지 않습니다.", field=field)
            return []
        if field == "needs":
            bad = [v for v in value if v not in _NEEDS_ALLOWED]
            if bad:
                raise ValidationFailed(f"허용되지 않는 값입니다: {bad}", field=field)
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValidationFailed("최소 1개 이상 선택해야 합니다.", field=field)
        return deduped
    raise ValidationFailed(f"허용되지 않는 필드입니다: {field}", field="field")


def patch_slot(conn, list_id: UUID, field: str, value, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = load_owned_draft(conn, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if field in ("category", "mode"):
        raise ValidationFailed("category/mode 는 /category 로만 변경할 수 있습니다.", field="field")
    if category == "baby":
        cat_def = _category(category)
        if value is None:
            if (cat_def.get("slot_schema") or {}).get(field) is None:
                raise ValidationFailed(f"허용되지 않는 필드입니다: {field}", field="field")
            repo.clear_condition(current["id"], field)
        else:
            validated = _validate_baby_value(cat_def, field, value, mode=values.get("mode"))
            stored = {"value": validated, "exact": True} if field == "age_months" else {"value": validated}
            repo.upsert_condition(current["id"], field, stored, "explicit")
    else:
        # 다른 카테고리(computer 등)는 기존 동작을 그대로 보존한다 — 이 과업 범위 밖.
        if value is None:
            repo.clear_condition(current["id"], field)
        else:
            repo.upsert_condition(current["id"], field, {"value": value}, "explicit")
    return _state(conn, list_id, principal)


def _current_values(repo: PlanRepo, revision_id: UUID) -> tuple[dict, str | None]:
    full = repo.load_full(revision_id)
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
    return values, values.get("category")


def handle_message(conn, list_id: UUID, text: str, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = load_owned_draft(conn, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    convo = ConversationRepo(conn)
    msg_id = convo.add_message(current["conversation_id"], "user", text)

    extracted = slot_rules.extract(category, text)
    applied: dict = {}
    for key, raw_value in extracted.items():
        if category == "baby":
            try:
                validated = _validate_baby_value(cat_def, key, raw_value, mode=values.get("mode"))
            except ValidationFailed:
                # 규칙 기반 추출이 애매하거나 현재 mode 와 안 맞는 값을 잘못 뽑아낸 경우 —
                # 자유 텍스트에서 나온 값이라 실패시키지 않고 그냥 missing 으로 남긴다(CONTRACTS SS03).
                continue
            stored = {"value": validated, "exact": True} if key == "age_months" else {"value": validated}
        else:
            validated = raw_value
            stored = {"value": raw_value}
        repo.upsert_condition(current["id"], key, stored, "extracted", msg_id)
        applied[key] = validated
    values.update(applied)

    nq = _next_question(cat_def, values)
    if nq:
        reply = nq["text"] if applied else "죄송해요, 이해하지 못했어요. " + nq["text"]
    else:
        reply = "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def handle_answer(conn, list_id: UUID, question_id: str, selected: list, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    current = load_owned_draft(conn, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    q = next((q for q in cat_def.get("question_sets", []) if q["id"] == question_id), None)
    if q is None:
        raise ValidationFailed("알 수 없는 질문입니다.", field="question_id")

    key = q["maps_to"]
    none_opt = q.get("none_option")
    if q["select"] == "multi":
        value = list(selected)
    else:
        value = selected[0] if selected else None

    if value is None:
        raise ValidationFailed("답변이 필요합니다.", field="selected")
    if category == "baby":
        value = _validate_baby_value(cat_def, key, value, mode=values.get("mode"), none_token=none_opt)

    convo = ConversationRepo(conn)
    user_text = ", ".join(str(s) for s in selected) if selected else "(선택 없음)"
    msg_id = convo.add_message(current["conversation_id"], "user", user_text)
    exact = q.get("exact", True)
    stored = {"value": value, "exact": exact} if key == "age_months" else {"value": value}
    repo.upsert_condition(current["id"], key, stored, "explicit", msg_id)
    values[key] = value

    nq = _next_question(cat_def, values)
    reply = nq["text"] if nq else "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def reset_conditions(conn, list_id: UUID, principal: Principal) -> dict:
    """계약: 선택 카테고리는 유지하고 조건/대화를 비운다."""
    repo = PlanRepo(conn)
    current = load_owned_draft(conn, list_id, principal)
    values, category = _current_values(repo, current["id"])
    for key in list(values.keys()):
        if key not in ("category", "mode"):
            repo.clear_condition(current["id"], key)
    ConversationRepo(conn).delete_messages(current["conversation_id"])
    if category:
        cat_def = _category(category)
        nq = _next_question(cat_def, {"mode": values.get("mode")})
        if nq:
            ConversationRepo(conn).add_message(current["conversation_id"], "assistant", nq["text"])
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


def _owned(repo: PlanRepo, list_id: UUID, principal: Principal) -> dict:
    revision = repo.get_current_revision(list_id)
    if revision is None:
        raise NotFound("목록을 찾을 수 없습니다.")
    user_ok = principal.user_id is not None and revision["user_id"] == principal.user_id
    guest_ok = principal.browser_token is not None and revision["guest_session_hash"] == _token_hash(principal.browser_token)
    if not (user_ok or guest_ok):
        raise NotFound("목록을 찾을 수 없습니다.")
    return revision
