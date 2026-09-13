"""관계·행동 축 — 리뷰어–상품 그래프에서 관측 사실을 뽑는다. 본문은 한 글자도 보지 않는다.

리뷰 클렌징 배치(`review_cleanse_worker`)의 한 단계. 입력은 `scripts/amazon23_edges.py`
가 만든 엣지 표(user_id · parent_asin · ts_ms · rating · verified …)이고, 출력은
**상품 단위 관측 사실**과 그것을 사람이 읽는 **근거 카드**다.

설계 원칙 — 리뷰 탐지 사전 조사에서 그대로 가져온 것:

- **점수를 내지 않는다.** 조작 라벨이 없는 데이터라 탐지율·오탐률을 잴 수 없고,
  라벨이 있어도 카드에 실리는 것은 "7일 몰림 29% (전체 중앙값 11%)" 같은
  **확인·반박 가능한 관측 사실**이지 점수가 아니다. 점수는 반박할 수 없다.
- **상품 단위 신호는 리뷰 단위와 분리한다.** "상품이 의심스럽다"는 이유로 그 상품의
  리뷰를 전부 가짜로 보지 않는다. 출력 키가 `product_manipulation_risk` 인 이유.
- **대조군을 항상 옆에 둔다.** 전체 상품 중앙값이 없으면 29% 가 높은지 낮은지 모른다.
- **계정 단위 특징은 정의되는 범위를 명시한다.** 계정당 리뷰 중앙값이 1이라
  간격·신규성은 소수 계정에서만 성립한다. 성립하지 않는 것을 0 으로 채우지 않는다.

의존성: pandas · numpy · scipy (오프라인 배치 전용. API 경로는 산출 JSON 만 읽는다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

DAY_MS = 86_400_000
BURST_WINDOW_DAYS = 7
NEW_ACCOUNT_SPAN_DAYS = 30      # 활동 기간이 이보다 짧으면 "단기 활동 계정"
PROLIFIC_MIN_REVIEWS = 30       # 다작 계정 문턱 — 사전 조사에서 구매 확인율이 유일하게 갈린 계층(30건+)
GAP_MIN_REVIEWS = 3             # 간격 특징이 정의되려면 리뷰 3건 이상 (게이트 Q3)

# 카드에 중앙값을 병기하는 지표
CONTROL_KEYS = ("n", "p5", "mean_rating", "burst7", "one_off_rate", "short_span_rate",
                "prolific_rate", "verified_rate", "deg", "shared_reviewers")


# ─────────────────────────────────────────────────────────────────────────────
# 입력
# ─────────────────────────────────────────────────────────────────────────────
def load_edges(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", dtype={"user_id": "string", "parent_asin": "string"})
    df["day"] = (df.ts_ms // DAY_MS).astype(np.int64)
    df["rating"] = pd.to_numeric(df.rating, errors="coerce")
    return df.dropna(subset=["rating"])


# ─────────────────────────────────────────────────────────────────────────────
# 계정 단위
# ─────────────────────────────────────────────────────────────────────────────
def reviewer_features(df: pd.DataFrame) -> pd.DataFrame:
    """계정당 n · 5점 비율 · 활동 기간 · 리뷰 간 간격(중앙값·변동계수).

    간격은 리뷰 3건 이상에서만 정의된다. 미정의는 NaN 으로 둔다 — 0 으로 채우면
    "간격이 0 = 자동" 으로 읽혀 신호가 뒤집힌다.
    """
    s = df.sort_values(["user_id", "day"], kind="stable").assign(is5=lambda x: x.rating == 5)
    g = s.groupby("user_id", sort=False)
    f = pd.DataFrame({
        "n": g.size(),
        "p5": g.is5.mean(),
        "first_day": g.day.min(),
        "last_day": g.day.max(),
        "n_products": g.parent_asin.nunique(),
    })
    f["span_days"] = f.last_day - f.first_day
    # 간격: 같은 계정 안에서의 day 차이. 계정 경계는 diff 가 NaN.
    gap = s.groupby("user_id", sort=False).day.diff()
    s = s.assign(gap=gap)
    gg = s.dropna(subset=["gap"]).groupby("user_id", sort=False).gap
    f["gap_med"] = gg.median()
    f["gap_cv"] = (gg.std() / gg.mean()).replace([np.inf, -np.inf], np.nan)
    f.loc[f.n < GAP_MIN_REVIEWS, ["gap_med", "gap_cv"]] = np.nan
    return f


# ─────────────────────────────────────────────────────────────────────────────
# 상품 단위
# ─────────────────────────────────────────────────────────────────────────────
def _burst7(df: pd.DataFrame) -> pd.DataFrame:
    """상품별 — 임의의 7일 창에 들어가는 리뷰의 최대 비율과 그 창의 시작일.

    (상품, 날짜) 로 정렬한 뒤 키 = 상품코드×BIG + 날짜 로 만들면, 같은 상품 안에서
    날짜+7 미만인 행의 수를 searchsorted 한 번으로 얻는다. 파이썬 루프 없음.
    """
    s = df[["parent_asin", "day"]].sort_values(["parent_asin", "day"], kind="stable")
    codes, uniques = pd.factorize(s.parent_asin, sort=False)
    day = s.day.to_numpy()
    big = int(day.max()) + BURST_WINDOW_DAYS + 1
    key = codes.astype(np.int64) * big + day
    right = np.searchsorted(key, key + BURST_WINDOW_DAYS, side="left")
    cnt = right - np.arange(len(key))
    t = pd.DataFrame({"code": codes, "day": day, "cnt": cnt})
    idx = t.groupby("code", sort=False).cnt.idxmax()
    best = t.loc[idx].set_index("code")
    n = t.groupby("code", sort=False).size()
    out = pd.DataFrame({
        "burst7": best.cnt / n,
        "burst7_start_day": best.day,
        "burst7_count": best.cnt,
    })
    out.index = uniques[out.index]
    return out


def _product_graph(df: pd.DataFrame, rf: pd.DataFrame):
    """리뷰어를 공유하는 상품–상품 그래프. 리뷰어 2상품 이상만 엣지를 만든다.

    반환: (P, products) — P[i, j] = 상품 i·j 를 둘 다 리뷰한 계정 수 (i==j 는 공유 계정 수).
    """
    multi = rf.index[rf.n_products >= 2]
    e = df[df.user_id.isin(multi)][["user_id", "parent_asin"]].drop_duplicates()
    pcode, products = pd.factorize(e.parent_asin, sort=True)
    ucode, _ = pd.factorize(e.user_id, sort=False)
    B = sparse.csr_matrix((np.ones(len(e), dtype=np.int32), (pcode, ucode)))
    P = (B @ B.T).tocsr()
    return P, products


def product_features(df: pd.DataFrame, rf: pd.DataFrame,
                     P: sparse.csr_matrix, products: pd.Index) -> pd.DataFrame:
    """상품별 관측 사실. 전부 '비율' 또는 '건수' — 해석에 모델이 필요 없는 값만."""
    d = df.merge(rf[["n", "span_days"]].rename(columns={"n": "acct_n"}),
                 left_on="user_id", right_index=True, how="left")
    d["is5"] = d.rating == 5
    d["is1"] = d.rating == 1
    d["one_off"] = d.acct_n == 1
    d["short_span"] = (d.acct_n >= 2) & (d.span_days <= NEW_ACCOUNT_SPAN_DAYS)
    d["prolific"] = d.acct_n >= PROLIFIC_MIN_REVIEWS
    g = d.groupby("parent_asin", sort=False)
    pf = pd.DataFrame({
        "n": g.size(),
        "n_reviewers": g.user_id.nunique(),
        "mean_rating": g.rating.mean(),
        "p5": g.is5.mean(),
        "p1": g.is1.mean(),
        "verified_rate": g.verified.mean(),
        "one_off_rate": g.one_off.mean(),        # 이 상품 리뷰 중 '데이터 전체에서 1건뿐인 계정' 비율
        "short_span_rate": g.short_span.mean(),  # 활동 기간 30일 이하 계정(2건+) 비율
        "prolific_rate": g.prolific.mean(),      # 다작 30건+ 계정 비율
        "first_day": g.day.min(),
        "last_day": g.day.max(),
    })
    pf = pf.join(_burst7(df))

    diag = P.diagonal()
    deg = np.diff(P.indptr) - (diag > 0).astype(np.int64)      # 자기 자신 제외
    wdeg = np.asarray(P.sum(axis=1)).ravel() - diag
    gf = pd.DataFrame({"shared_reviewers": diag, "deg": deg, "wdeg": wdeg}, index=products)
    pf = pf.join(gf).fillna({"shared_reviewers": 0, "deg": 0, "wdeg": 0})
    pf["deg_norm"] = pf.deg / pf.n
    return pf


def neighbor_density(P: sparse.csr_matrix, products: pd.Index, asin: str) -> float:
    """연결된 상품들끼리도 리뷰어를 공유하는 비율 (국소 군집 계수). 카드용 — 상품 하나씩."""
    pos = products.get_indexer([asin])[0]
    if pos < 0:
        return 0.0
    row = P.getrow(pos)
    nb = row.indices[row.indices != pos]
    k = len(nb)
    if k < 2:
        return 0.0
    sub = P[nb][:, nb]
    e = (sub.nnz - int((sub.diagonal() > 0).sum())) / 2
    return float(2 * e / (k * (k - 1)))


# ─────────────────────────────────────────────────────────────────────────────
# 근거 카드
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class EvidenceCard:
    """검토자가 읽는 카드. 점수 없음. 관측 사실 + 대조군 + 확인 경로 + 이 신호가 말하지 않는 것."""
    product_key: str
    n_reviews: int
    n_reviewers: int
    mean_rating: float
    observations: list[str] = field(default_factory=list)     # 사람이 읽는 문장
    facts: dict = field(default_factory=dict)                  # 같은 내용의 숫자
    controls: dict = field(default_factory=dict)               # 전체 상품 중앙값
    verify_paths: dict = field(default_factory=dict)           # 클릭 한 번으로 원본에 닿는 경로
    scope_note: str = ("이것은 상품 단위 신호다. 이 상품의 개별 리뷰가 가짜라는 뜻이 아니다. "
                       "조작 라벨이 없는 데이터라 탐지율·오탐률은 잴 수 없고, 값은 관측 사실이다.")
    label: str | None = None                                   # 실측 라벨이 있는 데이터에서만


def _day_str(day: int) -> str:
    return str(pd.Timestamp(int(day), unit="D").date())


def make_card(asin: str, pf: pd.DataFrame, controls: dict, df: pd.DataFrame,
              P: sparse.csr_matrix, products: pd.Index) -> EvidenceCard:
    r = pf.loc[asin]
    n = int(r.n)
    dens = neighbor_density(P, products, asin)
    bs, be = int(r.burst7_start_day), int(r.burst7_start_day) + BURST_WINDOW_DAYS
    rows = df[df.parent_asin == asin]
    burst_users = rows[(rows.day >= bs) & (rows.day < be)].user_id.unique().tolist()

    obs = [
        f"리뷰 {n}건 중 {int(r.burst7_count)}건({100*r.burst7:.1f}%)이 {_day_str(bs)}~{_day_str(be)} 7일 안에 몰림"
        f" — 전체 상품 중앙값 {100*controls['burst7']:.1f}%",
        f"리뷰어 {int(r.shared_reviewers)}명이 다른 상품에서도 함께 나타남 (연결 상품 {int(r.deg)}개)"
        f" — 중앙값 {controls['shared_reviewers']:.0f}명 / {controls['deg']:.0f}개",
        f"연결된 상품들끼리도 리뷰어를 공유하는 비율 {dens:.2f}",
        f"5점 비율 {100*r.p5:.0f}% — 중앙값 {100*controls['p5']:.0f}%",
        f"데이터 전체에서 리뷰가 이 한 건뿐인 계정 {100*r.one_off_rate:.0f}% — 중앙값 {100*controls['one_off_rate']:.0f}%",
        f"활동 기간 30일 이하 계정 {100*r.short_span_rate:.0f}% · 다작 30건+ 계정 {100*r.prolific_rate:.0f}%"
        f" — 중앙값 {100*controls['short_span_rate']:.0f}% / {100*controls['prolific_rate']:.0f}%",
        f"구매 확인 {100*r.verified_rate:.0f}% — 중앙값 {100*controls['verified_rate']:.0f}%"
        " (양방향 모두 증거 아님)",
    ]
    facts = {k: (float(r[k]) if k in r else None) for k in CONTROL_KEYS}
    facts.update({"burst7_start": _day_str(bs), "burst7_count": int(r.burst7_count),
                  "neighbor_density": dens, "n_reviewers": int(r.n_reviewers)})
    return EvidenceCard(
        product_key=asin, n_reviews=n, n_reviewers=int(r.n_reviewers),
        mean_rating=round(float(r.mean_rating), 2),
        observations=obs, facts=facts, controls=controls,
        verify_paths={
            "product_url": f"https://www.amazon.com/dp/{asin}",
            "burst_window": [_day_str(bs), _day_str(be)],
            "burst_reviewers": burst_users[:50],
            "connected_products": [str(x) for x in
                                   products[P.getrow(products.get_indexer([asin])[0]).indices][:50]
                                   if str(x) != asin],
        },
    )


def render_card(c: EvidenceCard) -> str:
    head = f"┌─ 상품 {c.product_key}" + (f"   [실측 라벨: {c.label}]" if c.label else "")
    lines = [head,
             f"│  리뷰 {c.n_reviews}건 · 리뷰어 {c.n_reviewers}명 · 평점 {c.mean_rating:.2f}",
             "│", "│  [관측 사실]"]
    lines += [f"│   · {o}" for o in c.observations]
    lines += ["│", f"│  확인: {c.verify_paths.get('product_url', '')}",
              f"│  ※ {c.scope_note}", "└─"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 배치 진입점
# ─────────────────────────────────────────────────────────────────────────────
def load_category_filter(meta_tsv: str | Path, pattern: str) -> set[str]:
    """`scripts/amazon23_meta_slim.py` 의 TSV 에서 categories 가 패턴에 맞는 ASIN 집합."""
    m = pd.read_csv(meta_tsv, sep="\t", dtype="string", usecols=["parent_asin", "categories"])
    hit = m[m.categories.fillna("").str.contains(pattern, case=False, regex=True)]
    return set(hit.parent_asin.dropna())


def run(edges_path: str | Path, out_json: str | Path, *, min_reviews: int = 30,
        card_min_reviews: int = 200, n_cards: int = 3, log=print,
        product_filter: set[str] | None = None, scope_label: str | None = None) -> dict:
    """엣지 표 → 상품 특징 + 근거 카드 JSON.

    반환 dict 가 곧 JSON 내용이다:
      meta      데이터 규모 · 계정 단위 특징의 정의 비율(Q3) · 대조군 범위
      controls  대조군 중앙값 — product_filter 가 있으면 **그 범위 안의** 상품 중앙값
      products  {asin: facts}  — min_reviews 이상 (product_filter 안의) 상품만
      cards     몰림 상위 / 연결 상위 / 대조 하위 카드

    **대조군은 같은 부류의 상품이어야 한다.** Electronics 전체 중앙값을 PC 부품에 대면 다작
    계정 비율(4.4%)이 PC 부품에서는 일상적으로 2~3배라 절반이 "검토 필요" 로 찍힌다 — 조작이
    아니라 PC 조립자가 부품을 여러 번 산다는 사실이다. 사전 조사가 잰 도메인 전이 비대칭
    (유아용품↔전자 사이에서도 임계값이 옮겨지지 않았다)의 교훈 그대로다. 특징은 전체 그래프에서 계산하고(다른 부류 상품과의 연결도 실제 연결이다),
    중앙값과 출력만 범위를 좁힌다.
    """
    log(f"[관계·행동] 엣지 읽는 중: {edges_path}")
    df = load_edges(edges_path)
    log(f"  리뷰 {len(df):,} · 계정 {df.user_id.nunique():,} · 상품 {df.parent_asin.nunique():,}")

    rf = reviewer_features(df)
    q3 = {
        "median_reviews_per_account": float(rf.n.median()),
        "accounts_ge3_share": float((rf.n >= GAP_MIN_REVIEWS).mean()),
        "reviews_from_accounts_ge3_share": float(rf.n[rf.n >= GAP_MIN_REVIEWS].sum() / rf.n.sum()),
        "gap_defined_share": float(rf.gap_med.notna().mean()),
    }
    log(f"  [Q3] 계정당 중앙값 {q3['median_reviews_per_account']:.0f} · 3건+ 계정 {100*q3['accounts_ge3_share']:.1f}%"
        f" · 간격 특징 정의 {100*q3['gap_defined_share']:.1f}%")

    P, products = _product_graph(df, rf)
    log(f"  상품 그래프: 노드 {len(products):,} · 공유 엣지 {(P.nnz - len(products)) // 2:,}")
    pf = product_features(df, rf, P, products)

    big = pf[pf.n >= min_reviews]
    if product_filter is not None:
        big = big[big.index.isin(product_filter)]
        log(f"  대조군 범위: {scope_label or 'filter'} — 상품 {len(product_filter):,}개 중 리뷰 {min_reviews}건+ {len(big):,}개")
    controls = {k: float(big[k].median()) for k in CONTROL_KEYS}
    log(f"  대조군(리뷰 {min_reviews}건+ 상품 {len(big):,}개 중앙값): "
        + " · ".join(f"{k} {v:.3g}" for k, v in controls.items()))

    cand = big[big.n >= card_min_reviews]
    picks = {
        "burst_top": cand.sort_values("burst7", ascending=False).index[:n_cards],
        "graph_top": cand.sort_values("deg_norm", ascending=False).index[:n_cards],
        "control_low": cand.sort_values("burst7").index[:n_cards],
    }
    cards = {}
    for group, idx in picks.items():
        cards[group] = [asdict(make_card(a, pf, controls, df, P, products)) for a in idx]
        for c in cards[group]:
            log(f"\n[{group}]\n" + render_card(EvidenceCard(**c)))

    out = {
        "meta": {
            "source": str(edges_path), "n_reviews": int(len(df)),
            "n_accounts": int(df.user_id.nunique()), "n_products": int(df.parent_asin.nunique()),
            "min_reviews": min_reviews, "labels": None,
            "control_scope": scope_label or "all",
            "q3": q3,
            "note": "조작 라벨 없음. 값은 전부 관측 사실이며 탐지 성능이 아니다. "
                    "절대 수치를 다른 언어·도메인·내부 데이터로 옮기지 않는다.",
        },
        "controls": controls,
        "products": {a: {k: (None if pd.isna(v) else (int(v) if isinstance(v, (np.integer,)) else float(v)))
                         for k, v in row.items()}
                     for a, row in big.round(4).iterrows()},
        "cards": cards,
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"\n→ {out_json}  (상품 {len(big):,}개 · 카드 {sum(len(v) for v in cards.values())}장)")
    return out
