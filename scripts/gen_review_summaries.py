#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/review_summaries.json 합성 생성기 (A안: 텍스트 톤은 AI Hub 리뷰 참고, 수치·구조는 합성).

- 입력  : data/parts_list.csv (부품 51개)
- 출력  : data/review_summaries.json  (엔진 [3-B]/[3-C]가 읽는 review_summaries 스키마)
          data/review_summaries_preview.csv  (사람이 눈으로 확인용)
- 성격  : 데모용. 평점/조작비율/항목별평가/대표요약은 전부 합성.
          원문은 저장하지 않음(저작권). orig_refs 는 AI Hub review_id 참조만.
- 재현성: product_key 해시 시드 → 재실행해도 동일. 팀이 값 직접 수정 가능.

사용:  python scripts/gen_review_summaries.py
"""
from __future__ import annotations
import csv, json, hashlib, random, re, sys
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
PARTS_CSV = ROOT / "data" / "parts_list.csv"
OUT_JSON = ROOT / "data" / "review_summaries.json"
OUT_PREVIEW = ROOT / "data" / "review_summaries_preview.csv"

COLLECT_BASE = date(2026, 9, 1)

# ──────────────────────────────────────────────────────────────────────────
# 부품군별 평가축 정의 + 대표요약 후보 (긍/부정 톤은 AI Hub 리뷰체 참고, 문장은 자체 작성)
#   각 축: (축이름, 기대 성향)  기대 성향은 seed 로 흔들려 실제 라벨이 정해짐
#   summaries: (축, 성향, 문장)  — 축별 2개 이상 두고 seed 로 3개 픽
# ──────────────────────────────────────────────────────────────────────────
AXES = {
    "cpu": ["게임성능", "발열", "번들쿨러", "전력효율"],
    "gpu": ["내구성", "발열", "소음", "설치난이도"],
    "ram": ["호환성", "안정성", "오버클럭", "방열판높이"],
    "mainboard": ["BIOS안정성", "VRM발열", "부팅/POST", "부가기능"],
    "ssd": ["순차속도", "발열", "내구성", "호환성"],
    "psu": ["팬소음", "코일소음", "전압안정성", "케이블"],
    "case": ["쿨링", "조립편의", "소음", "마감"],
    "cooler": ["냉각성능", "소음", "설치난이도", "클리어런스"],
}

SUMMARY_POOL = {
    "cpu": [
        ("게임성능", "긍정", "동급에서 프레임이 잘 뽑히고 1% 로우도 안정적이라는 평이 반복됩니다."),
        ("게임성능", "긍정", "게임 위주 사용에서는 상위 라인업과 체감 차이가 크지 않다는 후기가 많습니다."),
        ("발열", "부정", "장시간 풀로드 시 온도가 90도 근처까지 올라 쿨러를 신경 써야 한다는 지적이 반복됩니다."),
        ("발열", "긍정", "전력 제한만 걸어두면 온도와 소음이 확실히 잡힌다는 후기가 많습니다."),
        ("번들쿨러", "부정", "기본 쿨러로는 부족해 사제 쿨러 교체가 사실상 필수라는 후기가 많습니다."),
        ("전력효율", "긍정", "아이들·게임 전력이 낮아 조용하고 발열 관리가 쉽다는 반응이 많습니다."),
    ],
    "gpu": [
        ("소음", "부정", "고부하 게임에서 팬 소음이 확 올라간다는 평이 반복됩니다."),
        ("발열", "긍정", "언더볼팅하면 온도가 크게 떨어지고 정숙해진다는 후기가 많습니다."),
        ("발열", "부정", "케이스 통풍이 나쁘면 핫스팟 온도가 높게 잡힌다는 지적이 있습니다."),
        ("설치난이도", "부정", "3슬롯 두께·긴 길이라 좁은 케이스에서는 간섭이 생긴다는 설치 관련 지적이 있습니다."),
        ("내구성", "긍정", "1년 이상 사용자에서 성능 저하나 코일 노이즈 악화 언급이 거의 없습니다."),
        ("내구성", "긍정", "장기 사용 후에도 초기 성능이 유지된다는 후기가 대부분입니다."),
    ],
    "ram": [
        ("호환성", "부정", "일부 메인보드에서 EXPO/XMP 프로파일이 한 번에 안 잡혀 BIOS 업데이트가 필요했다는 후기가 있습니다."),
        ("안정성", "긍정", "정격·프로파일 모두 장기간 오류 없이 돌아간다는 평이 많습니다."),
        ("오버클럭", "긍정", "표기 클럭보다 조금 더 올려도 안정적이었다는 후기가 있습니다."),
        ("방열판높이", "부정", "방열판이 높아 대형 공랭 쿨러와 간섭될 수 있다는 지적이 있습니다."),
        ("호환성", "긍정", "메인보드 QVL에 올라 있어 설정 없이 바로 잡혔다는 후기가 많습니다."),
    ],
    "mainboard": [
        ("BIOS안정성", "부정", "출고 BIOS로는 최신 세대 CPU 인식이 안 돼 별도 업데이트가 필요했다는 사례가 있습니다."),
        ("VRM발열", "긍정", "고전력 CPU에서도 전원부 온도가 안정적이라는 측정 후기가 많습니다."),
        ("부팅/POST", "부정", "메모리 4개 장착 시 첫 POST가 오래 걸린다는 언급이 반복됩니다."),
        ("부가기능", "긍정", "내장 Wi-Fi·후면 USB 구성이 넉넉해 확장에 불편이 없다는 평이 많습니다."),
        ("BIOS안정성", "긍정", "최근 BIOS는 안정적이고 설정 항목도 직관적이라는 후기가 많습니다."),
    ],
    "ssd": [
        ("순차속도", "긍정", "카탈로그 수치에 근접한 순차 속도가 실사용에서도 나온다는 후기가 많습니다."),
        ("발열", "부정", "히트싱크 없이 쓰면 대용량 쓰기에서 온도가 올라 속도가 떨어진다는 지적이 있습니다."),
        ("내구성", "긍정", "수년 사용자에서 수명 관련 문제 언급이 드뭅니다."),
        ("호환성", "긍정", "메인보드·노트북 모두 인식 문제 없이 바로 잡혔다는 후기가 대부분입니다."),
        ("발열", "긍정", "메인보드 기본 히트싱크만으로도 온도가 무난하다는 후기가 많습니다."),
    ],
    "psu": [
        ("팬소음", "긍정", "중부하까지 팬이 거의 돌지 않아 조용하다는 평이 많습니다."),
        ("코일소음", "부정", "고프레임 상황에서 약한 코일 소음이 들린다는 후기가 일부 있습니다."),
        ("전압안정성", "긍정", "트랜지언트 스파이크가 큰 그래픽카드에서도 셧다운 없이 버틴다는 후기가 많습니다."),
        ("케이블", "부정", "케이블이 짧거나 뻣뻣해 빅타워에서는 선정리가 까다롭다는 지적이 있습니다."),
        ("팬소음", "부정", "팬이 한번 돌기 시작하면 특정 RPM에서 소음이 도드라진다는 후기가 있습니다."),
    ],
    "case": [
        ("쿨링", "긍정", "메쉬 전면 덕에 동일 구성에서 GPU·CPU 온도가 낮게 유지된다는 후기가 많습니다."),
        ("조립편의", "긍정", "선정리 공간과 후면 케이블 채널이 넉넉해 조립이 수월하다는 평이 많습니다."),
        ("소음", "부정", "기본 팬은 최대 RPM에서 풍절음이 있어 교체했다는 후기가 있습니다."),
        ("마감", "긍정", "도장과 패널 결합부 마감이 가격대 대비 좋다는 평이 많습니다."),
        ("쿨링", "부정", "상단·후면 팬을 추가하지 않으면 고사양 구성에서 온도가 아쉽다는 지적이 있습니다."),
    ],
    "cooler": [
        ("냉각성능", "긍정", "동급 공랭 중 온도가 낮은 편이고 소음도 조용하다는 평이 많습니다."),
        ("설치난이도", "부정", "백플레이트 장착이 까다롭고 설명서가 불친절하다는 지적이 반복됩니다."),
        ("클리어런스", "부정", "높이가 있어 일부 미들타워 케이스나 키 큰 RAM과 간섭된다는 후기가 있습니다."),
        ("소음", "긍정", "풀로드에서도 팬 소음이 거슬리지 않는다는 후기가 많습니다."),
        ("냉각성능", "긍정", "고전력 CPU도 전력 제한 없이 상시 사용 가능한 수준이라는 후기가 많습니다."),
    ],
}

SOURCES = [
    ("커뮤니티A", "community", "https://example.com/community-a/thread"),
    ("쇼핑몰B", "marketplace", "https://example.com/mall-b/review"),
    ("블로그C", "blog", "https://example.com/blog-c/post"),
    ("유튜브D", "youtube", "https://example.com/youtube-d/watch"),
]

# AI Hub 원문 참조용 review_id 풀 (원문 미저장, 참조 id 만) — 실제 파일에서 관측된 범위
AIHUB_ID_LO, AIHUB_ID_HI = 119058, 120557


def seeded_rng(product_key: str) -> random.Random:
    h = int(hashlib.sha256(product_key.encode("utf-8")).hexdigest(), 16)
    return random.Random(h)


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w]+", "-", s, flags=re.UNICODE)
    return s.strip("-")


def load_parts() -> list[dict]:
    parts = []
    with PARTS_CSV.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("type,"):
                continue
            row = next(csv.reader([line]))
            if len(row) < 3:
                continue
            parts.append({"type": row[0].strip(), "name": row[1].strip(), "brand": row[2].strip()})
    return parts


# 인기도 가중 (리뷰 수 스케일) — 이름에 특정 토큰 있으면 상향
POPULAR_TOKENS = ["5090", "5080", "5070", "9800X3D", "14600K", "14700K", "990 PRO",
                  "RM750e", "RM850e", "NH-D15", "Peerless Assassin", "North", "H5 Flow",
                  "B760M-A", "TOMAHAWK", "Trident Z5", "RX 9070"]


def gen_one(part: dict) -> dict:
    typ, name = part["type"], part["name"]
    key = slugify(name)
    rng = seeded_rng(key)

    popular = any(tok.lower() in name.lower() for tok in POPULAR_TOKENS)
    base = rng.randint(600, 1600) if popular else rng.randint(90, 700)
    total_reviews = base + rng.randint(-40, 120)

    cleanse_ratio = round(rng.uniform(0.06, 0.24), 3)
    orig_rating = round(rng.uniform(4.15, 4.75), 2)
    drop = round(rng.uniform(0.15, 0.55), 2)
    cleaned_rating = round(max(3.2, orig_rating - drop), 2)
    removed = round(total_reviews * cleanse_ratio)

    # 평점 분포 (제외 전) — 5점 쏠린 곡선
    b5 = rng.randint(52, 64)
    b4 = rng.randint(20, 27)
    b3 = rng.randint(7, 12)
    b2 = rng.randint(3, 7)
    b1 = max(1, 100 - (b5 + b4 + b3 + b2))
    dist_before = [b5, b4, b3, b2, b1]

    # 제외 후 — 조작(대부분 5점) 제거 → 5점 비중 하락, 3~4점·1점으로 재분배
    move = rng.randint(9, 17)
    a4_add = round(move * 0.35)
    a3_add = round(move * 0.30)
    a2_add = round(move * 0.10)
    a1_add = move - a4_add - a3_add - a2_add
    dist_after = [max(1, b5 - move), b4 + a4_add, b3 + a3_add, b2 + a2_add, b1 + a1_add]
    s_after = sum(dist_after)
    dist_after = [round(x / s_after * 100) for x in dist_after]

    # 항목별 평가 (axis_scores) — 축마다 라벨(긍정/부정) + 비율 + 언급수
    axis_scores = {}
    pool = SUMMARY_POOL[typ]
    axis_default_sent = {}
    for a, sent, _ in pool:
        axis_default_sent.setdefault(a, sent)
    for axis in AXES[typ]:
        sent = axis_default_sent.get(axis, rng.choice(["긍정", "부정"]))
        # seed 로 성향 약하게 흔들기
        if rng.random() < 0.15:
            sent = "부정" if sent == "긍정" else "긍정"
        if sent == "긍정":
            pct = rng.randint(58, 92)
        else:
            pct = rng.randint(38, 62)
        mentions = round(total_reviews * rng.uniform(0.12, 0.45))
        axis_scores[axis] = {"label": sent, "pct": pct, "n": mentions}

    # 대표 요약 3건 — 서로 다른 축에서 픽, 출처/수집일 부여
    picks = []
    seen_axes = set()
    cand = pool[:]
    rng.shuffle(cand)
    for axis, sent, text in cand:
        if axis in seen_axes:
            continue
        seen_axes.add(axis)
        src_label, src_type, src_url = rng.choice(SOURCES)
        collected = COLLECT_BASE - timedelta(days=rng.randint(0, 20))
        picks.append({
            "axis": axis,
            "sentiment": sent,
            "text": text,
            "source_label": src_label,
            "source_type": src_type,
            "source_url": src_url,
            "collected_at": collected.isoformat(),
            "orig_refs": sorted(rng.sample(range(AIHUB_ID_LO, AIHUB_ID_HI), k=rng.randint(2, 4))),
        })
        if len(picks) == 3:
            break

    sources = []
    for lbl in sorted({p["source_label"] for p in picks}):
        p = next(pp for pp in picks if pp["source_label"] == lbl)
        sources.append({"label": lbl, "type": p["source_type"], "url": p["source_url"]})

    return {
        "product_key": key,
        "product_name": name,
        "category": typ,
        "brand": part["brand"],
        "total_reviews": total_reviews,
        "removed_count": removed,
        "cleanse_ratio": cleanse_ratio,
        "orig_rating": orig_rating,
        "cleaned_rating": cleaned_rating,
        "rating_dist": {
            "labels": [5, 4, 3, 2, 1],
            "before_pct": dist_before,
            "after_pct": dist_after,
        },
        "axis_scores": axis_scores,
        "top_summaries": picks,
        "sources": sources,
        "corpus_note": "합성 데모 데이터. 평점·조작비율·항목평가·요약은 생성됨. 원문 미저장 / orig_refs 는 AI Hub 상품리뷰 감정데이터(가공) review_id 참조.",
        "collected_at": COLLECT_BASE.isoformat(),
        # 화면이 이 두 필드를 읽어 "합성 데모값" 을 표시한다. cleaned_rating·cleanse_ratio 는
        # 판정기 없이 만든 값이라 실측이 아니고, 실사용자에게 노출하지 않는다 (docs/decisions/0001).
        "is_synthetic": True,
        "cleaned_rating_note": "합성 데모값 — 리뷰 진위 판정기가 없어 실측이 아니다. 실사용자 노출 금지.",
    }


def main() -> int:
    parts = load_parts()
    rows = [gen_one(p) for p in parts]
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_PREVIEW.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_key", "category", "product_name", "total_reviews",
                    "cleanse_ratio", "orig_rating", "cleaned_rating",
                    "axis_1", "axis_2", "axis_3", "axis_4", "summary_1"])
        for r in rows:
            ax = list(r["axis_scores"].items())
            axcells = [f'{k} {v["label"]} {v["pct"]}%' for k, v in ax]
            axcells += [""] * (4 - len(axcells))
            w.writerow([r["product_key"], r["category"], r["product_name"],
                        r["total_reviews"], r["cleanse_ratio"], r["orig_rating"],
                        r["cleaned_rating"], *axcells[:4], r["top_summaries"][0]["text"]])

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["category"]] = by_type.get(r["category"], 0) + 1
    print(f"생성 완료: {len(rows)} products -> {OUT_JSON}")
    print("부품군별:", by_type)
    print(f"미리보기 : {OUT_PREVIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
