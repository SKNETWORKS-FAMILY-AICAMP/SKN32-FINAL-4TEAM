#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""데모 부품(data/parts_list.csv) ↔ Amazon'23 Electronics 상품(parent_asin) 매핑.

관계·행동 축 산출물은 ASIN 으로 키가 잡혀 있고 엔진 후보는 부품명 슬러그로 잡혀 있다.
이 둘을 잇는 표가 없으면 S5 화면의 i5-14400F 에 카드가 영원히 안 붙는다.

매핑 규칙은 **부품마다 손으로 적는다** — 제목 유사도 같은 자동 매칭은 "RTX 4060" 에
"RTX 4060 Ti" 를, "Ryzen 5 7600" 에 "7600X" 를 붙인다. 규칙은 (필수 정규식, 제외 정규식)
이고, 후보가 여럿이면 평점 수(rating_number)가 가장 많은 상품을 고른다 — 데모 화면에
붙일 것이라 리뷰가 많은 쪽이 카드가 풍부하다. 상위 후보 3개를 같이 남겨 사람이 고칠 수 있게 한다.

**Amazon'23 은 2023-09 까지다.** 2024년 이후 출시 부품(14세대·Ultra 200·RTX 50·Ryzen 9000·
Z890/B850/B860·Liquid Freezer III …)은 데이터에 없다. 그 행은 asin 이 비고 이유가 적힌다.

  입력  data/parts_list.csv · data/amazon23/electronics_meta.tsv (scripts/amazon23_meta_slim.py)
  출력  data/parts_asin_map.csv  (커밋한다 — 51행, 제목·평점 수뿐)

사용:  uv run --with pandas python scripts/map_parts_to_asin.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "data" / "parts_list.csv"
META = ROOT / "data" / "amazon23" / "electronics_meta.tsv"
OUT = ROOT / "data" / "parts_asin_map.csv"

