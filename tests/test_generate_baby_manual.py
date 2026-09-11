"""Behavior tests for synthetic manual generation (stdlib unittest)."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_baby_manual import (
    ManualError, build_manual, canonical, digest, read_json, select_product,
    validate_artifact, write_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.p = read_json(ROOT / "data/synthetic_manuals/stroller_example.json")

    def test_sample_reproducible_and_no_fabricated_procedure(self):
        original = deepcopy(self.p)
        a = build_manual(self.p)
        self.assertEqual(a, build_manual(self.p))
        self.assertEqual(self.p, original)
        self.assertIn("22 kg 이하", a["manual"])
        self.assertIn("22 kg을 초과", a["manual"])
        self.assertIn("자립 기능: 지원하지 않습니다", a["manual"])
        self.assertNotIn("버튼을", a["manual"])
        self.assertNotIn("290000", a["manual"])
        self.assertEqual(a["mapping"]["coverage_status"], "partial")
        self.assertIn("S05", a["mapping"]["missing_sections"])

    def test_inconsistent_repeated_limit_rejected(self):
        self.p["specs"]["seat_max_kg"] = 25
        with self.assertRaises(ManualError):
            build_manual(self.p)

    def test_inconsistent_stop_rejected(self):
        self.p["eligibility"][0]["stop_when_any"] = ["weight_over_21kg"]
        with self.assertRaises(ManualError):
            build_manual(self.p)

    def test_unknown_is_not_false(self):
        self.p["specs"]["one_hand_fold"] = None
        self.p["field_status"]["specs.one_hand_fold"] = "unknown"
        a = build_manual(self.p)
        self.assertIn("한 손 접기 기능: 미확인", a["manual"])
        self.assertNotIn("한 손 접기 기능: 지원하지", a["manual"])

    def test_conflict_and_bad_status_rejected(self):
        for status in ("conflicting", "unknown", "not_applicable"):
            with self.subTest(status=status):
                p = deepcopy(self.p)
                p["field_status"]["specs.one_hand_fold"] = status
                with self.assertRaises(ManualError):
                    build_manual(p)

    def test_unknown_condition_not_silently_dropped(self):
        self.p["eligibility"][0]["requires"] = ["unregistered_condition"]
        with self.assertRaises(ManualError):
            build_manual(self.p)

    def test_reference_and_real_product_rejected(self):
        p = deepcopy(self.p)
        p["specs"]["compatible_adapter_ids"] = ["MISSING"]
        with self.assertRaises(ManualError):
            build_manual(p)
        self.p["is_synthetic"] = False
        with self.assertRaises(ManualError):
            build_manual(self.p)

    def test_bundle_requires_one_selection(self):
        second = deepcopy(self.p)
        second["product_id"] = "SYN-STROLLER-002"
        bundle = {"products": [self.p, second], "references": []}
        with self.assertRaises(ManualError):
            select_product(bundle)
        selected, refs = select_product(bundle, second["product_id"])
        self.assertEqual(selected["product_id"], second["product_id"])
        self.assertEqual(refs, [])

    def test_mapping_and_tamper_detection(self):
        a = build_manual(self.p)
        for block in a["mapping"]["blocks"]:
            loc = block["locator"]
            self.assertEqual(a["manual"][loc["char_start"]:loc["char_end"]], block["text"])
        a["manual"] = a["manual"].replace("22 kg", "25 kg")
        with self.assertRaises(ManualError):
            validate_artifact(a)

    def test_profile_is_product_bound_and_state_checked(self):
        profile = {
            "profile_id": "SYN-PROFILE", "version": "V1", "is_synthetic": True,
            "review_status": "reviewed", "category_id": "stroller",
            "product_id": self.p["product_id"], "product_sha256": digest(canonical(self.p)),
            "procedures": [{"section": "S10", "initial_state": "A", "terminal_state": "B",
                            "states": ["A", "B"], "steps": [{"requires_state": "A", "resulting_state": "B",
                            "required_parts": [], "action": "가상 보관 점검.", "confirmation": "점검 완료.",
                            "on_failure": "점검 중단.", "warnings": ["가상 절차."]}]}],
        }
        a = build_manual(self.p, profile=profile)
        self.assertEqual(a["mapping"]["section_status"]["S10"], "complete")
        profile["procedures"][0]["steps"][0]["requires_state"] = "B"
        with self.assertRaises(ManualError):
            build_manual(self.p, profile=profile)
        profile["product_sha256"] = "wrong"
        with self.assertRaises(ManualError):
            build_manual(self.p, profile=profile)

    def test_atomic_single_document_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "example"
            a = build_manual(self.p)
            write_artifact(a, out)
            self.assertEqual(len(list(out.glob("*.md"))), 1)
            self.assertEqual((out / "manual.md").read_text(encoding="utf-8"), a["manual"])
            manifest = read_json(out / "manifest.json")
            import hashlib
            for name, sha in manifest["files"].items():
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), sha)
            with self.assertRaises(ManualError):
                write_artifact(a, out)

    def test_bottle_component_care_is_not_generalized(self):
        p = deepcopy(self.p)
        p.update(category_id="bottle", eligibility=[], components=[],
                 specs={"capacity_ml": 260, "pack_count": 1,
                        "care_by_component": [{"component": "병", "methods": ["steam"]},
                                              {"component": "젖꼭지", "methods": ["hand_wash"]}]})
        p["field_status"] = {"specs." + k: "known" for k in p["specs"]}
        text = build_manual(p)["manual"]
        self.assertIn("병에 등록된 관리 방법: 스팀 소독", text)
        self.assertIn("젖꼭지에 등록된 관리 방법: 손세척", text)
        self.assertNotIn("젖꼭지에 등록된 관리 방법: 스팀", text)


if __name__ == "__main__":
    unittest.main()
