#!/usr/bin/env python3
"""이 디렉터리의 manifest.json/samples.jsonl/labels.jsonl/analysis.jsonl을 만든 스크립트.

RV02 계약 예시(raw ratings [5,5,1], 승인 제외 표본 1/3 → raw=11/3, refined=5,
excluded=1/3)를 그대로 재현하는 최소 합성 고정 픽스처다. 파일을 손으로 고치면
sha256/record_count가 어긋나 import가 file_hash_mismatch로 거부된다 — 내용을 바꾸려면
이 스크립트를 고쳐 다시 실행한다.

    python tests/fixtures/reviews/approved_demo/build_fixture.py
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> None:
    samples = [
        {"sample_id": "s1", "product_key": "SYN-STROLLER-001", "variant_key": None, "rating": 5,
         "reviewer_id": "reviewer-1", "created_at": "2026-01-05T00:00:00+00:00",
         "text_or_excerpt": "무게가 가볍고 접이가 편해요.", "text_hash": _hash("s1-text-v1"),
         "source_ref": "https://example.test/reviews/s1", "is_synthetic": True, "split": "test"},
        {"sample_id": "s2", "product_key": "SYN-STROLLER-001", "variant_key": None, "rating": 5,
         "reviewer_id": "reviewer-2", "created_at": "2026-01-06T00:00:00+00:00",
         "text_or_excerpt": "바퀴가 부드럽고 방향 전환이 쉬워요.", "text_hash": _hash("s2-text-v1"),
         "source_ref": "https://example.test/reviews/s2", "is_synthetic": True, "split": "test"},
        {"sample_id": "s3", "product_key": "SYN-STROLLER-001", "variant_key": None, "rating": 1,
         "reviewer_id": "reviewer-3", "created_at": "2026-01-07T00:00:00+00:00",
         "text_or_excerpt": "짧은 기간에 같은 계정군에서 몰려 올라온 평점으로 관측됨.",
         "text_hash": _hash("s3-text-v1"),
         "source_ref": "https://example.test/reviews/s3", "is_synthetic": True, "split": "test"},
    ]
    labels = [
        {"sample_id": "s1", "label": "retained", "review_status": "approved", "reviewer_ref": "mod-a",
         "method_version": "manual-v1", "observations": [], "confidence": 0.1},
        {"sample_id": "s2", "label": "retained", "review_status": "approved", "reviewer_ref": "mod-a",
         "method_version": "manual-v1", "observations": [], "confidence": 0.15},
        {"sample_id": "s3", "label": "excluded", "review_status": "approved", "reviewer_ref": "mod-a",
         "method_version": "manual-v1", "observations": ["burst7", "prolific_rate"], "confidence": 0.92},
    ]
    analysis = [
        {"subject_key": "SYN-STROLLER-001", "variant_key": None, "source_scope": "combined",
         "analysis_version": "review-analysis-v1",
         "input_hash": _hash("".join(s["text_hash"] for s in samples)),
         "summary_texts": ["5점 응답 2건, 1점 응답 1건(승인 제외) — 파일 기반 분석 v1"],
         "total_count": 3, "excluded_count": 1,
         "raw_distribution": {"5": 0.666667, "1": 0.333333},
         "refined_distribution": {"5": 1.0},
         "observation_evidence": ["짧은 기간 내 유사 계정군 몰림 관측(s3)"],
         "review_status": "approved"},
    ]

    def _write_jsonl(name: str, rows: list[dict]) -> dict:
        path = HERE / name
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        path.write_text(text, encoding="utf-8")
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "record_count": len(rows)}

    files = [
        _write_jsonl("samples.jsonl", samples),
        _write_jsonl("labels.jsonl", labels),
        _write_jsonl("analysis.jsonl", analysis),
    ]
    manifest = {
        "schema_version": 1, "dataset_version": "baby-review-analysis-approved-demo-v1",
        "corpus": "synthetic", "language": "ko", "domain": "baby",
        "generated_at": "2026-09-14T00:00:00+00:00",
        "files": files, "label_definition_version": "v1", "split_policy": "fixed",
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", HERE)


if __name__ == "__main__":
    build()
