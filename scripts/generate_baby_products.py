"""Generate reproducible, explicitly synthetic baby-product catalogues (stdlib only).

Usage:
    python generate_baby_products.py --count 100 --seed 42
    python generate_baby_products.py --categories stroller,bottle --count 20

The adjacent Korean JSON file is a data dictionary, NOT a JSON Schema.
Values below are demo profiles, not certified limits or care/feeding guidance.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys


VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent
DEFAULT_DICTIONARY = ROOT / "유아용품_가상제품_스펙사전_v1.json"
DEFAULT_OUTPUT = ROOT / "generated" / "baby_products.json"
# Synthetic price bands in KRW, deliberately not market estimates.
PRICE_BANDS = {
    "stroller": (180000, 900000), "car_seat": (150000, 700000),
    "carrier": (60000, 250000), "crib": (150000, 700000),
    "sleepwear": (20000, 70000), "bouncer": (80000, 250000),
    "high_chair": (80000, 400000), "bottle": (10000, 50000),
    "pump": (30000, 300000), "sterilizer": (100000, 300000),
    "formula_maker": (60000, 350000), "formula": (15000, 50000),
    "baby_food": (2000, 7000), "cup": (10000, 30000),
    "bib": (5000, 25000), "diaper": (15000, 40000),
    "wipes": (2000, 6000), "bath": (25000, 100000),
    "skincare": (10000, 40000), "thermometer": (20000, 100000),
    "pacifier": (5000, 20000), "gate": (40000, 200000),
    "mat": (50000, 300000),
}


class DataError(ValueError):
    """Dictionary, generated data, or reference integrity error."""


def load_dictionary(path: Path = DEFAULT_DICTIONARY) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    categories = data.get("categories", [])
    ids = [c["id"] for c in categories]
    if len(ids) != len(set(ids)) or set(ids) != set(PRICE_BANDS):
        raise DataError("Dictionary must contain the 23 supported category IDs exactly once")
    for category in categories:
        keys = [f["key"] for f in category["fields"]]
        if len(keys) != len(set(keys)):
            raise DataError(f"Duplicate field in {category['id']}")
        for field in category["fields"]:
            if field["type"] not in {"number", "integer", "boolean", "string", "array", "object"}:
                raise DataError(f"Unsupported field type: {field['key']}")
    return data


def sample_field(field: dict, rng: random.Random):
    values = field["synthetic_examples"]
    # Array examples describe the WHOLE array; object examples are candidate objects.
    if field["type"] == "array":
        return deepcopy(values)
    if not values:
        raise DataError(f"Empty candidate list: {field['key']}")
    return deepcopy(rng.choice(values))


class References:
    def __init__(self):
        self.records: dict[str, dict] = {}

    def add(self, product_id: str, name: str, kind: str, **data) -> str:
        ref_id = f"{product_id}-{name.upper()}"
        record = {"id": ref_id, "kind": kind, "is_synthetic": True, **deepcopy(data)}
        if ref_id in self.records and self.records[ref_id] != record:
            raise DataError(f"Conflicting reference: {ref_id}")
        self.records[ref_id] = record
        return ref_id


def apply_profile(category: str, s: dict, rng: random.Random, refs: References,
                  product_id: str) -> tuple[list, list, str]:
    """Override correlated fields together. Leave only independent preferences sampled."""
    components: list[dict] = []
    eligibility: list[dict] = []
    profile = category

    def ref(name, kind, **data):
        return refs.add(product_id, name, kind, **data)

    def component(name, kind, included=True, required_for_modes=(), price_krw=0, **data):
        key = ref(name, kind, price_krw=price_krw, **data)
        components.append({"id": key, "included": included,
                           "required_for_modes": list(required_for_modes)})
        return key

    if category == "stroller":
        compact = rng.choice([True, False])
        s.update(type="compact" if compact else "standard",
                 assembled_weight_kg=rng.choice([6.5, 7.2]) if compact else rng.choice([10.5, 12.5]),
                 folded_cm={"width": 45, "depth": 25, "height": 55} if compact else
                           {"width": 60, "depth": 45, "height": 85},
                 unfolded_cm={"width": 55, "depth": 85, "height": 105} if compact else
                             {"width": 60, "depth": 95, "height": 110},
                 seat_max_kg=22, newborn_setup="not_supported", compatible_adapter_ids=[])
        eligibility = [{"mode": "seat", "min_age_months": 6, "max_weight_kg": 22,
                        "requires": ["independent_sitting"], "stop_when_any": ["weight_over_22kg"]}]
        profile += "_compact" if compact else "_standard"
    elif category == "car_seat":
        infant = rng.choice([True, False])
        s.update(seat_type="infant" if infant else "convertible", installation="isofix",
                 required_anchors=["support_leg"], weight_kg=4.5 if infant else 13,
                 rotation=False if infant else s["rotation"], newborn_insert_included=True)
        s["mode_limits"] = [{"mode": "rear_facing", "min_height_cm": 40,
                             "max_height_cm": 83 if infant else 105,
                             "max_weight_kg": 13 if infant else 19}]
        seat = ref("vehicle-seat", "vehicle_seat", vehicle_model="가상차량_A",
                   model_year=2025, position="rear_right", anchors=["isofix", "support_leg"])
        s["compatible_vehicle_seat_ids"] = [seat]
        component("support-leg", "anchor", required_for_modes=["rear_facing"])
        component("newborn-insert", "insert", required_for_modes=["rear_facing"])
        eligibility = deepcopy(s["mode_limits"])
        profile += "_infant" if infant else "_convertible"
    elif category == "carrier":
        # Deliberately scoped to structured carriers: no fabricated newborn hipseat use.
        s.update(type="structured", min_weight_kg=3.5, max_weight_kg=20,
                 position_rules=[{"position": "front_inward", "min_weight_kg": 3.5,
                                  "max_weight_kg": 20, "requires_head_control": False}])
        eligibility = [{"mode": "front_inward", "min_weight_kg": 3.5, "max_weight_kg": 20}]
    elif category == "crib":
        s.update(type="crib", outer_cm={"width": 65, "depth": 125, "height": 90},
                 mattress_cm={"width": 60, "length": 120, "thickness": 6},
                 base_height_levels=2,
                 mode_stop_conditions=[{"mode": "highest_base", "stop_when": "attempts_to_sit"},
                                       {"mode": "lowest_base", "stop_when": "climbs_out"}])
        mattress = component("mattress", "mattress", included=s["mattress_included"],
                             required_for_modes=["highest_base", "lowest_base"],
                             price_krw=60000, dimensions_cm=s["mattress_cm"])
        s["compatible_mattress_ids"] = [mattress]
        eligibility = [{"mode": x["mode"], "stop_when_any": [x["stop_when"]]}
                       for x in s["mode_stop_conditions"]]
    elif category == "sleepwear":
        swaddle = s["type"] == "swaddle"
        s.update(arms_restrained=swaddle,
                 height_range_cm={"min": 50, "max": 60} if swaddle else {"min": 60, "max": 75},
                 weight_range_kg={"min": 3.5, "max": 6} if swaddle else {"min": 6, "max": 9},
                 stop_conditions=["signs_of_rolling"] if swaddle else [])
        eligibility = [{"mode": s["type"], "min_height_cm": s["height_range_cm"]["min"],
                        "max_height_cm": s["height_range_cm"]["max"],
                        "min_weight_kg": s["weight_range_kg"]["min"],
                        "max_weight_kg": s["weight_range_kg"]["max"],
                        "stop_when_any": s["stop_conditions"]}]
    elif category == "bouncer":
        s.update(intended_for_sleep=False, harness=True,
                 mode_limits=[{"mode": "bouncer", "min_weight_kg": 3.5,
                               "max_weight_kg": 9, "stop_when": "attempts_to_sit"}],
                 power_sources=[] if s["drive"] == "manual" else ["mains"])
        eligibility = [{"mode": "bouncer", "min_weight_kg": 3.5, "max_weight_kg": 9,
                        "stop_when_any": ["attempts_to_sit"]}]
    elif category == "high_chair":
        s["harness_included"] = True
        baby_set = component("baby-set", "seat_set", included=rng.choice([True, False]),
                             required_for_modes=["high_chair"], price_krw=45000)
        s["required_set_ids"] = [baby_set]
        eligibility = deepcopy(s["mode_limits"])
    elif category == "bottle":
        neck = ref("neck", "connector", system="demo_wide_v1")
        s["neck_system_id"] = neck
        nipple = component("nipple", "nipple", connector_id=neck, flow_grade=s["flow_grade"],
                           material=s["nipple_material"])
        s["compatible_nipple_ids"] = [nipple]
        # Care is explicitly a synthetic per-component profile, not inferred from material.
        s["care_by_component"] = [{"component": "bottle", "methods": ["hand_wash"]},
                                  {"component": "nipple", "methods": ["hand_wash"]}]
    elif category == "pump":
        manual = s["drive"] == "manual"
        s.update(sides="single" if manual else "double", included_flange_mm=[21, 24],
                 available_flange_mm=[21, 24, 27])
        if manual:
            s.update(suction_levels=None, battery_runtime_min=None)
        connector = ref("connector", "connector", system="demo_pump_v1")
        s["connector_system_id"] = connector
        for size in s["available_flange_mm"]:
            component(f"flange-{size}", "flange", included=size in s["included_flange_mm"],
                      price_krw=15000, diameter_mm=size, connector_id=connector)
    elif category == "sterilizer":
        steam = s["sterilization_method"] == "steam"
        s.update(functions=["sterilize", "dry"], cycle_minutes=40 if steam else 60,
                 capacity_reference=f"가상 240mL 젖병 {s['bottle_capacity']}개 배치 기준",
                 filter_replacement_days=None if steam else 180)
        s["supported_care_profile_ids"] = [ref("care", "care_profile",
                                               methods=[s["sterilization_method"]],
                                               validation_scope="simulation_only")]
    elif category == "formula_maker":
        mixer = s["type"] == "automatic_mixer"
        s.update(boils_water=not mixer, clean_after_bottles=4 if mixer else None,
                 formula_settings=None)
        if mixer:
            formula = ref("compatible-formula", "formula_profile", stage="demo_1",
                          preparation_guidance_available=False)
            s["formula_settings"] = [{"formula_id": formula, "setting": "DEMO-A"}]
    elif category == "formula":
        powder = s["form"] == "powder"
        s.update(net_quantity=800 if powder else 200, quantity_unit="g" if powder else "mL",
                 ingredients=["우유 유래 성분", "유당"], allergens=["milk"],
                 use_within_days_after_open=21 if powder else 1,
                 preparation_profile_id=ref("preparation", "preparation_profile",
                                            form=s["form"], reviewed_for_real_use=False,
                                            water_ml=None, powder_g=None,
                                            note="조유 비율은 제공하지 않는 가상 프로필"))
    elif category == "baby_food":
        storage, days, hours, package = rng.choice([
            ("chilled", 7, 24, "cup"), ("frozen", 30, 24, "cup"),
            ("ambient", 180, 24, "pouch")])
        s.update(storage=storage, shelf_life_days=days, after_open_hours=hours,
                 package_type=package, ingredients=["쌀", "당근", "닭고기"], allergens=[])
    elif category == "cup":
        opened = s["drinking_type"] == "open"
        has_straw = s["drinking_type"] in {"weighted_straw", "straw"}
        s["lid_system_id"] = None if opened else ref("lid-system", "connector", version="demo_v2")
        s["compatible_straw_ids"] = [component("straw", "straw", connector_id=s["lid_system_id"])] if has_straw else None
        s.update(care_methods=["hand_wash"], washable_part_count=1 if opened else 4)
    elif category == "bib":
        s["detachable_pocket"] = s["food_pocket"] and s["detachable_pocket"]
        if s["material"] == "silicone":
            s.update(sleeves=False, wash_method="hand")
    elif category == "diaper":
        size, low, high = rng.choice([("S", 4, 8), ("M", 6, 11), ("L", 9, 14)])
        s.update(size_label=f"SYN-{size}", weight_range_kg={"min": low, "max": high},
                 fit_profile_id=ref("fit", "fit_profile", size=size,
                                    weight_range_kg={"min": low, "max": high}))
        eligibility = [{"mode": s["type"], "min_weight_kg": low, "max_weight_kg": high}]
    elif category == "wipes":
        s["intended_use"] = "skin"
        s["ingredients"] = ["water", "glycerin"] + (["fragrance"] if s["fragrance_added"] else [])
    elif category == "bath":
        if not s["foldable"]:
            s["folded_cm"] = None
        support = component("support", "bath_support", included=s["support_included"],
                            required_for_modes=["newborn_support"], price_krw=25000,
                            max_weight_kg=8)
        s.update(support_ids=[support], component_limits=[{"component_id": support, "max_weight_kg": 8}],
                 stand_supported=False)
        eligibility = [{"mode": "newborn_support", "max_weight_kg": 8}]
    elif category == "skincare":
        wash = s["type"] == "wash"
        s.update(rinse_required=wash, body_area="hair_and_body" if wash else "face_and_body",
                 ingredients=["water", "glycerin"] + (["fragrance"] if s["fragrance_added"] else []))
    elif category == "thermometer":
        contact = s["measurement_site"] == "axillary"
        s.update(technology="contact" if contact else "infrared",
                 measurement_seconds=30 if contact else 3, declared_error_c=0.2,
                 disposable_cover_required=s["measurement_site"] == "ear")
        protocol = ref("error-test", "test_profile", test_kind="laboratory_demo",
                       min_c=35, max_c=42, ambient_c=23, declared_error_c=0.2,
                       clinically_validated=False)
        s["error_test_conditions"] = {"min_c": 35, "max_c": 42, "ambient_c": 23, "protocol_id": protocol}
    elif category == "pacifier":
        s.update(vent_holes=True, care_methods=["hand_wash"])
        eligibility = [{"mode": "pacifier", "min_age_months": s["age_months"]["min"],
                        "max_age_months": s["age_months"]["max"]}]
    elif category == "gate":
        gate = s["type"] == "gate"
        s.update(mounting="wall_fixed" if gate else "freestanding",
                 opening_width_cm={"min": 75, "max": 85} if gate else None,
                 inner_cm=None if gate else {"width": 200, "depth": 140},
                 compatible_extension_ids=[], top_of_stairs_supported=False,
                 auto_lock=s["auto_lock"] if gate else False)
    elif category == "mat":
        activity = s["type"] == "activity"
        s.update(size_cm={"width": 150, "length": 100, "thickness": 2} if activity else
                         rng.choice([{"width": 200, "length": 140, "thickness": 4},
                                     {"width": 240, "length": 140, "thickness": 1.2}]),
                 construction="single_sheet" if activity else "folding",
                 surface_material="fabric" if activity else "PU",
                 core_material="fiber" if activity else "PE_foam", wipe_clean=not activity,
                 activity_count=rng.choice([4, 8]) if activity else 0,
                 acoustic_test_profile_id=None)
    else:
        raise DataError(f"No generation profile: {category}")
    return eligibility, components, profile


def generate_dataset(count: int = 100, seed: int = 42, categories: list[str] | None = None,
                     dictionary: dict | None = None) -> dict:
    if type(count) is not int or count < 1:
        raise DataError("count must be a positive integer")
    dictionary = dictionary if dictionary is not None else load_dictionary()
    definitions = {c["id"]: c for c in dictionary["categories"]}
    selected = list(definitions) if categories is None else list(categories)
    if not selected or len(selected) != len(set(selected)) or any(c not in definitions for c in selected):
        raise DataError("Categories must be nonempty, unique, supported IDs")
    rng = random.Random(seed)
    refs = References()
    products = []
    for index in range(count):
        cat = selected[index % len(selected)]
        definition = definitions[cat]
        product_id = f"SYN-{cat.upper().replace('_', '-')}-{index + 1:06d}"
        specs = {f["key"]: sample_field(f, rng) for f in definition["fields"]}
        eligibility, components, profile = apply_profile(cat, specs, rng, refs, product_id)
        low, high = PRICE_BANDS[cat]
        products.append({
            "product_id": product_id, "is_synthetic": True,
            "brand": rng.choice(["가상브랜드_새봄", "가상브랜드_도담", "가상브랜드_모아"]),
            "model": f"SYN-{cat.upper()}-{index + 1:06d}", "category_id": cat,
            "variant_id": f"{product_id}-V1", "market": "KR_DEMO",
            "eligibility": deepcopy(eligibility), "components": deepcopy(components), "specs": specs,
            "field_status": {f"specs.{k}": "known" if v is not None else
                             ("unknown" if k == "acoustic_test_profile_id" else "not_applicable")
                             for k, v in specs.items()},
            "simulated_safety_status": "not_evaluated",
            "offer": {"price_krw": rng.randrange(low, high + 1, 1000),
                      "shipping_krw": rng.choice([0, 3000, 5000]), "stock": rng.randint(0, 30),
                      "lead_time_days": rng.randint(1, 7), "lead_time_basis": "dispatch"},
            "dataset_meta": {"version": VERSION, "seed": seed, "profile_id": profile,
                             "scenario_id": None},
        })
    canonical = json.dumps(dictionary, ensure_ascii=False, sort_keys=True).encode("utf-8")
    bundle = {
        "metadata": {"generator_version": VERSION, "seed": seed, "count": count,
                     "category_counts": dict(Counter(p["category_id"] for p in products)),
                     "dictionary_sha256": hashlib.sha256(canonical).hexdigest(),
                     "is_synthetic": True, "profile_scope": "curated_demo_subset",
                     "notice": "가상 데이터. 실제 상품·안전 인증·조유/보관 지침·시장 통계가 아님.",
                     "scenario_scope": "product_catalog_only; recommendation scenarios not generated"},
        "products": products,
        "references": list(refs.records.values()),
    }
    validate_dataset(bundle, dictionary)
    return bundle


def validate_dataset(bundle: dict, dictionary: dict) -> None:
    """Check supported schema, types, references and the generator's cross-field invariants.

    This is a demo-data integrity validator, not a product safety certification.
    """
    definitions = {c["id"]: c for c in dictionary["categories"]}
    references = {r["id"]: r for r in bundle["references"]}
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    def bounds(value, path):
        if isinstance(value, dict):
            if isinstance(value.get("min"), (int, float)) and isinstance(value.get("max"), (int, float)):
                check(value["min"] <= value["max"], f"{path}: inverted range")
            for key, number in value.items():
                if key.startswith("min_") and "max_" + key[4:] in value:
                    check(number <= value["max_" + key[4:]], f"{path}: inverted {key} range")
                if key in {"width", "height", "depth", "length", "thickness"}:
                    check(type(number) in (int, float) and number > 0, f"{path}.{key}: invalid dimension")
                bounds(number, f"{path}.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                bounds(item, f"{path}[{i}]")

    def pointers(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                if item is not None and (key == "id" or key.endswith("_id")):
                    check(isinstance(item, str) and item in references, f"{path}.{key}: dangling reference {item}")
                elif key.endswith("_ids") and item is not None:
                    check(isinstance(item, list), f"{path}.{key}: expected list")
                    if isinstance(item, list):
                        for ref_id in item:
                            check(ref_id in references, f"{path}.{key}: dangling reference {ref_id}")
                pointers(item, f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                pointers(item, path)

    check(len(references) == len(bundle["references"]), "Duplicate reference IDs")
    products = bundle["products"]
    check(len({p["product_id"] for p in products}) == len(products), "Duplicate product IDs")
    check(len({p["variant_id"] for p in products}) == len(products), "Duplicate variant IDs")
    check(bundle["metadata"]["count"] == len(products), "Count mismatch")
    check(bundle["metadata"]["category_counts"] == dict(Counter(p["category_id"] for p in products)), "Category count mismatch")
    for record in bundle["references"]:
        check(record.get("is_synthetic") is True and record["id"].startswith("SYN-"), "Reference must be synthetic")
        pointers({k: v for k, v in record.items() if k != "id"}, record["id"])
    valid_types = {"number": (int, float), "integer": (int,), "boolean": (bool,),
                   "string": (str,), "array": (list,), "object": (dict,)}
    for p in products:
        pid, cat, s = p["product_id"], p["category_id"], p["specs"]
        check(cat in definitions, f"{pid}: unknown category")
        if cat not in definitions:
            continue
        check(p["is_synthetic"] is True and pid.startswith("SYN-"), f"{pid}: not marked synthetic")
        check(p["simulated_safety_status"] == "not_evaluated", f"{pid}: fabricated safety result")
        check(all(f["key"] in p for f in dictionary["common_fields"] if f["required"]), f"{pid}: missing common field")
        check(set(s) == {f["key"] for f in definitions[cat]["fields"]}, f"{pid}: spec keys differ from dictionary")
        # This generator emits complete profiles, except explicit N/A and unknown acoustics.
        nullable = set()
        if cat == "pump" and s.get("drive") == "manual":
            nullable.update(["suction_levels", "battery_runtime_min"])
        if cat == "sterilizer" and s.get("sterilization_method") == "steam":
            nullable.add("filter_replacement_days")
        if cat == "formula_maker" and s.get("type") == "water_kettle":
            nullable.update(["formula_settings", "clean_after_bottles"])
        if cat == "cup":
            if s.get("drinking_type") == "open":
                nullable.add("lid_system_id")
            if s.get("drinking_type") not in {"straw", "weighted_straw"}:
                nullable.add("compatible_straw_ids")
        if cat == "bath" and s.get("foldable") is False:
            nullable.add("folded_cm")
        if cat == "gate":
            nullable.add("inner_cm" if s.get("type") == "gate" else "opening_width_cm")
        if cat == "mat":
            nullable.add("acoustic_test_profile_id")
        for field in definitions[cat]["fields"]:
            key = field["key"]
            if key not in s:
                continue
            value, status = s[key], p["field_status"].get(f"specs.{key}")
            if value is None:
                check(key in nullable, f"{pid}.{key}: unexpected null in complete profile")
                check(status in {"unknown", "not_applicable"}, f"{pid}.{key}: null with incorrect status")
            else:
                check(status == "known", f"{pid}.{key}: value with incorrect status")
                check(type(value) in valid_types[field["type"]], f"{pid}.{key}: incorrect type")
                if "allowed_values" in field:
                    check(value in field["allowed_values"], f"{pid}.{key}: unsupported enum")
                if type(value) in (int, float):
                    check(value >= 0, f"{pid}.{key}: negative value")
                    if key in {"pack_count", "pieces_per_pack", "sheets_per_pack", "capacity_ml", "net_quantity"}:
                        check(value > 0, f"{pid}.{key}: must be positive")
        bounds(s, pid)
        bounds(p["eligibility"], pid + ".eligibility")
        pointers(s, pid)
        pointers(p["components"], pid + ".components")
        offer = p["offer"]
        for key in ("price_krw", "shipping_krw", "stock", "lead_time_days"):
            check(type(offer[key]) is int and offer[key] >= 0, f"{pid}.{key}: invalid offer")
        check(offer.get("lead_time_basis") == "dispatch", f"{pid}: ambiguous lead time")
        # Validate only type-correct generated records in the category-specific pass.
        try:
            validate_relations(p, references)
        except (DataError, KeyError, TypeError, IndexError) as exc:
            errors.append(f"{pid}: {exc}")
    if errors:
        raise DataError("\n".join(errors))


def validate_relations(p: dict, refs: dict) -> None:
    c, s, e = p["category_id"], p["specs"], p["eligibility"]

    def require(condition, message):
        if not condition:
            raise DataError(message)

    if c == "stroller":
        require(e[0]["max_weight_kg"] == s["seat_max_kg"], "Seat/eligibility weight mismatch")
        require(s["newborn_setup"] == "not_supported" and e[0]["min_age_months"] == 6, "Invalid stroller profile")
    elif c == "car_seat":
        require(e == s["mode_limits"], "Car-seat mode limits differ")
        for seat in s["compatible_vehicle_seat_ids"]:
            anchors = refs[seat]["anchors"]
            require(s["installation"] in anchors and set(s["required_anchors"]) <= set(anchors), "Vehicle anchors incompatible")
    elif c == "carrier":
        require(s["min_weight_kg"] <= s["max_weight_kg"], "Carrier inverted range")
        require(e[0]["min_weight_kg"] == s["min_weight_kg"] and e[0]["max_weight_kg"] == s["max_weight_kg"], "Carrier limits differ")
    elif c == "crib":
        for key in s["compatible_mattress_ids"]:
            require(refs[key]["dimensions_cm"] == s["mattress_cm"], "Mattress dimensions differ")
            item = next(x for x in p["components"] if x["id"] == key)
            require(item["included"] == s["mattress_included"], "Mattress inclusion differs")
    elif c == "sleepwear":
        require(s["arms_restrained"] == (s["type"] == "swaddle"), "Arm restraint/type mismatch")
        require(not s["arms_restrained"] or "signs_of_rolling" in s["stop_conditions"], "Missing swaddle stop condition")
    elif c == "bouncer":
        require(s["intended_for_sleep"] is False and s["harness"] is True, "Invalid bouncer use")
        require(bool(s["power_sources"]) == (s["drive"] == "electric"), "Bouncer power mismatch")
        require(e[0]["max_weight_kg"] == s["mode_limits"][0]["max_weight_kg"], "Bouncer limits differ")
    elif c == "high_chair":
        require(e == s["mode_limits"], "High-chair modes differ")
        require(set(s["required_set_ids"]) <= {x["id"] for x in p["components"]}, "Missing baby set")
    elif c == "bottle":
        for key in s["compatible_nipple_ids"]:
            require(refs[key]["connector_id"] == s["neck_system_id"], "Nipple connector mismatch")
            require(refs[key]["flow_grade"] == s["flow_grade"], "Nipple flow mismatch")
    elif c == "pump":
        require(set(s["included_flange_mm"]) <= set(s["available_flange_mm"]), "Unavailable included flange")
        if s["drive"] == "manual":
            require(s["suction_levels"] is None and s["battery_runtime_min"] is None and s["sides"] == "single", "Manual pump has electric features")
    elif c == "sterilizer":
        require(s["functions"] == ["sterilize", "dry"], "Unsupported sterilizer functions")
        require(str(s["bottle_capacity"]) in s["capacity_reference"], "Capacity description mismatch")
    elif c == "formula_maker":
        if s["type"] == "water_kettle":
            require(s["formula_settings"] is None and s["clean_after_bottles"] is None, "Kettle has powder settings")
    elif c == "formula":
        require(s["quantity_unit"] == ("g" if s["form"] == "powder" else "mL"), "Formula unit mismatch")
        require("milk" in s["allergens"], "Missing milk allergen")
        require(refs[s["preparation_profile_id"]]["water_ml"] is None, "Unexpected feeding recipe")
    elif c == "baby_food":
        require(s["allergens"] == [] and s["ingredients"] == ["쌀", "당근", "닭고기"], "Food label profile mismatch")
        require(s["shelf_life_days"] == {"chilled": 7, "frozen": 30, "ambient": 180}[s["storage"]], "Storage profile mismatch")
    elif c == "cup":
        if s["drinking_type"] == "open":
            require(s["lid_system_id"] is None and s["compatible_straw_ids"] is None, "Open cup has lid/straw")
        for key in s["compatible_straw_ids"] or []:
            require(refs[key]["connector_id"] == s["lid_system_id"], "Straw connector mismatch")
    elif c == "bib":
        require(s["food_pocket"] or not s["detachable_pocket"], "Detachable pocket without pocket")
    elif c == "diaper":
        require(refs[s["fit_profile_id"]]["weight_range_kg"] == s["weight_range_kg"], "Diaper size differs")
        require(e[0]["max_weight_kg"] == s["weight_range_kg"]["max"], "Diaper eligibility differs")
    elif c in {"wipes", "skincare"}:
        require(s["fragrance_added"] == ("fragrance" in s["ingredients"]), "Fragrance label mismatch")
        if c == "skincare":
            require(s["rinse_required"] == (s["type"] == "wash"), "Rinse/type mismatch")
    elif c == "bath":
        require(s["foldable"] or s["folded_cm"] is None, "Rigid bath has folded dimensions")
        for limit in s["component_limits"]:
            require(refs[limit["component_id"]]["max_weight_kg"] == limit["max_weight_kg"], "Bath support limit differs")
    elif c == "thermometer":
        require(s["technology"] == ("contact" if s["measurement_site"] == "axillary" else "infrared"), "Thermometer technology mismatch")
        protocol = refs[s["error_test_conditions"]["protocol_id"]]
        require(s["declared_error_c"] == protocol["declared_error_c"], "Thermometer error differs from test")
    elif c == "pacifier":
        require(e[0]["min_age_months"] == s["age_months"]["min"] and e[0]["max_age_months"] == s["age_months"]["max"], "Pacifier age mismatch")
    elif c == "gate":
        gate = s["type"] == "gate"
        require((s["opening_width_cm"] is not None) == gate and (s["inner_cm"] is None) == gate, "Gate/playpen dimensions mismatch")
        require(not s["top_of_stairs_supported"], "Unsupported stair-use claim")
    elif c == "mat":
        require((s["activity_count"] > 0) == (s["type"] == "activity"), "Mat activity profile mismatch")
        require(s["acoustic_test_profile_id"] is None, "Unexpected acoustic performance claim")


def write_dataset(bundle: dict, path: Path, force: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create by default: never silently destroy an existing catalogue.
    with path.open("w" if force else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(bundle, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100, help="Total products (not per category)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--categories", default="all", help="all or comma-separated category IDs")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="Overwrite the selected output file")
    args = parser.parse_args(argv)
    try:
        dictionary = load_dictionary(args.dictionary)
        selected = None if args.categories == "all" else [c.strip() for c in args.categories.split(",")]
        bundle = generate_dataset(args.count, args.seed, selected, dictionary)
        write_dataset(bundle, args.output, args.force)
    except (DataError, OSError, ValueError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(f"Generated and validated {len(bundle['products'])} synthetic products, "
          f"{len(bundle['references'])} references: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
