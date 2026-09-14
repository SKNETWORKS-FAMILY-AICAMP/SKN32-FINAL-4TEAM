"""사용자 언어 (ko|en) — 02 조건 대화가 감지해 조건 `language` 로 남기고, [3-C]·[5]·결과 조립이 읽는다.

데모는 영어로 진행한다(2026-09-14). 저장·계산은 언어와 무관하고, 사용자에게 나가는 문장만 갈린다.
리뷰 관측 문장(관계·행동 축 산출물)은 데이터라 한국어 그대로다.
"""
from __future__ import annotations

_LLM_LANGUAGE_LINE = {
    "en": "\n\nOutput language: English. Write plain sentences (no labels, headings or bullet prefixes). "
          "Keep numbers, units and slot/part names exactly as given — do not translate slot names such as 메인보드 or 저장장치, "
          "do not convert amounts; '원' stays as '원'. Say 'confidence 94' exactly as given — never the word 'score'. "
          "No evaluative words (excellent, powerful, best, perfect, outstanding, strong); state facts only.",
}

# 한국어를 명시한 규칙 줄 — 영어 출력 때는 이 줄이 위 지시와 충돌해 모델이 한국어를 고른다([3-C] 실측). 런타임에 바꿔 끼운다.
_KO_RULE_LINES = {
    "한국어 존댓말로 1~2문장, 120자 이내.": "English, one or two sentences, under 200 characters.",
    "7. 한국어 존댓말.": "7. English.",
}


def localize_system(system: str, lang: str) -> str:
    """시스템 프롬프트를 사용자 언어에 맞춘다. 문안 파일(prompts.py)은 그대로 두고 호출 시점에만 바꾼다."""
    if lang != "en":
        return system
    for ko, en in _KO_RULE_LINES.items():
        system = system.replace(ko, en)
    return system + llm_language_suffix(lang)


def lang_of(values: dict | None) -> str:
    return "en" if (values or {}).get("language") == "en" else "ko"


def L(lang: str, ko: str, en: str) -> str:
    return en if lang == "en" else ko


def llm_language_suffix(lang: str) -> str:
    """시스템 프롬프트 뒤에 붙이는 언어 지시. 문안(prompts.py) 자체는 건드리지 않는다."""
    return _LLM_LANGUAGE_LINE.get(lang, "")
