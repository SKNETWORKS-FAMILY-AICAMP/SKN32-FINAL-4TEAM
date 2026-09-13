#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazon Reviews'23 상품 메타 jsonl → 제목·평점 수·카테고리·스펙(details)만 남긴 TSV (표준 라이브러리).

메타 원본(Electronics 5.2GB)은 설명·이미지·동영상이 대부분이다. 데모 부품 ↔ ASIN 매핑과
허위 여부 축(스펙 대조)에 필요한 것은 제목·카테고리·details 뿐이라 그것만 뽑는다.

  출력  data/amazon23/<cat>_meta.tsv
        parent_asin  title  main_category  categories(|구분)  store  rating_number  average_rating  price  details(JSON)

사용:  python scripts/amazon23_meta_slim.py /path/meta_Electronics.jsonl --cat electronics
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _clean(s) -> str:
    return str(s if s is not None else "").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="data/amazon23")
    ap.add_argument("--cat", default=None)
    a = ap.parse_args()
    src = Path(a.src)
    cat = a.cat or src.stem.lower().replace("meta_", "")
    out = Path(a.out) / f"{cat}_meta.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)

    n = bad = 0
    with open(src, encoding="utf-8") as fin, open(out, "w", encoding="utf-8") as fo:
        fo.write("parent_asin\ttitle\tmain_category\tcategories\tstore\trating_number\taverage_rating\tprice\tdetails\n")
        for line in fin:
            if not line.strip():
                continue
            n += 1
            try:
                r = json.loads(line)
            except Exception:
                bad += 1
                continue
            fo.write("\t".join([
                _clean(r.get("parent_asin")), _clean(r.get("title")), _clean(r.get("main_category")),
                "|".join(_clean(c) for c in (r.get("categories") or [])), _clean(r.get("store")),
                _clean(r.get("rating_number") or 0), _clean(r.get("average_rating") or ""),
                _clean(r.get("price") or ""),
                _clean(json.dumps(r.get("details") or {}, ensure_ascii=False)),
            ]) + "\n")
            if n % 500_000 == 0:
                print(f"  ...{n:,}", file=sys.stderr)
    print(f"{cat}: 상품 {n - bad:,}건 (버림 {bad:,}) → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
