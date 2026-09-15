#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/baby/review_summaries.json 합성 생성기 — scripts/gen_review_summaries.py(PC용)와 같은 스키마를
유아용품 카탈로그(data/baby/catalog_demo_v1.json)에 맞춰 만든다.

- 입력  : data/baby/catalog_demo_v1.json (유아용품, 18개 품목군 / 188개 레코드)
- 출력  : data/baby/review_summaries.json          (db/seed_review_summaries.py --input 으로 적재)
          data/baby/review_summaries_preview.csv   (사람이 눈으로 확인용)
- 성격  : 데모용. 평점/조작비율/항목별평가/대표요약은 전부 합성. 원문은 저장하지 않음.
- 재현성: product_key 해시 시드 → 재실행해도 동일.

사용:  python scripts/gen_baby_review_summaries.py
"""
from __future__ import annotations
import csv, json, hashlib, random, sys
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
CATALOG_JSON = ROOT / "data" / "baby" / "catalog_demo_v1.json"
OUT_JSON = ROOT / "data" / "baby" / "review_summaries.json"
OUT_PREVIEW = ROOT / "data" / "baby" / "review_summaries_preview.csv"

COLLECT_BASE = date(2026, 9, 1)

# 품목군별 평가축 (카탈로그 category_code 기준, 18개)
AXES = {
    "stroller": ["주행감", "폴딩편의성", "내구성", "통풍성"],
    "car_seat": ["설치편의성", "안전벨트", "통풍성", "인증관련"],
    "carrier": ["착용감", "허리부담", "통풍성", "탈부착편의성"],
    "crib": ["조립편의성", "내구성", "매트리스핏", "마감"],
    "sleepwear": ["보온성", "세탁내구성", "사이즈핏", "촉감"],
    "bottle": ["젖꼭지호환", "세척편의성", "누수", "온도감지"],
    "formula": ["용해성", "맛수용성", "포장편의성", "가격대비량"],
    "high_chair": ["조립편의성", "청소편의성", "높이조절", "안전벨트"],
    "baby_food": ["맛수용성", "포장편의성", "원재료", "농도"],
    "cup": ["누수", "세척편의성", "손잡이", "빨대내구성"],
    "bib": ["방수성", "세탁내구성", "목둘레조절", "촉감"],
    "diaper": ["흡수력", "누기", "피부트러블", "사이즈핏"],
    "wipes": ["두께감", "촉감", "성분자극", "포장밀폐력"],
    "bath": ["미끄럼방지", "온도유지", "수납편의성", "건조편의성"],
    "skincare": ["자극성", "보습력", "향", "펌프사용성"],
    "mat": ["층간소음저감", "청소편의성", "이음새마감", "냄새"],
    "gate": ["설치편의성", "고정력", "내구성", "개폐편의성"],
    "thermometer": ["측정정확도", "반응속도", "사용편의성", "배터리수명"],
}

SUMMARY_POOL = {
    "stroller": [
        ("주행감", "긍정", "바퀴 회전이 부드럽고 방향 전환이 쉽다는 후기가 많습니다."),
        ("주행감", "부정", "요철이 있는 길에서 진동이 그대로 전달된다는 지적이 있습니다."),
        ("폴딩편의성", "긍정", "한 손으로 접고 펼 수 있어 편하다는 평이 많습니다."),
        ("폴딩편의성", "부정", "폴딩 락 위치가 낮아 허리를 숙여야 한다는 불편이 있습니다."),
        ("내구성", "긍정", "1년 이상 사용해도 프레임 흔들림이 없다는 후기가 많습니다."),
        ("통풍성", "부정", "여름철 시트 통풍이 부족해 등에 땀이 찬다는 지적이 있습니다."),
    ],
    "car_seat": [
        ("설치편의성", "긍정", "isofix 고정이 직관적이라 설치가 어렵지 않다는 평이 많습니다."),
        ("설치편의성", "부정", "차종에 따라 안전벨트 각도가 안 맞아 설치에 시간이 걸렸다는 후기가 있습니다."),
        ("안전벨트", "긍정", "5점식 벨트 조절이 쉽고 아이가 답답해하지 않는다는 평이 많습니다."),
        ("통풍성", "부정", "여름에 등받이 쪽이 덥다는 지적이 반복됩니다."),
        ("인증관련", "긍정", "KC 인증 정보가 명확히 표기돼 있어 안심된다는 후기가 많습니다."),
    ],
    "carrier": [
        ("착용감", "긍정", "어깨끈 패딩이 두꺼워 장시간 착용해도 편하다는 평이 많습니다."),
        ("허리부담", "부정", "체중이 늘수록 허리 벨트만으로는 부담이 크다는 지적이 있습니다."),
        ("통풍성", "긍정", "메쉬 소재라 여름에도 덜 덥다는 후기가 많습니다."),
        ("탈부착편의성", "부정", "혼자 아기를 안을 때 버클 위치를 찾기 어렵다는 의견이 있습니다."),
    ],
    "crib": [
        ("조립편의성", "부정", "부품 수가 많아 조립 설명서를 여러 번 봐야 했다는 후기가 있습니다."),
        ("내구성", "긍정", "흔들림 없이 튼튼하다는 평이 많습니다."),
        ("매트리스핏", "긍정", "동봉 매트리스 사이즈가 프레임에 딱 맞는다는 후기가 많습니다."),
        ("마감", "부정", "모서리 마감재가 시간이 지나면 들뜬다는 지적이 일부 있습니다."),
    ],
    "sleepwear": [
        ("보온성", "긍정", "간절기에 이불 대신 입혀도 충분히 따뜻하다는 평이 많습니다."),
        ("세탁내구성", "부정", "여러 번 세탁하면 보풀이 생긴다는 지적이 있습니다."),
        ("사이즈핏", "긍정", "표기 개월수보다 넉넉하게 나와 오래 입힐 수 있다는 후기가 많습니다."),
        ("촉감", "긍정", "속감이 부드러워 아이가 거부감 없이 입는다는 평이 많습니다."),
    ],
    "bottle": [
        ("젖꼭지호환", "부정", "타사 젖꼭지와 호환이 안 돼 세트로만 써야 한다는 불편이 있습니다."),
        ("세척편의성", "긍정", "분해가 쉬워 구석구석 세척하기 편하다는 후기가 많습니다."),
        ("누수", "부정", "외출 시 가방에서 새는 경우가 있었다는 지적이 있습니다."),
        ("온도감지", "긍정", "온도감지 라벨이 정확하다는 평이 많습니다."),
    ],
    "formula": [
        ("용해성", "긍정", "미온수에도 잘 녹아 덩어리가 안 남는다는 후기가 많습니다."),
        ("맛수용성", "부정", "이전 단계에서 바꾸니 처음엔 잘 안 먹었다는 후기가 있습니다."),
        ("포장편의성", "긍정", "1회분 소포장이라 외출할 때 편하다는 평이 많습니다."),
        ("가격대비량", "부정", "용량 대비 가격이 비싸다는 의견이 있습니다."),
    ],
    "high_chair": [
        ("조립편의성", "긍정", "공구 없이도 조립할 수 있어 편했다는 후기가 많습니다."),
        ("청소편의성", "긍정", "식판이 분리돼 물로 바로 씻을 수 있다는 평이 많습니다."),
        ("높이조절", "부정", "단계별 높이 조절 시 소음이 크다는 지적이 있습니다."),
        ("안전벨트", "긍정", "5점식 벨트로 혼자 앉아도 안심된다는 후기가 많습니다."),
    ],
    "baby_food": [
        ("맛수용성", "긍정", "간이 삼삼해 아이가 거부감 없이 먹는다는 평이 많습니다."),
        ("포장편의성", "부정", "파우치 개봉 시 손에 묻는다는 지적이 있습니다."),
        ("원재료", "긍정", "원산지·성분 표기가 상세해서 믿고 먹인다는 후기가 많습니다."),
        ("농도", "부정", "월령별로 농도 편차가 있다는 의견이 일부 있습니다."),
    ],
    "cup": [
        ("누수", "부정", "가방에 넣고 다니면 조금씩 샌다는 후기가 있습니다."),
        ("세척편의성", "긍정", "부품이 단순해 세척과 건조가 편하다는 평이 많습니다."),
        ("손잡이", "긍정", "양손잡이라 아이가 스스로 들기 편하다는 후기가 많습니다."),
        ("빨대내구성", "부정", "빨대 부분을 씹어서 자주 교체해야 한다는 지적이 있습니다."),
    ],
    "bib": [
        ("방수성", "긍정", "이유식이 옷까지 안 튀어 좋다는 후기가 많습니다."),
        ("세탁내구성", "부정", "세탁 후 방수 코팅이 벗겨진다는 지적이 있습니다."),
        ("목둘레조절", "긍정", "단추 단수가 여러 개라 오래 쓸 수 있다는 평이 많습니다."),
        ("촉감", "긍정", "목 안쪽 마감이 부드러워 자국이 안 남는다는 후기가 많습니다."),
    ],
    "diaper": [
        ("흡수력", "긍정", "밤새 착용해도 새지 않는다는 후기가 많습니다."),
        ("누기", "부정", "허벅지 쪽으로 새는 경우가 있다는 지적이 있습니다."),
        ("피부트러블", "긍정", "장시간 착용해도 발진이 덜하다는 평이 많습니다."),
        ("사이즈핏", "부정", "같은 사이즈라도 라인마다 핏이 다르다는 의견이 있습니다."),
    ],
    "wipes": [
        ("두께감", "긍정", "한 장으로도 잘 닦여 도톰하다는 평이 많습니다."),
        ("촉감", "긍정", "부드러워 신생아에게도 자극이 적다는 후기가 많습니다."),
        ("성분자극", "부정", "일부 아이는 트러블이 생겼다는 후기가 있습니다."),
        ("포장밀폐력", "부정", "리필 캡이 헐거워 마른다는 지적이 있습니다."),
    ],
    "bath": [
        ("미끄럼방지", "긍정", "바닥 흡착력이 좋아 안정적이라는 평이 많습니다."),
        ("온도유지", "부정", "물 온도가 금방 식는다는 지적이 있습니다."),
        ("수납편의성", "긍정", "접어서 세워 보관할 수 있어 공간을 덜 차지한다는 후기가 많습니다."),
        ("건조편의성", "부정", "주름 사이에 물기가 남아 곰팡이가 생겼다는 의견이 일부 있습니다."),
    ],
    "skincare": [
        ("자극성", "긍정", "무향·저자극이라 민감한 피부에도 순하다는 후기가 많습니다."),
        ("보습력", "긍정", "건조한 계절에도 트러블 없이 촉촉하다는 평이 많습니다."),
        ("향", "부정", "무향 표기인데 은은한 향이 난다는 의견이 있습니다."),
        ("펌프사용성", "부정", "펌프 용기 배출량이 일정하지 않다는 지적이 있습니다."),
    ],
    "mat": [
        ("층간소음저감", "긍정", "층간소음이 확실히 줄었다는 평이 많습니다."),
        ("청소편의성", "긍정", "이염 없이 물걸레질만으로 관리된다는 후기가 많습니다."),
        ("이음새마감", "부정", "이음새 사이로 이물질이 낀다는 지적이 있습니다."),
        ("냄새", "부정", "초기 냄새가 며칠 간다는 의견이 있습니다."),
    ],
    "gate": [
        ("설치편의성", "부정", "벽 마감재에 따라 압착 고정이 헐거워진다는 지적이 있습니다."),
        ("고정력", "긍정", "아이가 밀어도 흔들리지 않는다는 평이 많습니다."),
        ("내구성", "긍정", "1년 넘게 써도 잠금장치가 헐거워지지 않는다는 후기가 많습니다."),
        ("개폐편의성", "부정", "한 손 개폐가 익숙해지기 전까지는 불편하다는 의견이 있습니다."),
    ],
    "thermometer": [
        ("측정정확도", "긍정", "체온계 두 개로 교차 측정해도 편차가 작다는 후기가 많습니다."),
        ("반응속도", "긍정", "1~2초 내로 빠르게 측정된다는 평이 많습니다."),
        ("사용편의성", "부정", "화면 글씨가 작아 밤에 보기 불편하다는 지적이 있습니다."),
        ("배터리수명", "부정", "배터리가 생각보다 빨리 닳는다는 의견이 있습니다."),
    ],
}

SOURCES = [
    ("커뮤니티A", "community", "https://example.com/community-a/thread"),
    ("쇼핑몰B", "marketplace", "https://example.com/mall-b/review"),
    ("블로그C", "blog", "https://example.com/blog-c/post"),
    ("유튜브D", "youtube", "https://example.com/youtube-d/watch"),
]


def seeded_rng(product_key: str) -> random.Random:
    h = int(hashlib.sha256(product_key.encode("utf-8")).hexdigest(), 16)
    return random.Random(h)


def load_records() -> list[dict]:
    data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    return data["records"]


def gen_one(record: dict) -> dict:
    key = record["product_key"]
    typ = record["category_code"]
    name = record["name"]
    brand = record["brand"]
    rng = seeded_rng(key)

    total_reviews = rng.randint(15, 320)
    cleanse_ratio = round(rng.uniform(0.05, 0.20), 3)
    orig_rating = round(rng.uniform(4.10, 4.70), 2)
    drop = round(rng.uniform(0.10, 0.45), 2)
    cleaned_rating = round(max(3.2, orig_rating - drop), 2)
    removed = round(total_reviews * cleanse_ratio)

    b5 = rng.randint(50, 62)
    b4 = rng.randint(20, 28)
    b3 = rng.randint(7, 13)
    b2 = rng.randint(3, 7)
    b1 = max(1, 100 - (b5 + b4 + b3 + b2))
    dist_before = [b5, b4, b3, b2, b1]

    move = rng.randint(8, 16)
    a4_add = round(move * 0.35)
    a3_add = round(move * 0.30)
    a2_add = round(move * 0.10)
    a1_add = move - a4_add - a3_add - a2_add
    dist_after = [max(1, b5 - move), b4 + a4_add, b3 + a3_add, b2 + a2_add, b1 + a1_add]
    s_after = sum(dist_after)
    dist_after = [round(x / s_after * 100) for x in dist_after]

    axis_scores = {}
    pool = SUMMARY_POOL[typ]
    axis_default_sent = {}
    for a, sent, _ in pool:
        axis_default_sent.setdefault(a, sent)
    for axis in AXES[typ]:
        sent = axis_default_sent.get(axis, rng.choice(["긍정", "부정"]))
        if rng.random() < 0.15:
            sent = "부정" if sent == "긍정" else "긍정"
        pct = rng.randint(58, 92) if sent == "긍정" else rng.randint(38, 62)
        mentions = round(total_reviews * rng.uniform(0.12, 0.45))
        axis_scores[axis] = {"label": sent, "pct": pct, "n": mentions}

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
            "axis": axis, "sentiment": sent, "text": text,
            "source_label": src_label, "source_type": src_type, "source_url": src_url,
            "collected_at": collected.isoformat(), "orig_refs": [],
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
        "brand": brand,
        "total_reviews": total_reviews,
        "removed_count": removed,
        "cleanse_ratio": cleanse_ratio,
        "orig_rating": orig_rating,
        "cleaned_rating": cleaned_rating,
        "rating_dist": {"labels": [5, 4, 3, 2, 1], "before_pct": dist_before, "after_pct": dist_after},
        "axis_scores": axis_scores,
        "top_summaries": picks,
        "sources": sources,
        "corpus_note": "합성 데모 데이터. 평점·조작비율·항목평가·요약은 생성됨. 원문 미저장.",
        "collected_at": COLLECT_BASE.isoformat(),
        "is_synthetic": True,
        "cleaned_rating_note": "합성 데모값 — 리뷰 진위 판정기가 없어 실측이 아니다. 실사용자 노출 금지.",
    }


def main() -> int:
    records = load_records()
    rows = [gen_one(r) for r in records]
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
    print("품목군별:", by_type)
    print(f"미리보기 : {OUT_PREVIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
