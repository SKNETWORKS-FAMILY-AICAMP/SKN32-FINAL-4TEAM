"""Versioned lexical baseline, not a Korean morphological analyzer."""

import re
import unicodedata

VERSION = "nfkc-ko-bigram-v1"
_STOP = {
    "이",
    "그",
    "제품",
    "유모차",
    "알려",
    "알려줘",
    "알려주세요",
    "어떻게",
    "무엇",
    "인가요",
    "있나요",
    "하나요",
}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def tokens(text: str) -> list[str]:
    out = []
    for word in re.findall(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[가-힣]+", normalize(text)):
        if word in _STOP:
            continue
        out.append(word)
        if re.fullmatch(r"[가-힣]+", word) and len(word) > 2:
            out.extend(word[i : i + 2] for i in range(len(word) - 1))
    return out


def lexical_text(text: str) -> str:
    return " ".join(tokens(text))


def query_expression(text: str) -> str:
    return " | ".join(
        "'" + t.replace("'", "''") + "'" for t in sorted(set(tokens(text)))
    )