# 부품명 → (필수 패턴, 제외 패턴, 데이터 기간 밖이면 이유)
# 필수·제외는 제목에 대한 정규식(대소문자 무시). 필수는 전부 맞아야 한다.
RULES: dict[str, tuple[list[str], list[str], str | None]] = {
    # cpu
    "Intel Core i5-14400F": ([r"\bi5-14400F\b"], [], "2024-01 출시"),
    "Intel Core i5-14600K": ([r"\bi5-14600K\b"], [r"14600KF"], "2023-10 출시 (데이터 종료 후)"),
    "Intel Core i7-14700K": ([r"\bi7-14700K\b"], [r"14700KF"], "2023-10 출시 (데이터 종료 후)"),
    "Intel Core Ultra 7 265K": ([r"Ultra 7 265K"], [], "2024-10 출시"),
    "Intel Core Ultra 9 285K": ([r"Ultra 9 285K"], [], "2024-10 출시"),
    "AMD Ryzen 5 7600": ([r"Ryzen\W*5 7600(?![X\dGH])"], [r"7600X"], None),
    "AMD Ryzen 7 7700": ([r"Ryzen\W*7 7700(?![X\dGH])"], [r"7700X"], None),
    "AMD Ryzen 7 9800X3D": ([r"9800X3D"], [], "2024-11 출시"),
    "AMD Ryzen 9 9950X": ([r"9950X(?!3D)"], [], "2024-08 출시"),
    "AMD Ryzen 5 5600": ([r"Ryzen\W*5 5600(?![XGH\d])"], [r"5600X", r"5600G", r"5600H", r"5600X3D"], None),
    # mainboard
    "ASUS PRIME B760M-A WIFI": ([r"B760M-A (?:AX|Wi-?Fi)"], [r"CSM"], None),   # 북미명 "B760M-A AX" = WIFI 판
    "ASUS ROG STRIX Z790-E GAMING WIFI": ([r"Z790-E"], [r"Z790-E II"], None),
    "MSI MAG B760 TOMAHAWK WIFI": ([r"B760 Tomahawk"], [r"MAX"], None),
    "MSI MAG Z890 TOMAHAWK WIFI": ([r"Z890 Tomahawk"], [], "2024-10 출시"),
    "ASRock B860M Pro RS": ([r"B860M Pro RS"], [], "2025-01 출시"),
    "ASUS TUF GAMING B650-PLUS WIFI": ([r"B650-PLUS", r"Wi-?Fi"], [], None),
    "MSI MAG B850 TOMAHAWK WIFI": ([r"B850 Tomahawk"], [], "2025-01 출시"),
    "ASRock X870E Taichi": ([r"X870E Taichi"], [], "2024-10 출시"),
    "ASRock B550M Pro RS": ([r"B550M Pro RS"], [r"Pro RS/ac"], None),
    "GIGABYTE B650 AORUS ELITE AX": ([r"B650 AORUS ELITE AX"], [r"ICE", r"V2"], None),
    # ram
    "Samsung DDR5-5600 32GB (2x16)": ([r"^Samsung", r"DDR5", r"5600", r"(?:32\s?GB|2\s?x\s?16)"], [r"SODIMM", r"Samsung IC"], None),
    "G.Skill Trident Z5 RGB DDR5-6000 CL30 32GB (2x16)": ([r"Trident Z5 RGB", r"6000", r"32\s?GB", r"CL30"], [r"64\s?GB"], None),
    "G.Skill Flare X5 DDR5-6000 CL36 32GB (2x16)": ([r"Flare X5", r"6000", r"32\s?GB", r"CL36"], [r"64\s?GB"], None),
    "Samsung DDR4-3200 16GB (2x8)": ([r"^Samsung", r"DDR4", r"3200", r"(?:16\s?GB|2\s?x\s?8)"], [r"SODIMM", r"Samsung IC"], None),   # "Samsung IC" 를 단 타사 킷 제외
    "G.Skill Ripjaws V DDR4-3600 32GB (2x16)": ([r"Ripjaws V", r"3600", r"32\s?GB"], [r"64\s?GB", r"16\s?GB\s?\("], None),
    # gpu — 칩 이름이라 AIB 카드 여러 개가 걸린다. 평점 수 최다를 고른다
    "NVIDIA GeForce RTX 4060": ([r"RTX\W*4060(?!\s?Ti)"], [r"\bTi\b"], None),   # 제목에 ™ 가 끼어 \W* 로
    "NVIDIA GeForce RTX 4070 SUPER": ([r"RTX\W*4070\s?SUPER"], [r"Ti"], "2024-01 출시"),
    "NVIDIA GeForce RTX 4070 Ti SUPER": ([r"RTX\W*4070\s?Ti\s?SUPER"], [], "2024-01 출시"),
    "NVIDIA GeForce RTX 5070 Ti": ([r"RTX\W*5070\s?Ti"], [], "2025-02 출시"),
    "NVIDIA GeForce RTX 5080": ([r"RTX\W*5080"], [], "2025-01 출시"),
    "NVIDIA GeForce RTX 5090": ([r"RTX\W*5090"], [], "2025-01 출시"),
    "AMD Radeon RX 7600": ([r"RX\W*7600(?!\s?XT)"], [r"\bXT\b"], None),
    "AMD Radeon RX 7800 XT": ([r"RX\s?7800\s?XT"], [r"Gaming PC"], None),
    "AMD Radeon RX 9070 XT": ([r"RX\s?9070\s?XT"], [], "2025-03 출시"),
    # ssd
    "Samsung 990 PRO 1TB": ([r"990 PRO", r"1\s?TB"], [r"2\s?TB", r"4\s?TB"], None),
    "Samsung 990 PRO 2TB": ([r"990 PRO", r"2\s?TB"], [r"1\s?TB", r"4\s?TB"], None),
    "WD Black SN770 1TB": ([r"SN770", r"1\s?TB"], [r"2\s?TB", r"500\s?GB", r"250\s?GB"], None),
    "Crucial MX500 1TB": ([r"MX500", r"1\s?TB"], [r"2\s?TB", r"500\s?GB", r"4\s?TB", r"250\s?GB"], None),
    # psu
    "Corsair RM650e": ([r"\bRM650e\b"], [], None),
    "Corsair RM750e": ([r"\bRM750e\b"], [], None),
    "Corsair RM850e": ([r"\bRM850e\b"], [], None),
    "MSI MPG A1000G PCIE5": ([r"A1000G"], [], None),
    "Corsair SF750": ([r"\bSF750\b"], [], None),
    # case
    "Fractal Design North": ([r"Fractal", r"\bNorth\b"], [r"XL"], None),
    "NZXT H5 Flow": ([r"H5 Flow"], [r"RGB", r"Elite"], None),
    "Cooler Master NR200P MAX": ([r"NR200P MAX"], [], None),
    "ASUS Prime AP201": ([r"AP201"], [], None),
    # cooler
    "Thermalright Peerless Assassin 120 SE": ([r"Peerless Assassin 120 SE"], [r"ARGB", r"WHITE", r"Digital"], None),
    "Noctua NH-D15": ([r"NH-D15(?!S)"], [r"NH-D15S", r"NH-D15 G2"], None),
    "Arctic Liquid Freezer III 360": ([r"Liquid Freezer III 360"], [], "2024-01 출시"),
    "DeepCool AK400": ([r"DeepCool", r"\bAK400\b"], [r"Digital"], None),        # ZERO DARK 등 색상 변형 허용
}

