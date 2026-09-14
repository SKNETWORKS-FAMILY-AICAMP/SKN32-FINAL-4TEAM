#!/usr/bin/env python3
"""P8 — 파일 기반 리뷰 분석 결과를 evidence.review_summary/review_aggregate(_member)로 적재.

스키마 정의는 docs/review_analysis_contract.md. manifest.json이 가리키는 samples/labels/
analysis 세 JSONL 파일을 검증한 뒤, subject(product_key[/variant_key])별로 하나의
review_aggregate 스냅샷을 원자적으로 만든다.

    DATABASE_URL=... uv run python scripts/import_review_analysis.py \\
        --manifest tests/fixtures/reviews/approved_demo/manifest.json

검증(파일 해시·중복 sample_id·라벨 참조·분포 일치)은 DB 없이도 `validate_and_compute()`로
따로 실행할 수 있다(tests/test_review_analysis_files.py). 이 스크립트는 검증 뒤 실제 DB에
적재까지 한다. 이미 같은 (subject, domain_version, source_scope, analysis_version)로
내용까지 동일하게 재실행하면 아무 것도 새로 쓰지 않는다(멱등) — RV03.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ReviewAnalysisImportError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


REQUIRED_MANIFEST_KEYS = ("schema_version", "dataset_version", "corpus", "language", "domain",
                          "generated_at", "files", "label_definition_version", "split_policy")
ALLOWED_LABELS = ("retained", "excluded")
ALLOWED_REVIEW_STATUS = ("pending", "approved", "rejected")


@dataclass
class SampleMember:
    sample_id: str
    product_key: str
    variant_key: str | None
    rating: int
    text_or_excerpt: str | None
    text_hash: str
    source_ref: str | None
    created_at: str | None
    is_synthetic: bool
    disposition: str        # label.label, 'retained' | 'excluded'
    label_confidence: float | None
    observations: list


@dataclass
class AnalysisPlan:
    subject_key: str
    variant_key: str | None
    domain: str
    source_scope: str
    processing_version: str
    generated_at: str
    window_start: str
    window_end: str
    analyzed_count: int
    excluded_count: int
    retained_count: int
    raw_avg: float | None
    refined_avg: float | None
    raw_distribution: dict[str, float]
    refined_distribution: dict[str, float]
    summary_texts: list[str]
    observation_evidence: list
    members: list[SampleMember] = field(default_factory=list)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round(x: float) -> float:
    return round(x, 6)


def _check_distribution(dist: dict[str, float]) -> bool:
    total = sum(dist.values())
    return total == 0 or abs(total - 1.0) <= 1e-6


def validate_and_compute(manifest_path: str | Path) -> list[AnalysisPlan]:
    """DB에 닿지 않는 순수 검증+계산. 위반 시 ReviewAnalysisImportError."""
    manifest_path = Path(manifest_path)
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise ReviewAnalysisImportError("manifest_missing_keys", str(missing))

    files_by_role: dict[str, Path] = {}
    for entry in manifest["files"]:
        fp = base / entry["path"]
        if not fp.exists():
            raise ReviewAnalysisImportError("file_missing", entry["path"])
        actual_hash = _sha256(fp)
        if actual_hash != entry["sha256"]:
            raise ReviewAnalysisImportError("file_hash_mismatch", entry["path"])
        rows = _read_jsonl(fp)
        if len(rows) != entry["record_count"]:
            raise ReviewAnalysisImportError("file_record_count_mismatch", entry["path"])
        # 역할은 내용 모양으로 판별한다(manifest가 파일명을 어떻게 짓든 안전하다):
        # analysis만 subject_key를 갖고, label만 review_status+label을 같이 갖는다.
        if rows and "subject_key" in rows[0]:
            files_by_role["analysis"] = fp
        elif rows and "label" in rows[0] and "review_status" in rows[0]:
            files_by_role["labels"] = fp
        elif rows and "sample_id" in rows[0]:
            files_by_role["samples"] = fp
        else:
            raise ReviewAnalysisImportError("file_unrecognized_shape", entry["path"])

    for role in ("samples", "labels", "analysis"):
        if role not in files_by_role:
            raise ReviewAnalysisImportError("manifest_missing_file_role", role)

    samples_raw = _read_jsonl(files_by_role["samples"])
    labels_raw = _read_jsonl(files_by_role["labels"])
    analysis_raw = _read_jsonl(files_by_role["analysis"])

    samples: dict[str, dict] = {}
    for row in samples_raw:
        sid = row["sample_id"]
        if sid in samples and samples[sid]["text_hash"] != row["text_hash"]:
            raise ReviewAnalysisImportError("duplicate_sample_diverges", sid)
        samples[sid] = row

    labels_by_sample: dict[str, dict] = {}
    for row in labels_raw:
        sid = row.get("sample_id")
        if sid not in samples:
            raise ReviewAnalysisImportError("unknown_sample_label", str(sid))
        if row.get("label") not in ALLOWED_LABELS or row.get("review_status") not in ALLOWED_REVIEW_STATUS:
            raise ReviewAnalysisImportError("invalid_label_row", sid)
        labels_by_sample[sid] = row

    declared_corpus_synthetic = manifest["corpus"] == "synthetic"

    plans: list[AnalysisPlan] = []
    for a in analysis_raw:
        subject_key = a["subject_key"]
        variant_key = a.get("variant_key")
        if a.get("review_status") != "approved":
            raise ReviewAnalysisImportError("unapproved_analysis", subject_key)

        members: list[SampleMember] = []
        for sid, s in samples.items():
            if s["product_key"] != subject_key or s.get("variant_key") != variant_key:
                continue
            label = labels_by_sample.get(sid)
            if label is None or label["review_status"] != "approved":
                continue  # 라벨 없음/미승인 표본은 분석 모수에서 빠진다 — 승인 안 됐다고 0건이 되지 않음
            if bool(s.get("is_synthetic")) != declared_corpus_synthetic:
                raise ReviewAnalysisImportError("mixed_corpus", subject_key)
            members.append(SampleMember(
                sample_id=sid, product_key=s["product_key"], variant_key=s.get("variant_key"),
                rating=int(s["rating"]), text_or_excerpt=s.get("text_or_excerpt"),
                text_hash=s["text_hash"], source_ref=s.get("source_ref"), created_at=s.get("created_at"),
                is_synthetic=bool(s.get("is_synthetic")), disposition=label["label"],
                label_confidence=label.get("confidence"), observations=label.get("observations") or [],
            ))

        analyzed = len(members)
        excluded = sum(1 for m in members if m.disposition == "excluded")
        retained = analyzed - excluded
        if analyzed != excluded + retained or excluded < 0 or retained < 0:
            raise ReviewAnalysisImportError("impossible_counts", subject_key)

        raw_ratings = [m.rating for m in members]
        refined_ratings = [m.rating for m in members if m.disposition == "retained"]
        raw_avg = _round(sum(raw_ratings) / len(raw_ratings)) if raw_ratings else None
        refined_avg = _round(sum(refined_ratings) / len(refined_ratings)) if refined_ratings else None

        def _dist(ratings: list[int]) -> dict[str, float]:
            if not ratings:
                return {}
            n = len(ratings)
            out: dict[str, float] = {}
            for r in ratings:
                out[str(r)] = out.get(str(r), 0.0) + 1.0 / n
            return {k: _round(v) for k, v in out.items()}

        raw_dist = _dist(raw_ratings)
        refined_dist = _dist(refined_ratings)
        if not _check_distribution(raw_dist) or not _check_distribution(refined_dist):
            raise ReviewAnalysisImportError("impossible_distribution", subject_key)

        declared_total = a.get("total_count")
        declared_excluded = a.get("excluded_count")
        if declared_total is not None and declared_total != analyzed:
            raise ReviewAnalysisImportError("analysis_totals_mismatch", f"{subject_key}:total_count")
        if declared_excluded is not None and declared_excluded != excluded:
            raise ReviewAnalysisImportError("analysis_totals_mismatch", f"{subject_key}:excluded_count")
        for label_key, declared_dist, computed_dist in (
            ("raw_distribution", a.get("raw_distribution"), raw_dist),
            ("refined_distribution", a.get("refined_distribution"), refined_dist),
        ):
            if declared_dist is None:
                continue
            keys = set(declared_dist) | set(computed_dist)
            if any(abs(declared_dist.get(k, 0.0) - computed_dist.get(k, 0.0)) > 1e-6 for k in keys):
                raise ReviewAnalysisImportError("analysis_totals_mismatch", f"{subject_key}:{label_key}")

        created_ats = [m.created_at for m in members if m.created_at]
        window_start = min(created_ats) if created_ats else manifest["generated_at"]
        window_end = manifest["generated_at"]

        plans.append(AnalysisPlan(
            subject_key=subject_key, variant_key=variant_key, domain=manifest["domain"],
            source_scope=a.get("source_scope", "combined"), processing_version=a["analysis_version"],
            generated_at=manifest["generated_at"], window_start=window_start, window_end=window_end,
            analyzed_count=analyzed, excluded_count=excluded, retained_count=retained,
            raw_avg=raw_avg, refined_avg=refined_avg, raw_distribution=raw_dist, refined_distribution=refined_dist,
            summary_texts=a.get("summary_texts") or [], observation_evidence=a.get("observation_evidence") or [],
            members=members,
        ))
    return plans


def apply_plan(conn, plan: AnalysisPlan, *, dataset_version: str) -> dict:
    from src.repo.plan_repo import PlanRepo
    from src.repo.review_repo import ReviewRepo, ReviewSubjectRepo

    subject_repo, review_repo, plan_repo = ReviewSubjectRepo(conn), ReviewRepo(conn), PlanRepo(conn)
    subject_id = subject_repo.resolve_by_key(plan.subject_key, plan.variant_key)
    if subject_id is None:
        raise ReviewAnalysisImportError("unknown_subject", f"{plan.subject_key}/{plan.variant_key}")
    domain_version = plan_repo.published_domain_version(plan.domain)
    if domain_version is None:
        raise ReviewAnalysisImportError("unknown_domain_version", plan.domain)
    source_id = review_repo.get_or_create_source(f"review_analysis:{dataset_version}")

    member_rows = []
    for m in plan.members:
        summary_id = review_repo.upsert_review_summary(
            subject_id=subject_id, source_id=source_id,
            external_review_key=m.sample_id, original_url=m.source_ref or f"analysis://{m.sample_id}",
            normalized_rating=m.rating, collected_at=m.created_at or plan.generated_at,
            processing_version=plan.processing_version, cleaning_status=m.disposition,
            exclusion_reason=None if m.disposition == "retained" else "review_analysis_excluded",
            summary=(m.text_or_excerpt or f"rating={m.rating}")[:2000],
        )
        member_rows.append({"summary_id": summary_id, "disposition": m.disposition})

    ratings = {"raw_avg": plan.raw_avg, "refined_avg": plan.refined_avg,
               "raw_distribution": plan.raw_distribution, "refined_distribution": plan.refined_distribution,
               "summary_texts": plan.summary_texts, "observation_evidence": plan.observation_evidence}
    result = review_repo.replace_aggregate(
        subject_id=subject_id, domain_version_id=domain_version["id"], source_scope=plan.source_scope,
        processing_version=plan.processing_version, window_start=plan.window_start, window_end=plan.window_end,
        analyzed_count=plan.analyzed_count, excluded_count=plan.excluded_count, retained_count=plan.retained_count,
        ratings=ratings, axis_scores={}, members=member_rows,
    )
    result["subject_key"] = plan.subject_key
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dry-run", action="store_true", help="검증만 하고 DB에 쓰지 않는다")
    args = ap.parse_args()

    try:
        plans = validate_and_compute(args.manifest)
    except ReviewAnalysisImportError as exc:
        print(json.dumps({"status": "rejected", "code": exc.code, "detail": str(exc)}, ensure_ascii=False))
        return 1

    if args.dry_run:
        print(json.dumps({"status": "validated", "subjects": [p.subject_key for p in plans]}, ensure_ascii=False))
        return 0

    from src.db import get_conn

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    results = []
    failed = False
    with get_conn() as conn:
        for plan in plans:
            try:
                results.append(apply_plan(conn, plan, dataset_version=manifest["dataset_version"]))
            except ReviewAnalysisImportError as exc:
                results.append({"status": "rejected", "subject_key": plan.subject_key, "code": exc.code, "detail": str(exc)})
                failed = True
    print(json.dumps(results, ensure_ascii=False, default=str, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
