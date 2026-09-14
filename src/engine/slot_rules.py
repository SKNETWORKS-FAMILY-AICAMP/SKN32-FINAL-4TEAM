"""자유 입력 → 조건 필드 규칙 기반 추출 ([1] 의도 분해, LLM 미사용).

`POST /session/{id}/message`가 호출한다. 칩 선택(`/answer`)은 `question_sets.maps_to`로
직접 반영되므로 여기서 다루지 않는다 — 이 모듈은 자유 텍스트 파싱만 담당한다.
반환값은 매칭된 필드만 담은 dict (매칭 안 되면 빈 dict) — 호출 쪽이 기존 값 위에 병합한다.
"""
from __future__ import annotations

import re

_WON = re.compile(r"(\d+(?:[.,]\d+)?)\s*억|(\d+(?:[.,]\d+)?)\s*(?:천만|천\s*만)|(\d+(?:[.,]\d+)?)\s*만|(\d{2,})\s*원?")


def _parse_won(text: str) -> int | None:
    """'150만원', '₩1,500,000', '1.5 million won' 같은 표현 → 정수 원."""
    text = text.replace(",", "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*억", text)
    if m:
        return int(float(m.group(1)) * 100_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*천\s*만", text)
    if m:
        return int(float(m.group(1)) * 10_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*만\s*원?", text)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.search(r"(\d{4,})\s*원", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:₩|krw\s*)(\d{4,})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(million|thousand|m|k)\s*(?:won|krw)?\b", text)
    if m:
        multiplier = 1_000_000 if m.group(2) in {"million", "m"} else 1_000
        return int(float(m.group(1)) * multiplier)
    m = re.search(r"(\d{4,})\s*(?:won|krw)\b", text)
    if m:
        return int(m.group(1))
    return None


def _parse_months(text: str) -> int | None:
    m = re.search(r"(\d+)\s*개?\s*월", text)
    if m:
        return int(m.group(1))
    if re.search(r"출산\s*예정|임신|태어나기\s*전", text):
        return None
    m = re.search(r"(\d+)\s*(?:months?|mos?|mo)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:years?|yrs?|yr)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 12
    return None


_PURPOSE = [
    ("game", ["게임", "롤", "옵치", "배그", "발로란트", "game", "gaming", "esports"]),
    ("creation", ["작업", "창작", "편집", "영상", "디자인", "3d", "렌더", "creator", "editing", "video", "render", "design"]),
    ("office", ["사무", "문서", "엑셀", "인터넷", "office", "work", "spreadsheet", "browsing"]),
    ("study", ["공부", "학습", "온라인 강의", "인강", "study", "school", "class", "lecture"]),
]

_PRIORITY = [
    ("performance", ["성능", "빠른", "고사양", "performance", "fast", "high-end", "fps"]),
    ("value", ["가성비", "저렴", "싸게", "가격", "value", "budget", "affordable", "cheap"]),
    ("quiet", ["조용", "저소음", "소음", "quiet", "silent", "low noise"]),
]

# 키워드 → baby.yaml/CONTRACTS 의 정식 need 라벨(부분 문자열이 아니라 그대로 저장 가능한 값).
_NEEDS_MAP: list[tuple[str, list[str]]] = [
    ("수유", ["수유", "젖병", "분유"]),
    ("이유식·식사", ["이유식", "식사"]),
    ("수면", ["수면", "잠", "재우"]),
    ("외출", ["외출", "산책", "유모차", "카시트"]),
    ("목욕·위생", ["목욕", "위생", "샴푸"]),
    ("기저귀·배변", ["기저귀", "배변"]),
    ("의류", ["의류", "옷"]),
    ("놀이", ["놀이", "장난감"]),
    ("안전·건강", ["안전", "건강"]),
]


def _first_match(text: str, table: list[tuple[str, list[str]]]) -> str | None:
    text = text.lower()
    for value, keywords in table:
        if any(k in text for k in keywords):
            return value
    return None


def extract_computer(text: str) -> dict:
    out: dict = {}
    budget = _parse_won(text)
    if budget:
        out["budget_max"] = budget
    purpose = _first_match(text, _PURPOSE)
    if purpose:
        out["purpose"] = purpose
    priority = _first_match(text, _PRIORITY)
    if priority:
        out["priority"] = priority
    if re.search(r"144|165|4k|1440|2160|풀\s*hd|fhd|qhd", text, re.IGNORECASE):
        if "4k" in text.lower() or "2160" in text:
            out["resolution"] = "4K"
        elif "165" in text or "1440" in text or "qhd" in text.lower():
            out["resolution"] = "QHD_165"
        else:
            out["resolution"] = "FHD_144"
    return out


def extract_baby(text: str) -> dict:
    out: dict = {}
    lowered = text.lower()
    budget = _parse_won(text)
    if budget:
        out["budget_max"] = budget
    months = _parse_months(text)
    if months is not None:
        out["age_months"] = months
    matched_needs = [label for label, keywords in _NEEDS_MAP if any(k in text for k in keywords)]
    if matched_needs:
        out["needs"] = matched_needs
    if re.search(r"아토피|atopic|atopy", lowered):
        out["health_skin"] = ["아토피"]
    elif re.search(r"민감|sensitive|eczema", lowered):
        out["health_skin"] = ["민감성 피부"]
    # "피부"/"건강"/"특이사항" 이 명시된 맥락에서만 none 으로 판단한다 — "보유 물품이 없어요" 같은
    # 무관한 문장의 "없어요" 만 보고 건강 상태를 단정하던 버그를 막는다.
    elif re.search(r"(특이사항|피부|건강|알러지|알레르기).{0,6}(없|괜찮)", text):
        out["health_skin"] = []
    if re.search(r"(보유|가진|갖고\s*있는|물품|아직).{0,8}(없|아직\s*없)", text) or re.fullmatch(r"\s*(아직\s*)?없어요\.?\s*", text):
        out.setdefault("owned_items", [])
    return out


def extract(category: str, text: str) -> dict:
    if category == "computer":
        return extract_computer(text)
    if category == "baby":
        return extract_baby(text)
    return {}
