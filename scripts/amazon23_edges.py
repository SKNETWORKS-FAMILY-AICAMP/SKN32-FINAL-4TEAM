#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazon Reviews'23 리뷰 jsonl → 관계·행동 축 엣지 표 (표준 라이브러리만).

관계·행동 축은 본문을 보지 않는다. 필요한 것은 리뷰어–상품 엣지와 시각·평점뿐이라
원문(text/title)은 버리고 한 줄에 한 엣지로 줄인다. 원문 미저장 정책(§15)과도 맞다.

  입력  Amazon'23 카테고리 리뷰 jsonl (McAuley-Lab/Amazon-Reviews-2023)
  출력  data/amazon23/<cat>_edges.tsv    user_id  parent_asin  ts_ms  rating  verified  helpful  n_img  text_len
        data/amazon23/<cat>_images.tsv   user_id  parent_asin  ts_ms  large_image_url   (이미지 재사용 축 확인용)
        stderr 에 게이트 Q3(계정당 리뷰 중앙값) · Q6(상품당 리뷰) 요약

  ※ 부분집합이 아니라 전량이다. 공유 리뷰어·연결 상품은 엣지 전체가 있어야 나온다.
  ※ 출력물은 외부 데이터셋 파생물이라 커밋하지 않는다 (.gitignore: data/amazon23/).

사용:  python scripts/amazon23_edges.py /path/to/Baby_Products.jsonl [--out data/amazon23]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="data/amazon23")
    ap.add_argument("--cat", default=None, help="출력 파일 접두 (기본: 입력 파일명)")
    a = ap.parse_args()

    src = Path(a.src)
    cat = a.cat or src.stem.lower()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f_edges = out / f"{cat}_edges.tsv"
    f_imgs = out / f"{cat}_images.tsv"

    users: Counter[str] = Counter()
    prods: Counter[str] = Counter()
    n = bad = n_img_rows = 0
    with open(src, encoding="utf-8") as fin, \
         open(f_edges, "w", encoding="utf-8") as fe, \
         open(f_imgs, "w", encoding="utf-8") as fi:
        fe.write("user_id\tparent_asin\tts_ms\trating\tverified\thelpful\tn_img\ttext_len\n")
        fi.write("user_id\tparent_asin\tts_ms\turl\n")
        for line in fin:
            if not line.strip():
                continue
            n += 1
            try:
                r = json.loads(line)
            except Exception:
                bad += 1
                continue
            u = r.get("user_id") or ""
            p = r.get("parent_asin") or r.get("asin") or ""
            ts = int(r.get("timestamp") or 0)
            if not u or not p or not ts:
                bad += 1
                continue
            imgs = r.get("images") or []
            fe.write("%s\t%s\t%d\t%s\t%d\t%d\t%d\t%d\n" % (
                u, p, ts, r.get("rating", ""), 1 if r.get("verified_purchase") else 0,
                int(r.get("helpful_vote") or 0), len(imgs), len(r.get("text") or "")))
            for im in imgs:
                url = im.get("large_image_url") or im.get("medium_image_url") or im.get("small_image_url")
                if url:
                    fi.write("%s\t%s\t%d\t%s\n" % (u, p, ts, url))
                    n_img_rows += 1
            users[u] += 1
            prods[p] += 1
            if n % 1_000_000 == 0:
                print(f"  ...{n:,}", file=sys.stderr)

    uc = sorted(users.values())
    pc = sorted(prods.values())
    n_ok = n - bad
    ge3_users = sum(1 for c in uc if c >= 3)
    ge3_reviews = sum(c for c in uc if c >= 3)
    print("=" * 66, file=sys.stderr)
    print(f"{cat}: 리뷰 {n_ok:,}건 (버림 {bad:,}) · 사용자 {len(uc):,} · 상품 {len(pc):,} · 이미지 {n_img_rows:,}장",
          file=sys.stderr)
    print(f"[Q3] 계정당 리뷰 — 중앙값 {statistics.median(uc):.0f} · 평균 {n_ok/len(uc):.2f} · "
          f"3건+ 사용자 {100*ge3_users/len(uc):.1f}% · 그 사용자의 리뷰 비중 {100*ge3_reviews/n_ok:.1f}%",
          file=sys.stderr)
    print(f"[Q6] 상품당 리뷰 — 중앙값 {statistics.median(pc):.0f} · 평균 {n_ok/len(pc):.1f} · "
          f"30건+ 상품 {100*sum(1 for c in pc if c >= 30)/len(pc):.1f}%",
          file=sys.stderr)
    print(f"→ {f_edges}\n→ {f_imgs}", file=sys.stderr)


if __name__ == "__main__":
    main()
