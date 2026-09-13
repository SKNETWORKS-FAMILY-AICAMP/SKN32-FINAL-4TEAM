"""[3-B] 리뷰축이 관측을 어떻게 읽는가 — 판정하지 않고 가중치만.

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




def test_rank_review_axis_uses_store_without_judging(tmp_path, monkeypatch):
    """[3-B] 리뷰축: 관측 없음 0.5 · 관측됨 0.75 · 중앙값 2배 초과 0.25. 출시 첫 주 몰림은 안 센다."""
    from src.dto import Candidate
    from src.engine import stage3b_rank as rk
    from src.repo import review_repo

    out = tmp_path / "risk.json"
    relation_axis.run(_edges(tmp_path), out, min_reviews=10, card_min_reviews=10,
                      n_cards=1, log=lambda *_: None)
    store = ProductRiskStore(out)
    store.controls.update({"burst7": 0.05, "one_off_rate": 0.1, "prolific_rate": 0.05})
    monkeypatch.setattr(review_repo, "_default_store", store)
    monkeypatch.setattr(review_repo, "_default_store_tried", True)

    # BURST: 몰림 67% 지만 첫 주(출시)라 랭킹 신호에서 빠진다 → 관측됨·특이 없음
    assert "burst7" not in [k for k, _, _ in store.excess("BURST")]
    v, flags = rk._review_axis(Candidate(product_key="BURST", slot="X", name="b"))
    assert v == rk._REVIEW_CLEAR and flags == ["REVIEW_OBS:observed"]
    # 1건 계정 비율은 랭킹 신호가 아니다 — QUIET 는 50% 인데(중앙값 10%의 5배) 걸리지 않는다
    v, flags = rk._review_axis(Candidate(product_key="QUIET", slot="X", name="q"))
    assert v == rk._REVIEW_CLEAR and "one_off_rate" not in [k for k, _, _ in store.excess("QUIET")]
    # LATE: 출시 300일 뒤 한 주에 67% → 검토 필요. 이유가 flags 에 남는다
    v, flags = rk._review_axis(Candidate(product_key="LATE", slot="X", name="l"))
    assert v == rk._REVIEW_FLAGGED and flags and flags[0].startswith("REVIEW_OBS:burst7=")
    # 데이터에 없는 상품: 모름 = 0.5, 감점 없음
    assert rk._review_axis(Candidate(product_key="NOPE", slot="X", name="n")) == (rk._REVIEW_UNKNOWN, [])
