"""카테고리 정의 파일 로더.

config/categories/<category>.yaml 을 읽어 슬롯 구조·필수 입력·질문 세트·기본값·검증 분기를
제공한다. 엔진 코드에 `if category == "computer"` 를 하드코딩하지 않고 전부 이 정의를 통해 분기한다.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from src.config import CATEGORY_DIR


@lru_cache(maxsize=8)
def load_category(category: str) -> dict:
    """카테고리 정의 dict 반환.

    Returns keys: category, label, modes, required_inputs, slot_structure,
    slot_schema, defaults, question_sets, verify_branch(set|per_item), status(optional).
    """
    path = CATEGORY_DIR / f"{category}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"카테고리 정의 없음: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def verify_branch(category: str) -> str:
    """'set' = [4]→[3-C] (컴퓨터) / 'per_item' = [3-C]→[4] (유아)."""
    return load_category(category)["verify_branch"]