# 어느 부품이든 완제품·노트북 제목은 뺀다 (칩 이름이 들어간 노트북이 CPU/GPU 에 걸린다)
COMMON_EXCLUDE = [r"Laptop", r"Notebook", r"Gaming PC", r"Desktop PC", r"Gaming Desktop", r"Zenbook", r"IdeaPad",
                  r"Computer Desktop", r"Mini PC", r"\bPC\b.*(?:Ryzen|Core i|RTX|Radeon)"]

# 부품 유형별로 제목이 있어야 할 카테고리 (엉뚱한 액세서리·완제품 PC 를 거른다)
TYPE_CATEGORY = {
    "cpu": r"CPU Processors|Processors", "mainboard": r"Motherboards", "ram": r"Memory",
    "gpu": r"Graphics Cards", "ssd": r"Solid State Drives|Internal", "psu": r"Power Supplies",
    "case": r"Computer Cases", "cooler": r"Fans & Cooling|Water Cooling|CPU Cooling",
}


def load_parts() -> list[dict]:
    rows = []
    with PARTS.open(encoding="utf-8-sig") as f:
        for r in csv.reader(l for l in f if l.strip() and not l.startswith("#")):
            if r[0] == "type":
                continue
            rows.append({"type": r[0].strip(), "name": r[1].strip(), "brand": r[2].strip()})
    return rows


def engine_key(name: str) -> str:            # src/repo/catalog_repo.py 와 같은 규칙
    return name.lower().replace(" ", "-")


def summary_key(name: str) -> str:           # scripts/gen_review_summaries.py 의 slugify 와 같은 규칙
    return re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-")


def main() -> None:
    meta = pd.read_csv(META, sep="\t", dtype="string", usecols=["parent_asin", "title", "categories", "rating_number", "average_rating"])
    meta["rating_number"] = pd.to_numeric(meta.rating_number, errors="coerce").fillna(0).astype(int)
    meta["title"] = meta.title.fillna("")
    meta["categories"] = meta.categories.fillna("")
    parts = load_parts()

    rows = []
    for p in parts:
        req, exc, absent = RULES[p["name"]]
        m = meta
        for r in req:
            m = m[m.title.str.contains(r, case=False, regex=True)]
        for r in exc:
            m = m[~m.title.str.contains(r, case=False, regex=True)]
        for r in COMMON_EXCLUDE:
            m = m[~m.title.str.contains(r, case=False, regex=True)]
        catpat = TYPE_CATEGORY.get(p["type"])
        if catpat:
            m = m[m.categories.str.contains(catpat, case=False, regex=True)]   # 폴백 없음 — 노트북·완제품이 걸린다
        m = m.sort_values("rating_number", ascending=False)
        best = m.iloc[0] if len(m) else None
        rows.append({
            "product_key": engine_key(p["name"]), "summary_key": summary_key(p["name"]),
            "name": p["name"], "type": p["type"],
            "asin": best.parent_asin if best is not None else "",
            "title": best.title[:120] if best is not None else "",
            "rating_number": int(best.rating_number) if best is not None else 0,
            "average_rating": best.average_rating if best is not None else "",
            "n_candidates": int(len(m)),
            "alt_asins": "|".join(m.parent_asin.iloc[1:4]) if len(m) > 1 else "",
            "note": ("데이터 기간(~2023-09) 밖: " + absent) if (absent and best is None)
                    else ("기간 밖인데 매칭됨 — 제목 확인 필요: " + absent) if absent else ("후보 없음" if best is None else ""),
        })

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")   # 저장소는 LF (.gitattributes)
        w.writeheader(); w.writerows(rows)

    hit = [r for r in rows if r["asin"]]
    print(f"부품 {len(rows)}개 중 매핑 {len(hit)}개 → {OUT}")
    for r in rows:
        mark = "✓" if r["asin"] else "✗"
        print(f"  {mark} {r['name']:<48} {r['asin']:<11} 평점수 {r['rating_number']:>7,}  후보 {r['n_candidates']:>3}  {r['note']}")
        if r["asin"]:
            print(f"      {r['title'][:100]}")


if __name__ == "__main__":
    main()
