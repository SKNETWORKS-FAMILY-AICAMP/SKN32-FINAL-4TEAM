"""컴퓨터 부품 카탈로그 읽기 ([3-0] 후보 수집이 사용).

데모: data/parts_list.csv (부품 마스터) 를 읽고, 스펙/가격이 비어 있는 필드는
결정적 목값으로 채워 후보로 낸다. 실제 스펙·시세는 이후 parts_catalog.csv +
gen_parts_offers.py 로 대체한다 (기획서 §15-3 하이브리드).
"""
from __future__ import annotations

import csv
import hashlib
from functools import lru_cache

from src.config import DATA_DIR
from src.dto import Candidate

_CSV = DATA_DIR / "parts_list.csv"

# 부품군 → 리스트 패널 슬롯 이름
TYPE_TO_SLOT = {
    "cpu": "CPU", "gpu": "GPU", "ram": "RAM", "mainboard": "메인보드",
    "ssd": "저장장치", "psu": "파워", "case": "케이스", "cooler": "쿨러",
}

# 슬롯별 대표 시세(원) — base_price. 데모용 근사값, 지터는 _mock_price 가 부여.
_BASE_PRICE = {
    "CPU": 300_000, "GPU": 700_000, "RAM": 130_000, "메인보드": 220_000,
    "저장장치": 120_000, "파워": 110_000, "케이스": 90_000, "쿨러": 60_000,
}


def _seed(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def _mock_price(product_key: str, slot: str) -> int:
    base = _BASE_PRICE.get(slot, 100_000)
    jitter = (_seed(product_key) % 60) - 25          # -25% ~ +34%
    return int(base * (1 + jitter / 100) // 1000 * 1000)


def _mock_tier(product_key: str) -> int:
    return 3 + _seed(product_key + "tier") % 7        # 3~9


@lru_cache(maxsize=1)
def _load_rows() -> list[dict]:
    rows: list[dict] = []
    with _CSV.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("type,"):
                continue
            r = next(csv.reader([line]))
            if len(r) < 3:
                continue
            rows.append({"type": r[0].strip(), "name": r[1].strip(), "brand": r[2].strip()})
    return rows


def load_candidates_by_slot() -> dict[str, list[Candidate]]:
    """슬롯별 후보 리스트 (판정 전, verdict='Pass' 기본)."""
    out: dict[str, list[Candidate]] = {}
    for row in _load_rows():
        slot = TYPE_TO_SLOT.get(row["type"])
        if slot is None:
            continue
        pk = row["name"].lower().replace(" ", "-")
        cand = Candidate(
            product_key=pk,
            slot=slot,
            name=row["name"],
            brand=row["brand"],
            price=_mock_price(pk, slot),
            specs={"perf_tier": _mock_tier(pk)},   # TODO: 실제 스펙으로 교체
        )
        out.setdefault(slot, []).append(cand)
    return out
