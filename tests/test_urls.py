"""Tabelarni test normalizacije (§12.3): tu se kriju najzabavniji bagovi."""

import pytest

from skener.fetch.urls import collapse_ws, normalize, path_group, same_site

# (ulaz, base, očekivano)
CASES = [
    ("http://Example.COM/", None, "http://example.com/"),
    ("https://d.rs", None, "https://d.rs/"),
    ("https://d.rs/usluge/", None, "https://d.rs/usluge"),
    ("https://d.rs/usluge", None, "https://d.rs/usluge"),
    ("https://d.rs:443/a", None, "https://d.rs/a"),
    ("http://d.rs:80/a", None, "http://d.rs/a"),
    ("https://d.rs:8443/a", None, "https://d.rs:8443/a"),
    ("https://d.rs/a#kontakt", None, "https://d.rs/a"),
    ("https://d.rs/a?utm_source=fb&utm_medium=cpc", None, "https://d.rs/a"),
    ("https://d.rs/a?fbclid=123&gclid=4&ref=x", None, "https://d.rs/a"),
    ("https://d.rs/a?b=2&a=1", None, "https://d.rs/a?a=1&b=2"),
    ("https://d.rs/a?q=", None, "https://d.rs/a?q="),
    ("https://d.rs./a", None, "https://d.rs/a"),
    ("https://D.RS/PATH", None, "https://d.rs/PATH"),
    ("https://d.rs//", None, "https://d.rs/"),
    ("usluge/1", "https://d.rs/o-nama", "https://d.rs/usluge/1"),
    ("/a/../b", "https://d.rs/x/", "https://d.rs/b"),
    ("//cdn.d.rs/x", "https://d.rs/", "https://cdn.d.rs/x"),
    ("mailto:x@d.rs", None, None),
    ("javascript:void(0)", None, None),
    ("tel:+381600000000", None, None),
    ("ftp://d.rs/a", None, None),
    ("#top", None, None),
    ("", None, None),
    (None, None, None),
]


@pytest.mark.parametrize("url, base, expected", CASES)
def test_normalize_table(url, base, expected):
    assert normalize(url, base) == expected


@pytest.mark.parametrize(
    "url",
    [expected for _, _, expected in CASES if expected]
    + [
        "https://šumadija.rs/Čačak",
        "https://d.rs/a%20b?x=a%26b",
        "https://d.rs/a?utm_source=x&strana=2",
        "https://d.rs/a/?q=1#f",
        "http://[::1]:8080/a/",
    ],
)
def test_normalize_je_idempotentan(url):
    """Normalizovan URL koji se ponovo normalizuje mora ostati isti.

    Inače je isti canonical „različit" zavisno od toga koliko puta je prošao
    kroz `normalize`, a na tome stoji svaki `*.duplicate` nalaz.
    """
    once = normalize(url)
    assert normalize(once) == once


def test_www_se_ne_uklanja():
    """§4.5 tačka 7: www i non-www jesu različite adrese za Google."""
    assert normalize("https://www.d.rs/a") != normalize("https://d.rs/a")


def test_normalize_je_idempotentna():
    for _url, _base, expected in CASES:
        if expected is not None:
            assert normalize(expected) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://d.rs/", "/"),
        ("https://d.rs", "/"),
        ("https://d.rs/o-nama", "/o-nama"),
        ("https://d.rs/usluge/protetika", "/usluge"),
        ("https://d.rs/blog/2026/nesto", "/blog"),
        (None, "/"),
    ],
)
def test_path_group(url, expected):
    assert path_group(url) == expected


def test_same_site_ignorise_www_za_uzorkovanje():
    assert same_site("https://www.d.rs/a", "https://d.rs/b")
    assert not same_site("https://d.rs/a", "https://drugi.rs/b")
    assert not same_site("https://d.rs/a", None)


def test_collapse_ws():
    assert collapse_ws("  Naslov   sa\n\trazmacima ") == "Naslov sa razmacima"
    assert collapse_ws(None) is None
    assert collapse_ws("   ") == ""
