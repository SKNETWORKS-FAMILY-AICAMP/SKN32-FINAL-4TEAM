from src.i18n.locale import normalize_locale


def test_missing_language_defaults_to_korean():
    assert normalize_locale(None) == "ko-KR"


def test_korean_language():
    assert normalize_locale("ko-KR") == "ko-KR"


def test_english_language():
    assert normalize_locale("en-US") == "en-US"


def test_short_english_language():
    assert normalize_locale("en") == "en-US"


def test_quality_priority():
    assert normalize_locale("ko;q=0.5,en;q=0.9") == "en-US"


def test_unsupported_language_falls_back_to_korean():
    assert normalize_locale("fr-FR") == "ko-KR"


def test_supported_secondary_language():
    assert normalize_locale("fr-FR,en;q=0.7") == "en-US"


def test_zero_quality_is_ignored():
    assert normalize_locale("en;q=0,ko;q=0.8") == "ko-KR"


def test_malformed_quality_is_ignored():
    assert normalize_locale("en;q=invalid,ko;q=0.8") == "ko-KR"
