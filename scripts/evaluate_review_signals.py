#!/usr/bin/env python3
"""P8 IMPLEMENTATION5 — 리뷰 진위 신호(관측 지표 개수/신뢰도)의 연구용 평가.

승인된 라벨(review_status=approved)만 정답으로 쓴다. 부모/작성자/캠페인/상품 파생
leakage 단위가 분할(split)을 넘나들면 평가를 거부한다(leakage_split_violation) —
같은 리뷰어의 표본이 train과 test에 걸쳐 있으면 탐지기가 "본 적 있는 사람"을 맞히는
것과 "조작을 맞히는 것"을 구별할 수 없다. 독립 leakage 단위 수가 문턱(기본 5)
미만이면 not_evaluated로 낸다 — 표본이 3개인데 confusion matrix를 내면 숫자는
그럴듯하지만 아무 것도 검증하지 않는다.

    uv run python scripts/evaluate_review_signals.py \\
        --manifest tests/fixtures/reviews/approved_demo/manifest.json \\
        --output generated/reviews/evaluation.json

합성(corpus=synthetic) 표본의 평가 결과는 실제 탐지 성능의 증거가 아니다 — 항상
그 사실을 결과에 같이 적는다(RV04).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_review_analysis import ReviewAnalysisImportError, _read_jsonl, _sha256  # noqa: E402

MIN_INDEPENDENT_PER_CLASS = 5
TARGET_FPR = 0.01
OBS_HEURISTIC_THRESHOLD = 2   # 기존 SuspectCountFile과 같은 "지표 2개+" 문턱


def _leakage_key(sample: dict) -> str:
    return str(sample.get("reviewer_id") or sample.get("parent_sample_id") or sample["product_key"])


def _load(manifest_path: Path) -> tuple[dict, dict[str, dict], dict[str, dict]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    samples: dict[str, dict] = {}
    labels: dict[str, dict] = {}
    for entry in manifest["files"]:
        fp = base / entry["path"]
        if _sha256(fp) != entry["sha256"]:
            raise ReviewAnalysisImportError("file_hash_mismatch", entry["path"])
        rows = _read_jsonl(fp)
        if rows and "subject_key" in rows[0]:
            continue  # analysis 파일 — 평가 대상 아님
        if rows and "label" in rows[0] and "review_status" in rows[0]:
            labels = {r["sample_id"]: r for r in rows}
        elif rows and "sample_id" in rows[0]:
            samples = {r["sample_id"]: r for r in rows}
    return manifest, samples, labels


def _confusion(y_true: list[bool], y_pred: list[bool]) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def _rate(numer: int, denom: int) -> float | None:
    return None if denom == 0 else numer / denom


def evaluate(manifest_path: str | Path, *, target_fpr: float = TARGET_FPR,
            min_independent_per_class: int = MIN_INDEPENDENT_PER_CLASS) -> dict:
    manifest, samples, labels = _load(Path(manifest_path))
    is_synthetic = manifest["corpus"] == "synthetic"

    rows = []
    for sid, s in samples.items():
        label = labels.get(sid)
        if label is None or label.get("review_status") != "approved":
            continue
        rows.append({"sample": s, "label": label})

    # leakage: 같은 unit이 서로 다른 split에 걸치면 평가 자체를 거부한다.
    splits_by_unit: dict[str, set] = {}
    for r in rows:
        splits_by_unit.setdefault(_leakage_key(r["sample"]), set()).add(r["sample"].get("split", "unassigned"))
    violations = [u for u, splits in splits_by_unit.items() if len(splits) > 1]
    if violations:
        return {"status": "not_evaluated", "reason": "leakage_split_violation",
                "corpus": manifest["corpus"], "is_synthetic_only": is_synthetic,
                "violating_units": violations,
                "note": "동일 leakage 단위(리뷰어/부모/상품)가 서로 다른 split에 걸쳐 있어 평가를 거부했다."}

    y_true = [r["label"]["label"] == "excluded" for r in rows]
    pos_units = {_leakage_key(r["sample"]) for r, t in zip(rows, y_true) if t}
    neg_units = {_leakage_key(r["sample"]) for r, t in zip(rows, y_true) if not t}

    if len(pos_units) < min_independent_per_class or len(neg_units) < min_independent_per_class:
        return {
            "status": "not_evaluated",
            "reason": "insufficient_independent_labels",
            "corpus": manifest["corpus"], "is_synthetic_only": is_synthetic,
            "required_independent_units_per_class": min_independent_per_class,
            "actual_independent_positive_units": len(pos_units),
            "actual_independent_negative_units": len(neg_units),
            "n_samples": len(rows),
            "note": "독립 leakage 단위가 문턱 미만이라 confusion matrix/FPR을 내지 않는다"
                    " — 표본이 적을 때 낸 숫자는 그럴듯해 보일 뿐 아무 것도 검증하지 않는다.",
        }

    y_obs_pred = [len(r["label"].get("observations") or []) >= OBS_HEURISTIC_THRESHOLD for r in rows]
    heuristic = _confusion(y_true, y_obs_pred)
    heuristic["fpr"] = _rate(heuristic["fp"], heuristic["fp"] + heuristic["tn"])
    heuristic["detection_rate"] = _rate(heuristic["tp"], heuristic["tp"] + heuristic["fn"])

    result = {
        "status": "evaluated",
        "corpus": manifest["corpus"], "is_synthetic_only": is_synthetic,
        "n_samples": len(rows),
        "independent_positive_units": len(pos_units), "independent_negative_units": len(neg_units),
        "target_fpr": target_fpr,
        "observation_count_heuristic": {
            "threshold": f">= {OBS_HEURISTIC_THRESHOLD} observations", **heuristic,
        },
        "confidence_threshold_sweep": None,
        "notes": [],
    }
    if is_synthetic:
        result["notes"].append(
            "합성(corpus=synthetic) 표본 평가다 — 실제 리뷰 데이터의 탐지 성능 증거로 쓸 수 없다.")

    confidences = [r["label"].get("confidence") for r in rows]
    if all(c is not None for c in confidences):
        pairs = sorted(zip(confidences, y_true), key=lambda x: -x[0])
        best = None
        for i in range(len(pairs) + 1):
            threshold_pred = [c >= (pairs[i - 1][0] if i > 0 else 1.0 + 1e-9) for c, _ in pairs]
            conf = _confusion(y_true, threshold_pred)
            fpr = _rate(conf["fp"], conf["fp"] + conf["tn"])
            if fpr is not None and fpr <= target_fpr:
                best = {"threshold": pairs[i - 1][0] if i > 0 else None, **conf, "fpr": fpr,
                        "detection_rate": _rate(conf["tp"], conf["tp"] + conf["fn"])}
        result["confidence_threshold_sweep"] = best or {
            "note": f"target_fpr={target_fpr}을 만족하는 문턱이 없다(모든 문턱에서 FPR 초과)."}
    else:
        result["notes"].append("일부 표본에 confidence가 없어 문턱 스윕 없이 관측지표 문턱(observation_count_heuristic)만 낸다.")

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--target-fpr", type=float, default=TARGET_FPR)
    ap.add_argument("--min-independent-per-class", type=int, default=MIN_INDEPENDENT_PER_CLASS)
    args = ap.parse_args()

    try:
        result = evaluate(args.manifest, target_fpr=args.target_fpr,
                          min_independent_per_class=args.min_independent_per_class)
    except ReviewAnalysisImportError as exc:
        result = {"status": "rejected", "code": exc.code, "detail": str(exc)}

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["status"] != "rejected" else 1


if __name__ == "__main__":
    sys.exit(main())
