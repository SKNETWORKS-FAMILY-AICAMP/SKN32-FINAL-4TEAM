"""P8 RV02/RV03/RV04 — 파일 기반 리뷰 분석 가져오기의 순수 검증(DB 없음).

`scripts.import_review_analysis.validate_and_compute()`는 DB에 닿지 않는다 — 여기서
검증하는 것은 파일 해시·중복 sample_id·라벨 참조·분포 일치 같은, DB 연결 유무와
무관하게 항상 참이어야 하는 규칙이다. DB 적재(subject 해석·review_aggregate 원자 교체)
검증은 tests/test_baby_reviews_http.py(DATABASE_URL 필요)에 있다.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_review_analysis import ReviewAnalysisImportError, validate_and_compute  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "reviews" / "approved_demo" / "manifest.json"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base_rows():
    samples = [
        {"sample_id": "s1", "product_key": "P1", "variant_key": None, "rating": 5,
         "reviewer_id": "r1", "created_at": "2026-01-01T00:00:00+00:00", "text_or_excerpt": "좋아요",
         "text_hash": _hash("s1"), "source_ref": "https://x/1", "is_synthetic": True, "split": "test"},
        {"sample_id": "s2", "product_key": "P1", "variant_key": None, "rating": 5,
         "reviewer_id": "r2", "created_at": "2026-01-02T00:00:00+00:00", "text_or_excerpt": "좋아요2",
         "text_hash": _hash("s2"), "source_ref": "https://x/2", "is_synthetic": True, "split": "test"},
        {"sample_id": "s3", "product_key": "P1", "variant_key": None, "rating": 1,
         "reviewer_id": "r3", "created_at": "2026-01-03T00:00:00+00:00", "text_or_excerpt": "몰림 의심",
         "text_hash": _hash("s3"), "source_ref": "https://x/3", "is_synthetic": True, "split": "test"},
    ]
    labels = [
        {"sample_id": "s1", "label": "retained", "review_status": "approved", "reviewer_ref": "m",
         "method_version": "v1", "observations": [], "confidence": 0.1},
        {"sample_id": "s2", "label": "retained", "review_status": "approved", "reviewer_ref": "m",
         "method_version": "v1", "observations": [], "confidence": 0.1},
        {"sample_id": "s3", "label": "excluded", "review_status": "approved", "reviewer_ref": "m",
         "method_version": "v1", "observations": ["burst7", "prolific_rate"], "confidence": 0.9},
    ]
    analysis = [
        {"subject_key": "P1", "variant_key": None, "source_scope": "combined",
         "analysis_version": "v1", "input_hash": _hash("s1s2s3"),
         "summary_texts": ["요약"], "total_count": 3, "excluded_count": 1,
         "raw_distribution": {"5": 0.666667, "1": 0.333333}, "refined_distribution": {"5": 1.0},
         "observation_evidence": [], "review_status": "approved"},
    ]
    return samples, labels, analysis


def _write(tmp_path: Path, samples, labels, analysis) -> Path:
    def _dump(name, rows):
        p = tmp_path / name
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        return {"path": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "record_count": len(rows)}

    files = [_dump("samples.jsonl", samples), _dump("labels.jsonl", labels), _dump("analysis.jsonl", analysis)]
    manifest = {"schema_version": 1, "dataset_version": "test-v1", "corpus": "synthetic", "language": "ko",
                "domain": "baby", "generated_at": "2026-01-01T00:00:00+00:00", "files": files,
                "label_definition_version": "v1", "split_policy": "fixed"}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return mp


# ── committed golden fixture (RV02 exact example) ──────────────────────────
def test_rv02_raw_refined_excluded_ratio_match_the_contract_example():
    plans = validate_and_compute(FIXTURE)
    assert len(plans) == 1
    p = plans[0]
    assert p.analyzed_count == 3 and p.excluded_count == 1 and p.retained_count == 2
    assert p.raw_avg == pytest.approx(11 / 3, abs=1e-6)
    assert p.refined_avg == 5.0
    assert p.excluded_count / p.analyzed_count == pytest.approx(1 / 3, abs=1e-6)
    assert p.raw_distribution == {"5": pytest.approx(2 / 3, abs=1e-6), "1": pytest.approx(1 / 3, abs=1e-6)}
    assert p.refined_distribution == {"5": 1.0}


def test_rv02_all_excluded_yields_null_refined_average(tmp_path):
    samples, labels, analysis = _base_rows()
    labels[0]["label"] = labels[1]["label"] = "excluded"
    analysis[0]["excluded_count"] = 3
    analysis[0]["refined_distribution"] = {}
    mp = _write(tmp_path, samples, labels, analysis)
    plans = validate_and_compute(mp)
    assert plans[0].refined_avg is None
    assert plans[0].refined_distribution == {}


# ── RV03: rejection cases ───────────────────────────────────────────────────
def test_rv03_tampered_file_hash_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    mp = _write(tmp_path, samples, labels, analysis)
    (tmp_path / "samples.jsonl").write_text(
        (tmp_path / "samples.jsonl").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "file_hash_mismatch"


def test_rv03_label_referencing_unknown_sample_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    labels.append({"sample_id": "ghost", "label": "retained", "review_status": "approved",
                    "reviewer_ref": "m", "method_version": "v1", "observations": []})
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "unknown_sample_label"


def test_rv03_unapproved_analysis_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    analysis[0]["review_status"] = "pending"
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "unapproved_analysis"


def test_rv03_duplicate_sample_id_with_different_content_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    dup = dict(samples[0]); dup["text_hash"] = _hash("different-content")
    samples.append(dup)
    analysis[0]["total_count"] = 4
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "duplicate_sample_diverges"


def test_rv03_impossible_declared_distribution_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    analysis[0]["raw_distribution"] = {"5": 0.9, "1": 0.9}       # 합이 1을 넘음 — 조작된 값
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "analysis_totals_mismatch"


def test_rv03_declared_excluded_count_mismatch_is_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    analysis[0]["excluded_count"] = 0        # 실제로는 s3 하나가 excluded
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "analysis_totals_mismatch"


def test_rv03_reimport_same_manifest_is_deterministic_and_idempotent(tmp_path):
    """같은 파일을 두 번 검증해도 같은 계획이 나온다(적재 시 중복 통계를 만들 근거가 된다)."""
    samples, labels, analysis = _base_rows()
    mp = _write(tmp_path, samples, labels, analysis)
    first, second = validate_and_compute(mp), validate_and_compute(mp)
    assert first[0].analyzed_count == second[0].analyzed_count
    assert first[0].raw_avg == second[0].raw_avg


# ── RV04: corpus separation ──────────────────────────────────────────────────
def test_rv04_mixed_real_and_synthetic_samples_are_rejected(tmp_path):
    samples, labels, analysis = _base_rows()
    samples[0]["is_synthetic"] = False      # manifest.corpus는 synthetic인데 표본 하나가 real
    mp = _write(tmp_path, samples, labels, analysis)
    with pytest.raises(ReviewAnalysisImportError) as exc:
        validate_and_compute(mp)
    assert exc.value.code == "mixed_corpus"


def test_rv04_pending_or_rejected_labels_are_excluded_from_analysis_not_counted_as_zero(tmp_path):
    """미승인 라벨은 분석 모수에서 빠진다 — "본 적 없음"과 "0건"은 다르다."""
    samples, labels, analysis = _base_rows()
    labels[2]["review_status"] = "pending"   # s3(excluded 라벨)가 아직 미승인
    analysis[0]["total_count"] = 2
    analysis[0]["excluded_count"] = 0
    analysis[0]["raw_distribution"] = {"5": 1.0}
    analysis[0]["refined_distribution"] = {"5": 1.0}
    mp = _write(tmp_path, samples, labels, analysis)
    plans = validate_and_compute(mp)
    assert plans[0].analyzed_count == 2 and plans[0].excluded_count == 0
