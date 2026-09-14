from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_all_pages_load_locale_before_api_and_i18n_last() -> None:
    pages = sorted(FRONTEND.glob("*.html"))
    assert pages

    for page in pages:
        html = page.read_text(encoding="utf-8")
        locale_position = html.find("./js/locale.js")
        api_position = html.find("./js/api.js")
        i18n_position = html.find("./js/i18n.js")

        assert locale_position >= 0, page.name
        assert locale_position < api_position < i18n_position, page.name
        assert i18n_position == html.rfind("./js/i18n.js"), page.name


def test_i18n_uses_the_shared_locale_source() -> None:
    source = (FRONTEND / "js" / "i18n.js").read_text(encoding="utf-8")

    assert "window.TF_LOCALE.get()" in source
    assert "window.TF_LOCALE.set(" in source
    assert "window.TF_I18N=Object.freeze" in source
    assert "localStorage.setItem(LS" not in source


def test_api_sends_the_normalized_locale_header() -> None:
    source = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")

    assert "window.TF_LOCALE?.get?.()||'ko-KR'" in source
    assert "'Accept-Language':locale" in source


def test_result_page_handles_generation_language_mismatch() -> None:
    source = (FRONTEND / "js" / "pages" / "results.js").read_text(encoding="utf-8")

    assert "content_language" in source
    assert "tfResultLanguageNotice(result)" in source
    assert "data-language-rerun" in source
    assert "data-plan-rerun" in source


def test_critical_language_mismatch_messages_are_translated() -> None:
    source = (FRONTEND / "js" / "i18n.js").read_text(encoding="utf-8")

    for message in (
        "이 추천은 한국어로 생성되었습니다.",
        "이 추천은 영어로 생성되었습니다.",
        "영어로 추천 다시 만들기",
        "한국어로 추천 다시 만들기",
    ):
        assert f'"{message}":' in source


def test_landing_accessibility_and_storage_notice_are_translated() -> None:
    source = (FRONTEND / "js" / "i18n.js").read_text(encoding="utf-8")

    assert '"회원 메뉴":"Account menu"' in source
    assert (
        '"입력한 리스트는 로그인 계정에는 서버에, 비로그인 상태에서는 이 브라우저에 임시로 '
        '저장됩니다.":"Lists are saved on the server for signed-in accounts and temporarily in this '
        'browser when signed out."'
    ) in source


def test_english_quick_replies_send_english_messages() -> None:
    source = (FRONTEND / "js" / "pages" / "results.js").read_text(encoding="utf-8")

    assert "Give me an overall assessment of this build" in source
    assert "'Make '+slotLabel+' cheaper'" in source


def test_all_page_titles_have_complete_english_translations() -> None:
    source = (FRONTEND / "js" / "i18n.js").read_text(encoding="utf-8")

    for title in (
        "회원정보 — TrueFit",
        "카테고리 선택 — TrueFit",
        "조건 입력 — TrueFit",
        "리스트 확정 — TrueFit",
        "TrueFit — 잘 고르는 시작",
        "로그인 — TrueFit",
        "추천 과정 — TrueFit",
        "내 리포트 — TrueFit",
        "추천 결과 — TrueFit",
        "회원가입 — TrueFit",
    ):
        assert f'"{title}":' in source


def test_i18n_does_not_translate_arbitrary_sentence_fragments() -> None:
    source = (FRONTEND / "js" / "i18n.js").read_text(encoding="utf-8")

    assert "function subclean" not in source
    assert ".split(k).join(DICT[k])" not in source
