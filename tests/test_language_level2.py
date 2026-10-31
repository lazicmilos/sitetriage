"""ADR-017: the language from the rendered text. A screen reader reads the page after JavaScript.

When level 2 ran, all three i18n checks look at `lang` and the text after JS, and the evidence
says where they came from. Without level 2, or with a level 2 snapshot from 1.x, they look at the
raw HTML, as before.
"""

from __future__ import annotations

from factories import SRPSKI_TEKST, clean_browser, clean_site, run_level

from sitetriage.messages import reason

I18N = ("i18n.lang.invalid", "i18n.lang.mismatch", "i18n.lang.missing")


def js_site(lang: str | None = None):
    """The raw HTML is almost empty, because JavaScript sets the text and `lang`."""
    site = clean_site()
    site.home.text_sample, site.home.text_length, site.home.lang = "Učitavanje…", 11, lang
    return site


def rendered(lang: str | None, text: str = SRPSKI_TEKST):
    browser = clean_browser()
    browser.dom.lang, browser.dom.text_sample, browser.dom.text_length = lang, text[:4000], len(text)
    return browser


def checks(site, browser=None):
    results = run_level(1, site, browser=browser)
    return {check_id: results[check_id] for check_id in I18N}


def test_language_from_rendered_text_when_raw_has_none():
    result = checks(js_site(), rendered("en-US"))["i18n.lang.mismatch"]
    assert result.status == "finding"
    assert result.findings[0].evidence["lang"] == "en-US"
    assert result.findings[0].evidence["text_length"] == len(SRPSKI_TEKST)


def test_without_level2_stays_unknown():
    result = checks(js_site())["i18n.lang.mismatch"]
    assert result.status == "unknown" and result.reason.code == "text_too_short"


def test_too_little_text_even_after_js_says_so():
    result = checks(js_site(), rendered("sr", "Kratko."))["i18n.lang.mismatch"]
    assert result.status == "unknown"
    assert "posle JavaScript-a" in reason(result.reason)


def test_lang_set_by_js_is_not_missing_when_level2_ran():
    results = checks(js_site(lang=None), rendered("sr"))
    assert {check_id: r.status for check_id, r in results.items()} == dict.fromkeys(I18N, "ok")


def test_lang_js_does_not_set_is_missing_even_after_level2():
    result = checks(js_site(lang=None), rendered(None))["i18n.lang.missing"]
    assert result.status == "finding" and result.findings[0].evidence["source"] == "rendered"


def test_evidence_names_the_text_source():
    without = checks(js_site(lang="zxx"))["i18n.lang.invalid"].findings[0]
    with_level2 = checks(js_site(lang="sr"), rendered("zxx"))["i18n.lang.invalid"].findings[0]
    assert (without.evidence["source"], with_level2.evidence["source"]) == ("raw_html", "rendered")


def test_level2_from_1x_without_text_uses_raw_html():
    """A level 2 snapshot from 1.x has no text or `lang` after JS; then the raw state applies, as before."""
    result = checks(js_site(lang="en"), clean_browser())["i18n.lang.mismatch"]
    assert result.status == "unknown" and result.reason.code == "text_too_short"
