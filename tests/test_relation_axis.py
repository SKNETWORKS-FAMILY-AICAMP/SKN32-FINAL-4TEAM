"""관계·행동 축 스모크 — 작은 엣지 표로 배치 → JSON → 계약 리더까지.

pandas 가 없는 환경(API 전용 venv)에서는 건너뛴다. 배치 의존성은 배치에서만.
"""
import json

import pytest

pd = pytest.importorskip("pandas")

from src.repo.review_repo import ProductRiskStore          # noqa: E402
from src.workers import relation_axis                     # noqa: E402

DAY = relation_axis.DAY_MS


def _edges(tmp_path):
    """상품 BURST: 60건 중 40건이 첫 주(출시) · 리뷰어 절반이 QUIET 에도 등장.
    상품 QUIET: 60건이 1년에 고르게 · 계정 전부 1건뿐.
    상품 LATE: 첫 리뷰 후 300일 뒤 한 주에 40건 — 출시가 아닌 몰림."""
    rows = []
    for i in range(60):
        day = 100 + (i % 7 if i < 40 else 20 * i)          # 앞 40건은 7일 창 안
        rows.append((f"u{i}", "BURST", day * DAY, 5, 0))
    for i in range(60):
        uid = f"u{i}" if i < 30 else f"q{i}"                # 앞 30명은 BURST 와 공유
        rows.append((uid, "QUIET", (200 + 6 * i) * DAY, 4 if i % 2 else 5, 1))
    for i in range(60):
        day = 100 + (400 + i % 7 if i < 40 else 5 * i)     # 첫 리뷰 day 100, 몰림은 day 500 주
        rows.append((f"l{i}", "LATE", day * DAY, 5, 0))
    p = tmp_path / "edges.tsv"
    with open(p, "w") as f:
        f.write("user_id\tparent_asin\tts_ms\trating\tverified\thelpful\tn_img\ttext_len\n")
        for u, a, ts, r, v in rows:
            f.write(f"{u}\t{a}\t{ts}\t{r}\t{v}\t0\t0\t10\n")
    return p


def test_batch_produces_observations_not_scores(tmp_path):
    out = tmp_path / "risk.json"
    res = relation_axis.run(_edges(tmp_path), out, min_reviews=10, card_min_reviews=10,
                            n_cards=1, log=lambda *_: None)
    pf = res["products"]
    assert pf["BURST"]["burst7"] > pf["QUIET"]["burst7"] and pf["LATE"]["burst7"] == pytest.approx(40 / 60, abs=1e-3)
    assert pf["BURST"]["burst7"] == pytest.approx(40 / 60, abs=1e-3)   # JSON 은 소수 4자리
    assert pf["BURST"]["shared_reviewers"] == 30 and pf["BURST"]["deg"] == 1
    assert pf["QUIET"]["one_off_rate"] == pytest.approx(0.5)       # q* 30명은 1건뿐
    assert res["meta"]["labels"] is None                            # 라벨 없음을 명시
    card = res["cards"]["burst_top"][0]
    assert card["product_key"] == "BURST"
    assert "score" not in card and card["controls"]["burst7"] > 0
    assert any("7일 안에 몰림" in o for o in card["observations"])
    assert json.loads(out.read_text())["controls"] == res["controls"]


def test_store_keeps_cleaned_rating_empty(tmp_path):
    out = tmp_path / "risk.json"
    relation_axis.run(_edges(tmp_path), out, min_reviews=10, card_min_reviews=10,
                      n_cards=1, log=lambda *_: None)
    store = ProductRiskStore(out)
    r = store.get_review_authenticity("BURST")
    assert r["cleaned_rating"] is None and r["cleanse_ratio"] is None
    assert r["orig_rating"] == 5.0 and r["total_reviews"] == 60
    risk = r["product_manipulation_risk"]
    assert risk["score"] is None and len(risk["evidence"]) >= 3 and risk["reliable_range"] is True
    missing = store.get_review_authenticity("NOPE")
    assert missing["total_reviews"] == 0 and missing["product_manipulation_risk"]["evidence"] == []
