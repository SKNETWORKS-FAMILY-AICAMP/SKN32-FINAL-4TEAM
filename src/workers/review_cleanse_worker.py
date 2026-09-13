"""오프라인 리뷰 클렌징 배치 (리뷰 담당 팀원).

수집 → **관계·행동 축 관측**(`relation_axis`) → [진위 라벨 — 미구현] → 평점 재계산 →
임베딩 → 평가축별 대표 리뷰 → 요약 3건 → evidence.review_summary / review_aggregate 저장.
산출물만 저장, 원문 미저장. dataset 의 합성 표본은 운영 집계에 포함하지 않음(C21).

지금 도는 단계는 관계·행동 축 하나다. 그 단계가 내는 것은 점수가 아니라
**상품 단위 관측 사실 + 근거 카드**이고, `product_manipulation_risk` 로 리뷰 단위
판정과 분리해 든다. 텍스트 AI 탐지는 가중치 0 — 사전 조사에서 텍스트 단독 판정이 닫혔고
(오탐 1% 고정에서 최대 37.5%, 문체 하나 바꾸면 0%) LLM 직접 판정은 금지다(사람 50.8% ·
GPT-4o 50.0% 인데 확신 85.6, Hidden Persuaders arXiv 2506.13313).

    # 1) 엣지 표 (표준 라이브러리)
    python scripts/amazon23_edges.py /path/Baby_Products.jsonl --cat baby
    # 2) 관계·행동 축 (pandas·numpy·scipy — `uv sync --group review-analysis`)
    #    자원: Baby 6.0M건 ≈ 3GB·25초, Electronics 43.9M건 ≈ 12GB·6분 (엣지 표 전체를 메모리에 올린다)
    python -m src.workers.review_cleanse_worker data/amazon23/baby_edges.tsv \
        --out data/amazon23/baby_product_risk.json
    # 3) 대조군을 같은 부류로 좁힌다 — PC 부품 데모가 읽는 파일 (config.REVIEW_RISK_JSON)
    python -m src.workers.review_cleanse_worker data/amazon23/electronics_edges.tsv \
        --meta data/amazon23/electronics_meta.tsv --category "Computer Components|Data Storage" \
        --out data/amazon23/pcparts_product_risk.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import DATA_DIR

DEFAULT_EDGES = DATA_DIR / "amazon23" / "baby_edges.tsv"
DEFAULT_OUT = DATA_DIR / "amazon23" / "baby_product_risk.json"


def run(edges: str | Path = DEFAULT_EDGES, out: str | Path = DEFAULT_OUT, **kw) -> dict:
    from src.workers import relation_axis   # 무거운 의존성은 배치 실행 시에만
    return relation_axis.run(edges, out, **kw)


def lookup(key: str, risk_json: str | Path, alias_csv: str | Path | None) -> None:
    """산출 JSON 에서 데모 부품 슬러그(또는 ASIN) 하나의 계약 dict 와 카드를 찍는다. 재계산 없음."""
    import json
    from src.repo.review_repo import ProductRiskStore
    store = ProductRiskStore(risk_json, alias_csv)
    r = store.get_review_authenticity(key)
    print(json.dumps({k: v for k, v in r.items() if k != "product_manipulation_risk"}, ensure_ascii=False, indent=1))
    risk = r["product_manipulation_risk"]
    print(f"\n┌─ {key} → {risk.get('product_ref', key)}   (대조군: {store.meta.get('control_scope')})")
    for e in risk["evidence"]:
        print(f"│   · {e}")
    print("│  랭킹 신호에 걸린 것:", ", ".join(k for k, v, m in store.excess(key) if v >= 2 * m) or "없음")
    print("└─")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edges", nargs="?", default=str(DEFAULT_EDGES))
    ap.add_argument("--lookup", metavar="KEY", default=None,
                    help="배치 대신 산출 JSON 조회 — 데모 부품 슬러그(amd-ryzen-5-5600) 또는 ASIN")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--min-reviews", type=int, default=30, help="산출 JSON 에 넣을 상품의 최소 리뷰 수")
    ap.add_argument("--card-min-reviews", type=int, default=200)
    ap.add_argument("--cards", type=int, default=3, help="그룹당 카드 수")
    ap.add_argument("--meta", default=None, help="scripts/amazon23_meta_slim.py 의 TSV — 대조군 범위를 좁힐 때")
    ap.add_argument("--category", default=None,
                    help="--meta 의 categories 에 대한 정규식. 예: 'Computer Components' (대조군·출력을 이 범위로)")
    a = ap.parse_args()
    if a.lookup:
        from src.config import PARTS_ASIN_MAP, REVIEW_RISK_JSON
        lookup(a.lookup, REVIEW_RISK_JSON if a.out == str(DEFAULT_OUT) else a.out, PARTS_ASIN_MAP)
        return
    kw = dict(min_reviews=a.min_reviews, card_min_reviews=a.card_min_reviews, n_cards=a.cards)
    if a.meta and a.category:
        from src.workers.relation_axis import load_category_filter
        kw["product_filter"] = load_category_filter(a.meta, a.category)
        kw["scope_label"] = a.category
    run(a.edges, a.out, **kw)


if __name__ == "__main__":
    main()
