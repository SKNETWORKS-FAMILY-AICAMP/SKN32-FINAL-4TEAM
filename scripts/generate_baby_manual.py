"""Deterministic synthetic manuals; standard library only, no LLM or network.

Run: python scripts/generate_baby_manual.py --input product.json --output new_dir

``data/baby/catalog_demo_v1.json``처럼 ``records[]``를 가진 실제 시드 카탈로그도
직접 입력으로 받는다. 카탈로그의 가격·판매처 정보는 사용 지침이 아니므로 본문에
넣지 않으며, 명시적으로 지원하는 품목/조건 템플릿만 렌더링한다.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
NOTICE = "가상제품 / RAG 테스트용 / 실제 사용 지침 아님"
SECTIONS = {
    "S01": "사용 대상과 사용 조건", "S02": "구성품",
    "S03": "조립·설치", "S04": "사용 전 점검", "S05": "기능과 사용",
    "S06": "경고·사용 중단", "S07": "제품 사양과 호환",
    "S08": "부품별 관리", "S09": "문제 해결", "S10": "보관·운반",
}
CATEGORIES = {
    "stroller": "유모차", "car_seat": "카시트", "carrier": "아기띠", "crib": "아기침대",
    "sleepwear": "수면조끼/우주복", "bottle": "젖병", "formula": "분유", "high_chair": "하이체어",
    "baby_food": "이유식", "cup": "빨대컵", "bib": "턱받이", "diaper": "기저귀",
    "wipes": "물티슈", "bath": "목욕용품", "skincare": "스킨케어", "mat": "놀이매트",
    "gate": "안전문/펜스", "thermometer": "체온계",
}
MODES = {
    "seat": "좌석", "tape": "테이프형", "pants": "팬티형",
    # The committed seed catalog uses these canonical diaper type values.
    "disposable": "일회용", "pull_up": "풀업형",
}
DEVELOPMENT = {"independent_sitting": "혼자 앉을 수 있음"}
METHODS = {"hand_wash": "손세척", "boiling": "열탕 소독", "steam": "스팀 소독",
           "uv": "UV 소독", "dishwasher": "식기세척기"}
# field: (section, Korean label, unit, expected type)
FIELDS = {
    "stroller": {
        "assembled_weight_kg": ("S07", "좌석 장착 제품 무게", "kg", "number"),
        "seat_max_kg": ("S07", "좌석 최대 하중", "kg", "number"),
        "basket_max_kg": ("S07", "바구니 최대 하중", "kg", "number"),
        "folded_cm": ("S07", "접힌 크기(가로 × 깊이 × 높이)", "cm", "dimensions"),
        "unfolded_cm": ("S07", "펼친 크기(가로 × 깊이 × 높이)", "cm", "dimensions"),
        "one_hand_fold": ("S05", "한 손 접기 기능", "", "bool"),
        "self_standing_folded": ("S05", "접힌 상태 자립 기능", "", "bool"),
        "newborn_setup": ("S01", "신생아 구성", "", "newborn"),
    },
    "bottle": {"capacity_ml": ("S07", "젖병 용량", "mL", "number"),
               "pack_count": ("S02", "포장 수량", "개", "integer")},
    "diaper": {"pack_count": ("S02", "포장 수량", "개", "integer")},
    "cup": {"capacity_ml": ("S07", "컵 용량", "mL", "number"),
            "washable_part_count": ("S08", "세척 부품 수", "개", "integer")},
}
SPECIALIZED_CATEGORIES = frozenset(FIELDS)


class ManualError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ManualError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value), f"잘못된 식별자: {value!r}")
    return value


def plain(value):
    require(isinstance(value, str) and value.strip() and not any(x in value for x in "\r\n<>[]`"),
            "표시 문자열에 빈 값·줄바꿈·Markdown 제어 문자를 사용할 수 없습니다")
    return value.replace("*", "\\*").replace("_", "\\_").replace("|", "\\|")


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f"잘못된 수치: {value!r}")
    return format(value, "g")


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"중복 JSON 키: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ManualError(f"비유한 값: {value}")))


def _catalog_record_to_product(record: dict, manifest: dict) -> tuple[dict, list]:
    """Convert one committed seed-catalog record without inventing instructions.

    The catalog deliberately stores recommendation data, not the richer manual
    input format.  Known values are copied from ``attributes`` and absent manual
    fields remain ``unknown``; offer prices, stock and synthetic facts are kept
    in the provenance snapshot but are never represented as usage guidance.
    """
    require(isinstance(record, dict), "카탈로그 레코드는 객체여야 합니다")
    require(record.get("is_synthetic") is True and record.get("market") == "KR_DEMO",
            "KR_DEMO 가상 카탈로그만 지원합니다")
    category = record.get("category_code")
    require(category in CATEGORIES, "지원하지 않는 카탈로그 품목")
    attrs = record.get("attributes")
    require(isinstance(attrs, dict) and isinstance(attrs.get("specs", {}), dict),
            "카탈로그 attributes.specs 객체 필요")
    specs = deepcopy(attrs.get("specs", {}))
    # The legacy manual contract needs explicit unknown states.  Existing values
    # are known catalog facts; fields not present in the catalog stay unknown.
    status = {"specs." + key: "known" for key, value in specs.items() if value is not None}
    status.update({"specs." + key: "unknown" for key, value in specs.items() if value is None})
    for key in FIELDS.get(category, {}):
        if key not in specs:
            specs[key] = None
            status["specs." + key] = "unknown"
    components = deepcopy(attrs.get("components", []))
    require(isinstance(components, list), "카탈로그 attributes.components 배열 필요")
    # Generated catalog components are their own references.  This preserves the
    # identifier relation checked by validate_input without creating a claim
    # about compatibility or inclusion that was not in the catalog.
    references = []
    reference_ids = set()

    def collect_reference_ids(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_ids") and item is not None:
                    require(isinstance(item, list), f"참조 배열 필요: {key}")
                    reference_ids.update(item)
                collect_reference_ids(item)
        elif isinstance(value, list):
            for item in value:
                collect_reference_ids(item)

    collect_reference_ids(specs)
    for component in components:
        require(isinstance(component, dict) and component.get("id"), "구성품 ID 필요")
        reference_ids.add(component["id"])
    for reference_id in sorted(reference_ids):
        identifier(reference_id)
        references.append({"id": reference_id, "is_synthetic": True})
    product_key = record.get("product_key")
    variant_key = record.get("variant_key")
    identifier(product_key); identifier(variant_key)
    brand = record.get("brand")
    name = record.get("name")
    plain(brand); plain(name)
    model = name[len(brand):].strip() if name.startswith(brand) else name
    if not model:
        model = product_key
    return ({
        "is_synthetic": True, "market": "KR_DEMO", "simulated_safety_status": "not_evaluated",
        "product_id": product_key, "variant_id": variant_key, "brand": brand, "model": model,
        "category_id": category, "specs": specs, "field_status": status,
        "eligibility": deepcopy(attrs.get("eligibility", [])), "components": components,
        "dataset_meta": {"catalog_dataset_version": manifest.get("dataset_version"),
                         "catalog_records_sha256": manifest.get("records_sha256"),
                         "catalog_product_key": product_key},
    }, references)


def select_product(data, product_id=None, product_key=None):
    require(not (product_id and product_key), "--product-id와 --product-key는 함께 사용할 수 없습니다")
    if "records" in data:
        records = data["records"]
        require(isinstance(records, list), "records는 배열이어야 합니다")
        keys = [record.get("product_key") for record in records]
        require(len(keys) == len(set(keys)), "중복 상품 키")
        selected = [record for record in records if product_key is None or record.get("product_key") == product_key]
        require(len(selected) == 1, "카탈로그에서는 한 건만 선택해야 합니다. --product-key를 지정하세요")
        return _catalog_record_to_product(selected[0], data.get("manifest", {}))
    if "products" not in data:
        require(product_id is None or data.get("product_id") == product_id, "제품 ID 불일치")
        return deepcopy(data), []
    products = data["products"]
    require(isinstance(products, list), "products는 배열이어야 합니다")
    ids = [p["product_id"] for p in products]
    require(len(ids) == len(set(ids)), "중복 상품 ID")
    selected = [p for p in products if product_id is None or p["product_id"] == product_id]
    require(len(selected) == 1, "한 건만 선택해야 합니다. --product-id를 지정하세요")
    return deepcopy(selected[0]), deepcopy(data.get("references", []))


def validate_input(p, refs):
    require(p.get("is_synthetic") is True and p.get("market") == "KR_DEMO", "KR_DEMO 가상제품만 지원합니다")
    require(p.get("simulated_safety_status") == "not_evaluated", "실제 안전 평가로 오인될 상태는 허용하지 않습니다")
    for key in ("product_id", "variant_id"):
        identifier(p.get(key))
    for key in ("brand", "model"):
        plain(p.get(key))
    require(p.get("category_id") in CATEGORIES, "지원하지 않는 품목")
    require(isinstance(p.get("specs"), dict) and isinstance(p.get("field_status"), dict), "스펙·상태 객체 필요")
    require(isinstance(p.get("eligibility"), list) and isinstance(p.get("components"), list), "사용 조건·구성품 배열 필요")
    require(isinstance(refs, list), "references는 배열이어야 합니다")
    index = {}
    for ref in refs:
        rid = identifier(ref.get("id"))
        require(rid not in index and ref.get("is_synthetic") is True, "중복 또는 비가상 참조")
        index[rid] = ref
    for key, value in p["specs"].items():
        status = p["field_status"].get("specs." + key)
        require(status in {"known", "unknown", "not_applicable"}, f"상태 누락 또는 상충: specs.{key}")
        require((status == "known") == (value is not None), f"값과 상태 불일치: {key}")
    def references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_ids") and item is not None:
                    require(isinstance(item, list), f"참조 배열 필요: {key}")
                    for rid in item:
                        require(rid in index, f"참조 없음: {rid}")
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
    references(p["specs"])
    for c in p["components"]:
        require(c.get("id") in index, f"구성품 참조 없음: {c.get('id')}")
        require(type(c.get("included")) is bool and isinstance(c.get("required_for_modes"), list), "구성품 계약 오류")
    modes = [e.get("mode") for e in p["eligibility"]]
    require(all(isinstance(e, dict) and isinstance(e.get("mode"), str) for e in p["eligibility"]), "사용 조건 모드 필요")
    require(len(modes) == len(set(modes)), "중복 사용 모드")
    for c in p["components"]:
        require(set(c["required_for_modes"]) <= set(modes), "구성품의 미등록 모드")
    if p["category_id"] not in SPECIALIZED_CATEGORIES:
        # For categories without a reviewed instruction template, retain the
        # complete structured condition as a catalog fact rather than translating
        # it into a possibly unsafe natural-language instruction.
        return index
    require(all(m in MODES for m in modes), "미지원 사용 모드")
    allowed = {"mode", "requires", "stop_when_any"} | {
        prefix + axis for prefix in ("min_", "max_") for axis in ("age_months", "weight_kg", "height_cm")}
    for e in p["eligibility"]:
        require(set(e) <= allowed, "알 수 없는 사용 조건; 조건을 생략하지 않고 생성 중단")
        for axis in ("age_months", "weight_kg", "height_cm"):
            lo, hi = e.get("min_" + axis), e.get("max_" + axis)
            for value in (lo, hi):
                if value is not None:
                    number(value)
            require(lo is None or hi is None or lo <= hi, "최소값이 최대값보다 큼")
        require(isinstance(e.get("requires", []), list) and isinstance(e.get("stop_when_any", []), list), "조건 배열 필요")
        require(all(x in DEVELOPMENT for x in e.get("requires", [])), "미등록 발달 조건")
        for stop in e.get("stop_when_any", []):
            match = re.fullmatch(r"weight_over_(\d+(?:\.\d+)?)kg", stop)
            require(match is not None, "미등록 중단 조건")
            require(e.get("max_weight_kg") == float(match[1]), "상한과 중단 조건 불일치")
    if p["category_id"] == "stroller":
        require(modes == ["seat"], "유모차 좌석 모드만 지원")
        require(p["specs"].get("seat_max_kg") == p["eligibility"][0].get("max_weight_kg"), "좌석 하중·사용 범위 불일치")
    return index


def catalog_value(value):
    """A literal display form for untemplated catalog facts, never an instruction."""
    if value is None:
        return "미확인"
    if isinstance(value, str):
        return plain(value)
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return number(value)
    # JSON is deterministic and labels a value as a catalog record, so nested
    # dimensions/ranges are not paraphrased as operating or safety guidance.
    return canonical(value).replace("|", "\\|")


def build_manual(product, references=None, profile=None, revision="R1"):
    """Return one deterministic artifact bundle; never modifies caller inputs."""
    p, refs = deepcopy(product), deepcopy(references or [])
    index = validate_input(p, refs)
    identifier(revision)
    facts, blocks, rendered = [], [], {key: [] for key in SECTIONS}
    covered = set()

    def add(section, text, path, value, unit="", operator="eq", subject=None, origin="catalog"):
        fid = f"F{len(facts)+1:04d}"
        bid = f"{section}-B{len(rendered[section])+1:03d}"
        facts.append({"fact_id": fid, "subject": subject or p["product_id"], "predicate": path,
                      "value": value, "unit": unit, "operator": operator, "status": "unknown" if value is None else "known",
                      "origin_kind": origin, "origin_ref": path})
        block = {"block_id": bid, "section": section, "text": text, "fact_ids": [fid]}
        blocks.append(block)
        rendered[section].append(block)

    if p["category_id"] in SPECIALIZED_CATEGORIES:
        for i, e in enumerate(p["eligibility"]):
            mode = MODES[e["mode"]]
            for key, value in e.items():
                path = f"/eligibility/{i}/{key}"
                if key == "mode":
                    continue
                if key == "requires":
                    for j, condition in enumerate(value):
                        add("S01", f"{mode} 모드 필수 조건: {DEVELOPMENT[condition]}.", path + f"/{j}", condition, subject=e["mode"])
                elif key == "stop_when_any":
                    for j, stop in enumerate(value):
                        threshold = float(re.fullmatch(r"weight_over_(\d+(?:\.\d+)?)kg", stop)[1])
                        add("S06", f"체중이 {number(threshold)} kg을 초과하면 {mode} 모드 사용을 중단하는 조건입니다.",
                            path + f"/{j}", threshold, "kg", "gt", e["mode"])
                else:
                    axis = key[4:]
                    label, unit = {"age_months": ("월령", "개월"), "weight_kg": ("체중", "kg"), "height_cm": ("키", "cm")}[axis]
                    comparison = "이상" if key.startswith("min_") else "이하"
                    text = f"{mode} 모드 {label}: 미확인." if value is None else f"{mode} 모드 {label}: {number(value)} {unit} {comparison}."
                    add("S01", text, path, value, unit, "gte" if key.startswith("min_") else "lte", e["mode"])
            for c in p["components"]:
                if e["mode"] in c["required_for_modes"]:
                    add("S01", f"{mode} 모드 필수 부품: {plain(c['id'])}.", "/components", c, subject=e["mode"])
        if p["eligibility"]:
            add("S01", "같은 모드에 적힌 사용 조건은 모두 충족해야 합니다.", "/eligibility", p["eligibility"])
    else:
        for i, condition in enumerate(p["eligibility"]):
            mode = plain(condition["mode"])
            add("S01", f"{mode} 모드 카탈로그 등록 조건: {catalog_value(condition)}. 이 기록만으로 사용 절차를 추정하지 않습니다.",
                f"/eligibility/{i}", condition, subject=condition["mode"])
    for key, (section, label, unit, kind) in FIELDS.get(p["category_id"], {}).items():
        path = "specs." + key
        status = p["field_status"].get(path, "unknown")
        value = p["specs"].get(key)
        if status == "not_applicable":
            continue
        if status == "unknown":
            add(section, f"{label}: 미확인.", "/specs/" + key, None)
            continue
        if kind == "bool":
            require(type(value) is bool, f"boolean 필요: {key}")
            result = "지원합니다" if value else "지원하지 않습니다"
        elif kind == "dimensions":
            require(isinstance(value, dict) and set(value) == {"width", "depth", "height"}, "치수 축 오류")
            result = " × ".join(number(value[x]) for x in ("width", "depth", "height")) + " " + unit
        elif kind == "newborn":
            require(value == "not_supported", "신생아 구성은 별도 프로필 구현 필요")
            result = "지원하지 않습니다"
        else:
            if kind == "integer":
                require(type(value) is int, f"정수 필요: {key}")
            result = number(value) + " " + unit
        add(section, f"{label}: {result}.", "/specs/" + key, value, unit)
    if p["category_id"] not in SPECIALIZED_CATEGORIES:
        for key in sorted(p["specs"]):
            value = p["specs"][key]
            add("S07", f"카탈로그 등록 스펙 {plain(key)}: {catalog_value(value)}.", "/specs/" + key, value)
    for i, c in enumerate(p["components"]):
        add("S02", f"{plain(c['id'])}: {'포함' if c['included'] else '별매'}.", f"/components/{i}", c)
    if not p["components"]:
        add("S02", "추가 구성품으로 등록된 항목이 없습니다. 내장 부품의 전체 목록을 뜻하지 않습니다.", "/components", [])
    for key in ("compatible_adapter_ids", "compatible_nipple_ids", "compatible_lid_ids"):
        if key in p["specs"] and p["field_status"].get("specs." + key) == "known":
            values = p["specs"][key]
            add("S07", "등록된 호환 부품: " + (", ".join(plain(v) for v in values) if values else "없음") + ". 미등록 조합의 호환 여부는 미확인입니다.", "/specs/" + key, values)
    care = p["specs"].get("care_by_component")
    if care is not None:
        require(isinstance(care, list), "부품별 관리 배열 필요")
        for i, entry in enumerate(care):
            require(set(entry) == {"component", "methods"} and isinstance(entry["methods"], list), "미지원 관리 조건")
            require(all(m in METHODS for m in entry["methods"]), "미등록 관리법")
            add("S08", f"{plain(entry['component'])}에 등록된 관리 방법: " + (", ".join(METHODS[m] for m in entry["methods"]) or "없음") + ". 다른 방법의 허용 여부·온도·시간은 이 정보만으로 확정하지 않습니다.", f"/specs/care_by_component/{i}", entry)

    # Optional reviewed linear procedure profile. No free-form generated instructions.
    if profile is not None:
        require(profile.get("is_synthetic") is True and profile.get("review_status") == "reviewed", "검수된 가상 프로필 필요")
        identifier(profile.get("profile_id")); identifier(profile.get("version"))
        require(profile.get("category_id") == p["category_id"], "프로필 품목 불일치")
        require(profile.get("product_id") == p["product_id"], "프로필 제품 불일치")
        require(profile.get("product_sha256") == digest(canonical(p)), "프로필은 현재 제품 해시에 고정되어야 합니다")
        require(isinstance(profile.get("procedures"), list) and profile["procedures"], "절차 목록 필요")
        seen = set()
        for procedure in profile["procedures"]:
            section = procedure["section"]
            require(section in {"S03", "S04", "S05", "S08", "S09", "S10"} and section not in seen, "중복 또는 미지원 절차 절")
            seen.add(section)
            state, states = procedure["initial_state"], set(procedure["states"])
            require(state in states and procedure["terminal_state"] in states and procedure["steps"], "절차 상태 오류")
            visited = {state}
            for step in procedure["steps"]:
                require(step["requires_state"] == state and step["resulting_state"] in states, "도달 불가능한 절차")
                require(set(step["required_parts"]) <= set(index), "절차 부품 참조 없음")
                state = step["resulting_state"]
                require(state not in visited, "순환 절차는 지원하지 않습니다")
                visited.add(state)
                # Each step is a reviewed atomic assertion; retain complete source.
                text = f"{plain(step['action'])} 확인: {plain(step['confirmation'])} 실패 시: {plain(step['on_failure'])}"
                require(isinstance(step["warnings"], list), "경고 배열 필요")
                for warning in step["warnings"]:
                    text += " 주의: " + plain(warning)
                add(section, text, f"{profile['profile_id']}@{profile['version']}/{section}/{len(rendered[section])}", step, origin="profile")
            require(state == procedure["terminal_state"], "완료 상태 미도달")
            covered.add(section)

    # Catalog facts alone do not define a full manual; no unsupported completeness claim.
    section_status = {s: ("complete" if s in covered else "partial" if rendered[s] else "missing") for s in SECTIONS}
    missing = [s for s, status in section_status.items() if status != "complete"]
    mid = "SYN-MAN-" + p["product_id"]
    text = (f"# {CATEGORIES[p['category_id']]} 사용설명서 · {plain(p['model'])}\n\n"
            f"**{NOTICE}**\n\n"
            f"{plain(p['brand'])} · {plain(p['product_id'])} · {plain(p['variant_id'])} · KR_DEMO\n\n"
            f"문서: {mid} / {revision} · 부분 설명서 · 실제 안전 평가: 미평가\n\n")
    for section, title in SECTIONS.items():
        if not rendered[section]:
            continue
        text += f"## {title}\n\n"
        for block in rendered[section]:
            text += f"<!-- {block['block_id']} -->\n"
            start = len(text)
            text += block["text"]
            block["locator"] = {"char_start": start, "char_end": len(text), "section": section,
                                "line_start": text[:start].count("\n") + 1}
            text += "\n\n"
    text += "## 문서에 정의되지 않은 범위\n\n"
    text += "다음 절은 전체 절차·조건이 완성되지 않았습니다: " + ", ".join(SECTIONS[s] for s in missing) + ".\n\n"
    text += "지원되는 기능만으로 조작 순서나 관리 방법을 추정하지 않습니다. 이 문서는 가상 테스트 자료이며 실제 제조사 지원·인증 정보를 제공하지 않습니다.\n"
    artifact = {
        "manual": text, "facts": facts, "product": p, "references": refs, "profile": deepcopy(profile),
        "mapping": {"manual_id": mid, "revision": revision, "product_id": p["product_id"], "variant_id": p["variant_id"],
                    "is_synthetic": True, "market": "KR_DEMO", "coverage_status": "partial", "section_status": section_status,
                    "missing_sections": missing, "manual_sha256": digest(text), "blocks": blocks},
        "manifest": {"generator_version": VERSION, "template_version": VERSION, "is_synthetic": True,
                     "product_sha256": digest(canonical(p)), "references_sha256": digest(canonical(refs)),
                     "profile_sha256": digest(canonical(profile)), "manual_count": 1,
                     "dataset_meta": deepcopy(p.get("dataset_meta", {})), "llm_used": False},
    }
    validate_artifact(artifact)
    return artifact


def validate_artifact(artifact):
    text, mapping = artifact["manual"], artifact["mapping"]
    require(NOTICE in text and digest(text) == mapping["manual_sha256"], "설명서 해시·가상 표시 불일치")
    facts = {f["fact_id"] for f in artifact["facts"]}
    require(len(facts) == len(artifact["facts"]), "중복 사실 ID")
    for b in mapping["blocks"]:
        loc = b["locator"]
        require(text[loc["char_start"]:loc["char_end"]] == b["text"], "본문과 근거 위치 불일치")
        require(b["fact_ids"] and set(b["fact_ids"]) <= facts, "존재하지 않는 근거 ID")


def write_artifact(artifact, output):
    """Publish a single bundle by rename; never overwrite existing output."""
    validate_artifact(artifact)
    output = Path(output).resolve()
    require(not output.exists(), f"출력 경로가 이미 존재합니다: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".manual-", dir=output.parent))
    try:
        (stage / "manual.md").write_text(artifact["manual"], encoding="utf-8", newline="\n")
        files = {"mapping.json": artifact["mapping"], "product.snapshot.json": artifact["product"],
                 "references.snapshot.json": artifact["references"], "profile.snapshot.json": artifact["profile"],
                 "validation.json": {"status": "passed", "scope": "deterministic data consistency; not product safety",
                                     "coverage_status": "partial", "manual_sha256": artifact["mapping"]["manual_sha256"]}}
        for name, value in files.items():
            (stage / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        (stage / "facts.jsonl").write_text("".join(canonical(f) + "\n" for f in artifact["facts"]), encoding="utf-8", newline="\n")
        manifest = deepcopy(artifact["manifest"])
        manifest["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.iterdir())}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        stage.rename(output)
    finally:
        if stage.exists():
            # Only our newly allocated staging directory, never caller's output.
            shutil.rmtree(stage)


def publish_bundle(bundle: Path, *, provider_name: str, reviewed: bool) -> dict:
    """Publish a completed bundle to the configured search provider and DB.

    The generated Markdown remains the immutable source bundle.  PostgreSQL stores
    its material/file/revision/applicability metadata; the provider stores chunks.
    ``reviewed`` is an operator attestation, never inferred from generator checks.
    """
    # Keep imports here: generation without --publish remains stdlib-only and can
    # run in an offline environment without database/search dependencies.
    import psycopg

    from src.config import DATABASE_URL
    from src.rag.ingestion import ingest_manual
    from src.rag.provider import get_search_provider
    from src.repo.material_repo import MaterialRepo

    os.environ["BABY_SEARCH_PROVIDER"] = provider_name
    provider = get_search_provider()
    if provider is None:
        raise ManualError("검색 제공자를 초기화할 수 없습니다")
    with psycopg.connect(DATABASE_URL, connect_timeout=5, prepare_threshold=None) as conn:
        return ingest_manual(bundle, MaterialRepo(conn), provider, reviewed=reviewed)


def generate_catalog_batch(data: dict, output: Path, *, publish: bool, provider_name: str,
                           reviewed: bool, revision: str) -> list[dict]:
    """Generate one partial manual per seed-catalog record, then optionally publish.

    All artifacts are validated in a staging directory before it becomes the output
    directory.  An external provider cannot share a transaction with PostgreSQL;
    if a later publication fails, the completed local bundles remain available for
    diagnosis and retry while the returned error identifies the failed product.
    """
    records = data.get("records")
    require(isinstance(records, list) and records, "records가 있는 카탈로그 입력 필요")
    require(not output.exists(), f"출력 경로가 이미 존재합니다: {output}")
    identifier(revision)
    artifacts = []
    for record in records:
        product, refs = _catalog_record_to_product(record, data.get("manifest", {}))
        artifacts.append((product["product_id"], build_manual(product, refs, revision=revision)))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".manual-batch-", dir=output.parent))
    try:
        for product_key, artifact in artifacts:
            write_artifact(artifact, stage / product_key)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    report = []
    for product_key, _ in artifacts:
        published = publish_bundle(output / product_key, provider_name=provider_name, reviewed=reviewed) if publish else None
        report.append({"product_key": product_key, "bundle": str(output / product_key), "published": published})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--product-id")
    parser.add_argument("--product-key", help="records[] 카탈로그 입력의 product_key")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--revision", default="R1")
    parser.add_argument("--publish", "--ingest", dest="publish", action="store_true",
                        help="생성 후 DB 메타데이터와 검색 제공자에 발행")
    parser.add_argument("--provider", choices=["local-file"], default="local-file",
                        help="--publish 시 사용할 검색 제공자")
    parser.add_argument("--reviewed", action="store_true",
                        help="사람이 본문 사실을 검수했음을 명시적으로 확인")
    parser.add_argument("--all-catalog-records", action="store_true",
                        help="records[] 카탈로그의 모든 상품 설명서를 생성한다")
    args = parser.parse_args(argv)
    try:
        data = read_json(args.input)
        if args.all_catalog_records:
            require(not args.product_id and not args.product_key and args.profile is None,
                    "--all-catalog-records는 상품 선택·프로필 옵션과 함께 사용할 수 없습니다")
            report = generate_catalog_batch(data, args.output, publish=args.publish,
                                            provider_name=args.provider, reviewed=args.reviewed,
                                            revision=args.revision)
            print(json.dumps({"generated": len(report), "published": sum(r["published"] is not None for r in report),
                              "output": str(args.output)}, ensure_ascii=False))
            return 0
        product, refs = select_product(data, args.product_id, args.product_key)
        artifact = build_manual(product, refs, read_json(args.profile) if args.profile else None, args.revision)
        write_artifact(artifact, args.output)
        published = publish_bundle(args.output, provider_name=args.provider, reviewed=args.reviewed) if args.publish else None
    except (ManualError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"생성 실패: {error}\n")
    print(f"설명서 1건 생성: {args.output / 'manual.md'} (partial)")
    if published is not None:
        print(json.dumps({"published": published, "reviewed": args.reviewed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
