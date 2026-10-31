"""ADR-015: the duplicate checks are "not applicable" only when the site really has < 3 pages.

A small sample is not the same as a small site: the sample is also small when the budget runs out,
when the links are in JS and when the sitemap does not list all pages. Then it is `unknown`, and
the reason says why.
"""

from __future__ import annotations

import asyncio

import pytest
from factories import clean_browser, clean_site, run_level
from localserver import FakeSite, Response

from sitetriage.config import load_config
from sitetriage.fetch.http import Fetcher, fetch_site
from sitetriage.messages import reason
from sitetriage.models import CheckResult, DomainInput
from sitetriage.report import html_out
from sitetriage.score import analyze

DUPLICATES = ("seo.canonical.duplicate", "seo.description.duplicate", "seo.title.duplicate")


def small_site(*, budget: bool = False, address_count: int = 2, js: bool = True):
    """The home page and `/usluge` in the sample; `address_count` is how many distinct URLs the sources
    see, including the home page."""
    site = clean_site(pages=clean_site().pages[:2])
    subpages = ["https://cist.rs/usluge"] + [f"https://cist.rs/strana-{i}" for i in range(2, address_count)]
    site.sitemap.urls = subpages
    site.home_links = ["https://cist.rs/", "https://cist.rs/usluge"]
    site.budget.exhausted = budget
    if not js:
        site.home.text_length = 100
        site.home.h1_count_raw = 0
    return site


def _duplicates(site, browser=None) -> dict[str, CheckResult]:
    results = run_level(1, site, browser=browser)
    return {check_id: results[check_id] for check_id in DUPLICATES}


# --------------------------------------------------------------------------- #
# Three conditions: budget, number of URLs from all sources, a source that sees JS
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "budget, address_count, js, status, code",
    [
        pytest.param(False, 2, True, "not_applicable", "few_pages", id="tab-all-three-met"),
        pytest.param(True, 2, True, "unknown", "pages_budget", id="tab-budget-exhausted"),
        pytest.param(False, 3, True, "unknown", "pages_sample", id="tab-sources-see-three-urls"),
        pytest.param(False, 2, False, "unknown", "pages_js", id="tab-nobody-sees-js"),
        pytest.param(True, 5, False, "unknown", "pages_budget", id="tab-none-met"),
    ],
)
def test_three_conditions_for_not_applicable(budget, address_count, js, status, code):
    site = small_site(budget=budget, address_count=address_count, js=js)
    for check_id, result in _duplicates(site).items():
        assert (result.status, result.reason.code) == (status, code), check_id


def test_level2_sees_js_when_raw_html_does_not():
    browser = clean_browser()
    browser.dom.internal_links = ["https://cist.rs/"]
    browser.dom.internal_links_total = 1
    for result in _duplicates(small_site(js=False), browser).values():
        assert result.status == "not_applicable"


def test_links_from_rendered_dom_count_as_urls():
    browser = clean_browser()
    browser.dom.internal_links = ["https://cist.rs/a", "https://cist.rs/b"]
    browser.dom.internal_links_total = 2
    for result in _duplicates(small_site(), browser).values():
        assert (result.status, result.reason.code) == ("unknown", "pages_sample")


def test_level2_without_recorded_links_does_not_see_js():
    """A level 2 snapshot from 1.x has no links: level 2 ran, but its links were not seen."""
    for result in _duplicates(small_site(js=False), clean_browser()).values():
        assert result.reason.code == "pages_js"


def test_budget_exhausted_after_home_page_stays_unknown():
    site = small_site(budget=True)
    del site.pages[1:]
    report = analyze(site, load_config())
    assert report.status == "partial"
    assert {u.check_id for u in report.unknowns} >= set(DUPLICATES)


def test_js_navigation_without_level2_stays_unknown():
    report = analyze(small_site(js=False), load_config())
    assert report.status == "partial"
    assert {u.reason.code for u in report.unknowns if u.check_id in DUPLICATES} == {"pages_js"}


def test_not_applicable_does_not_make_partial():
    report = analyze(small_site(), load_config())
    assert report.status == "scanned" and not report.unknowns
    assert sorted(n.check_id for n in report.not_applicable) == sorted(DUPLICATES)
    page = html_out.render([report], load_config())
    assert "ne primenjuje se: sajt ima 2 interne adrese" in page


def test_not_applicable_without_reason_is_a_bug():
    with pytest.raises(ValueError, match="bez `reason`"):
        CheckResult(check_id="seo.title.duplicate", status="not_applicable")


@pytest.mark.parametrize(
    "lang, expected",
    [
        pytest.param("sr", "sajt ima 2 interne adrese, a za poređenje treba bar 3", id="sr"),
        pytest.param("en", "the site has 2 internal addresses, and a comparison needs at least 3", id="en"),
    ],
)
def test_not_applicable_reason_in_both_languages(lang, expected):
    result = _duplicates(small_site())["seo.title.duplicate"]
    assert reason(result.reason, lang) == expected


def test_v1_snapshot_without_home_page_links_is_unknown():
    site = small_site()
    site.scanner_version = "1.0.0"
    for result in _duplicates(site).values():
        assert (result.status, result.reason.code) == ("unknown", "v1_snapshot")


# --------------------------------------------------------------------------- #
# Sampling: a small sitemap is topped up with links from the home page
# --------------------------------------------------------------------------- #
def _scan(site: FakeSite):
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url))

    return asyncio.run(run())


def test_sitemap_with_two_urls_is_topped_up_with_links():
    def sitemap(base: str) -> Response:
        urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/usluge", "/kontakt"))
        xmlns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        return Response(f'<?xml version="1.0"?><urlset xmlns="{xmlns}">{urls}</urlset>'.encode())

    class SmallSitemap(FakeSite):
        def route(self, path: str) -> Response:
            return sitemap(self.base_url) if path == "/sitemap.xml" else super().route(path)

    with SmallSitemap() as site:
        snapshot = _scan(site)
    paths = sorted(p.url.removeprefix(site.base_url) for p in snapshot.pages)
    assert paths == ["/", "/kontakt", "/o-nama", "/usluge"], "o-nama is only in the home page links"
    assert snapshot.home_links and all(link.startswith(site.base_url) for link in snapshot.home_links)
