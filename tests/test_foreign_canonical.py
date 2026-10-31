"""`seo.canonical.duplicate` counts only pages whose canonical points to a different URL.

A home page that points to itself is correct. The severity depends on the share of such pages in
the sample, because two subpages out of seven are not the same as the whole site (ADR-020).
"""

from __future__ import annotations

import pytest
from factories import clean_site, page, run_level

from sitetriage.messages import render

HOME = "https://cist.rs/"


def site_with(total: int, foreign: dict[int, str]):
    """`total` successfully fetched pages, each in its own path group; `foreign[i]` is the
    canonical of the i-th page (0 is the home page). The others point to themselves."""
    site = clean_site()
    site.pages = [site.home] + [page(f"https://cist.rs/g{i}/strana") for i in range(1, total)]
    for i, target in foreign.items():
        site.pages[i].canonical_normalized = target
    site.sitemap.urls = [p.url for p in site.pages[1:]]
    return site


def canonical(site):
    return run_level(1, site)["seo.canonical.duplicate"]


def test_home_page_pointing_to_itself_does_not_count():
    result = canonical(site_with(7, {1: HOME, 2: HOME}))
    assert result.status == "finding"
    assert result.findings[0].evidence["page_count"] == 2, "the home page points to itself"


def test_two_subpages_out_of_seven_give_medium():
    found = canonical(site_with(7, {1: HOME, 2: HOME})).findings[0]
    assert found.severity == "medium"
    assert (found.evidence["page_count"], found.evidence["total"]) == (2, 7)


def test_one_page_with_foreign_canonical_is_not_a_finding():
    assert canonical(site_with(7, {1: HOME})).status == "ok"


@pytest.mark.parametrize(
    "foreign_count, severity",
    [
        pytest.param(39, "medium", id="gv-0,39"),
        pytest.param(40, "high", id="gv-0,40"),
        pytest.param(41, "high", id="gv-0,41"),
        pytest.param(59, "high", id="gv-0,59"),
        pytest.param(60, "critical", id="gv-0,60"),
    ],
)
def test_severity_by_share(foreign_count, severity):
    site = site_with(100, dict.fromkeys(range(1, foreign_count + 1), HOME))
    found = canonical(site).findings[0]
    assert found.severity == severity
    assert found.evidence["share"] == foreign_count / 100


def test_pagination_of_one_blog_is_not_a_finding():
    """Blog pages 2 and 3 point to the first: that is one path group, not the whole site."""
    site = site_with(7, {})
    for i, page_number in ((1, 2), (2, 3)):
        site.pages[i].url = site.pages[i].final_url = f"https://cist.rs/blog?page={page_number}"
        site.pages[i].canonical_normalized = "https://cist.rs/blog"
    assert canonical(site).status == "ok"


def test_canonical_differing_only_by_normalization_is_not_foreign():
    """The home page fetched as `https://cist.rs?utm_source=fb`, with the canonical `https://cist.rs/`."""
    site = site_with(7, {1: HOME, 2: HOME})
    site.home.final_url = "https://cist.rs?utm_source=fb"
    site.home.canonical_normalized = HOME
    assert canonical(site).findings[0].evidence["page_count"] == 2


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("http://cist.rs/", id="http"),
        pytest.param("https://www.cist.rs/", id="www"),
        pytest.param("http://www.cist.rs/", id="http-www"),
    ],
)
def test_canonical_to_same_page_with_other_scheme_or_www_is_not_foreign(target):
    """ADR-020: the home page points to its own `http` or `www` version, and one subpage to the home page.
    The "other URL" in the sentence would be the owner's own home page."""
    assert canonical(site_with(7, {0: target, 1: target})).status == "ok"


def test_other_scheme_to_a_different_page_is_still_foreign():
    found = canonical(site_with(7, {1: "http://cist.rs/", 2: "http://cist.rs/"})).findings[0]
    assert found.evidence["page_count"] == 2


@pytest.mark.parametrize(
    "lang, expected",
    [
        pytest.param("sr", "2 od 7 proverenih stranica sajta", id="sr"),
        pytest.param("en", "2 of the 7 checked pages", id="en"),
    ],
)
def test_sentence_says_how_many_out_of_how_many(lang, expected):
    found = canonical(site_with(7, {1: HOME, 2: HOME})).findings[0]
    assert expected in render(found, lang).client
