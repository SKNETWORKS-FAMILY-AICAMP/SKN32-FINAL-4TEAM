"""Normalize HTTP language preferences to the locales supported by Truefit."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Header

Locale = Literal["ko-KR", "en-US"]

DEFAULT_LOCALE: Locale = "ko-KR"


def _quality(parameters: list[str]) -> float:
    """Return an Accept-Language quality value, rejecting malformed values."""
    for parameter in parameters:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().lower() == "q":
            try:
                quality = float(value.strip())
            except ValueError:
                return 0.0
            return quality if 0.0 <= quality <= 1.0 else 0.0
    return 1.0


def _supported_locale(language_tag: str) -> Locale | None:
    primary = language_tag.strip().lower().split("-", 1)[0]
    if primary == "en":
        return "en-US"
    if primary == "ko":
        return "ko-KR"
    return None


def normalize_locale(accept_language: str | None) -> Locale:
    """Choose the highest-priority supported locale, defaulting to Korean."""
    if not accept_language:
        return DEFAULT_LOCALE

    candidates: list[tuple[float, int, Locale]] = []
    for index, part in enumerate(accept_language.split(",")):
        sections = [value.strip() for value in part.split(";")]
        locale = _supported_locale(sections[0])
        quality = _quality(sections[1:])
        if locale is not None and quality > 0.0:
            candidates.append((quality, -index, locale))

    if not candidates:
        return DEFAULT_LOCALE
    return max(candidates)[2]


def resolve_locale(
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> Locale:
    """FastAPI dependency for the request's normalized response locale."""
    return normalize_locale(accept_language)
