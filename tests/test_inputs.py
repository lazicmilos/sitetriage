"""The domain list and CSV from Excel. The list usually comes from Excel, and the operator is not
necessarily a programmer."""

from __future__ import annotations

import pytest

from sitetriage.inputs import InputError, is_excluded, read_domain_list, read_excel_csv, read_exclusions


def read(content: str | bytes):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return read_domain_list(data, "d.csv")


def test_reads_csv_with_a_header():
    rows, _ = read(
        "domain,industry,note\ninstitucija.example,institution,beleska\nrestoran-ugao.example,,\nklinika.example,NEPOSTOJECA,\n\n"
    )
    assert [r.domain for r in rows] == ["institucija.example", "restoran-ugao.example", "klinika.example"]
    assert rows[0].industry == "institution" and rows[0].note == "beleska"
    assert rows[1].industry == "other", "an empty industry falls back to `other`"
    assert rows[2].industry == "other", "an unknown industry falls back to `other` and does not break the run"


def test_csv_without_a_domain_column_fails_clearly():
    with pytest.raises(InputError, match="row 1: the header has no `domain` column"):
        read("sajt,industry\na.rs,hotel\n")


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="nv-empty-file"),
        pytest.param(b"domain,industry\n", id="nv-header-only"),
        pytest.param(b"domain,industry\n\n  \n", id="nv-empty-rows"),
    ],
)
def test_csv_without_domains_fails_clearly(content):
    with pytest.raises(InputError):
        read(content)


# --------------------------------------------------------------------------- #
# Error guessing: a list from Excel on Windows with Serbian regional settings
# --------------------------------------------------------------------------- #
def test_csv_from_excel_with_semicolons():
    """Serbian Windows settings: Excel "CSV" separates columns with `;`."""
    rows, _ = read("domain;industry;note\ninstitucija.example;institution;beleška\n")
    assert [(r.domain, r.industry, r.note) for r in rows] == [
        ("institucija.example", "institution", "beleška")
    ]


def test_csv_in_windows_1250():
    """Excel without the "UTF-8" option saves in windows-1250; this used to be a traceback."""
    csv = "domain,industry,note\ninstitucija.example,institution,čćžšđ\n"
    rows, warnings = read(csv.encode("cp1250"))
    assert rows[0].note == "čćžšđ"
    assert "windows-1250" in warnings[0].message


def test_csv_duplicates_are_scanned_once():
    """The same domain twice = someone else's site twice and two report rows with the same snapshot."""
    rows, _ = read(
        "domain,industry\ninstitucija.example,institution\nINSTITUCIJA.EXAMPLE,hotel\n"
        "restoran-ugao.example,restaurant\n"
    )
    assert [r.domain for r in rows] == ["institucija.example", "restoran-ugao.example"]
    assert rows[0].industry == "institution", "the first occurrence wins"


def test_csv_with_a_bom():
    rows, _ = read("domain,industry\ninstitucija.example,institution\n".encode("utf-8-sig"))
    assert [r.domain for r in rows] == ["institucija.example"]


# --------------------------------------------------------------------------- #
# Row number: the user finds the row in Excel by it
# --------------------------------------------------------------------------- #
def test_warning_carries_the_row_number_and_the_domain():
    _, warnings = read(
        "domain,industry\ninstitucija.example,institution\nrestoran-ugao.example,picerija\n"
        "INSTITUCIJA.EXAMPLE,hotel\n"
    )
    assert [(w.row, w.domain) for w in warnings] == [
        (3, "restoran-ugao.example"),
        (4, "INSTITUCIJA.EXAMPLE"),
    ]


@pytest.mark.parametrize(
    ("content", "rows"),
    [
        pytest.param(b"domain\na.rs\nb.rs\n", [2, 3], id="ke-plain"),
        pytest.param(b"domain\na.rs\n\nb.rs\n", [2, 4], id="pg-empty-row-counts"),
        pytest.param(b'domain,note\na.rs,"prvi\ndrugi"\nb.rs,x\n', [2, 3], id="pg-line-break-in-cell"),
    ],
)
def test_row_number_is_the_excel_row(content, rows):
    """Excel shows an empty row; a cell with a line break is two lines in the file but one row in Excel."""
    assert [number for number, _ in read_excel_csv(content, "d.csv").rows] == rows


def test_header_after_an_empty_row():
    table = read_excel_csv(b"\ndomain;industry\na.rs;hotel\n", "d.csv")
    assert table.header_row == 2 and table.rows == [(3, {"domain": "a.rs", "industry": "hotel"})]


# --------------------------------------------------------------------------- #
# Excluded domains (opt-out)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("domain", "excluded"),
    [
        pytest.param("x.rs", True, id="ke-same-host"),
        pytest.param("www.x.rs", True, id="ke-www"),
        pytest.param("blog.x.rs", True, id="ke-subdomain"),
        pytest.param("https://shop.x.rs/putanja", True, id="ke-full-url"),
        pytest.param("X.RS", True, id="pg-upper-case"),
        pytest.param("x.rs.", True, id="pg-trailing-dot"),
        pytest.param("nex.rs", False, id="gv-suffix-without-dot"),
        pytest.param("x.rs.zlo.com", False, id="pg-x.rs-at-the-start-of-a-foreign-domain"),
        pytest.param("y.rs", False, id="ke-other-domain"),
    ],
)
def test_exclusion_applies_to_subdomains(domain, excluded):
    assert is_excluded(domain, ["x.rs"]) is excluded


def test_co_rs_is_not_excluded_when_firma_co_rs_is():
    """Without the Public Suffix List the "registered domain" of `firma.co.rs` would be `co.rs`."""
    exclusions = ["firma.co.rs"]
    assert is_excluded("firma.co.rs", exclusions) and is_excluded("www.firma.co.rs", exclusions)
    assert not is_excluded("co.rs", exclusions) and not is_excluded("druga.co.rs", exclusions)


def test_www_in_the_entry_excludes_the_whole_company():
    assert is_excluded("x.rs", ["www.x.rs"]) and is_excluded("blog.x.rs", ["https://www.x.rs/"])


def test_exclusion_file():
    data = "﻿x.rs\n\n# ko je tražio i kada\ny.rs  # posle tarabe je komentar\n   \n".encode()
    assert read_exclusions(data) == ["x.rs", "y.rs"]
    assert not is_excluded("x.rs", read_exclusions(b"# samo komentar\n"))


def test_exclusion_file_in_windows_1250():
    """pg-: Notepad on Serbian Windows saves the comment in windows-1250, and the domain is read anyway."""
    assert read_exclusions("# tražio vlasnik iz Niša\nx.rs\n".encode("cp1250")) == ["x.rs"]


# --------------------------------------------------------------------------- #
# The same site written two ways is scanned once (BUG-02)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("http://127.0.0.1:18001", "http://127.0.0.1:18001/", id="ke-trailing-slash"),
        pytest.param("example.invalid", "https://example.invalid/", id="ke-scheme-and-slash"),
        pytest.param("example.invalid", "http://example.invalid", id="ke-other-scheme"),
        pytest.param("example.invalid", "www.example.invalid", id="ke-www"),
        pytest.param("www.example.invalid", "https://WWW.Example.Invalid/", id="ke-www-upper-case-url"),
        pytest.param("example.invalid", "example.invalid.", id="ke-trailing-dot"),
        pytest.param("example.invalid", "https://example.invalid:443/", id="ke-default-https-port"),
        pytest.param("http://example.invalid", "http://example.invalid:80", id="ke-default-http-port"),
        pytest.param("example.invalid/en", "https://www.example.invalid/en/", id="ke-same-path"),
        pytest.param("example.invalid", "example.invalid/?utm_source=a#top", id="ke-tracking-fragment"),
        pytest.param("ftp://example.invalid", "FTP://EXAMPLE.INVALID", id="nv-not-a-web-url-as-written"),
    ],
)
def test_the_same_site_written_two_ways_is_scanned_once(first, second):
    rows, warnings = read(f"domain,industry\n{first},hotel\n{second},restaurant\n")
    assert [(r.domain, r.industry) for r in rows] == [(first, "hotel")], "the first occurrence wins"
    assert [(w.row, w.domain) for w in warnings] == [(3, second)]
    assert warnings[0].message == f"same site as row 2 ({first}), skipping it"


def test_three_spellings_of_one_site_give_one_row():
    rows, warnings = read("domain\nexample.invalid\nhttps://example.invalid/\nwww.example.invalid\n")
    assert [r.domain for r in rows] == ["example.invalid"]
    assert [(w.row, w.message) for w in warnings] == [
        (3, "same site as row 2 (example.invalid), skipping it"),
        (4, "same site as row 2 (example.invalid), skipping it"),
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("firma.example", "blog.firma.example", id="ke-subdomain-is-another-site"),
        pytest.param("http://127.0.0.1:18001", "http://127.0.0.1:18002", id="ke-other-port"),
        pytest.param("example.invalid", "https://example.invalid:8443", id="ke-non-default-port"),
        pytest.param("http://example.invalid:443", "https://example.invalid", id="pg-https-port-over-http"),
        pytest.param("example.invalid/en", "example.invalid/sr", id="ke-other-entry-path"),
        pytest.param("example.invalid", "example.invalid/en", id="ke-entry-path-vs-root"),
        pytest.param("wwwfirma.example", "firma.example", id="gv-www-without-dot"),
        pytest.param("example.invalid/?lang=en", "example.invalid/?lang=sr", id="ke-other-query"),
    ],
)
def test_different_sites_stay_distinct(first, second):
    rows, warnings = read(f"domain\n{first}\n{second}\n")
    assert [r.domain for r in rows] == [first, second]
    assert warnings == []


# --------------------------------------------------------------------------- #
# Header names from Excel (BUG-08)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "header",
    [
        pytest.param("domain, industry, note", id="ke-space-after-comma"),
        pytest.param("domain;\t industry ;note", id="ke-tab-and-space"),
        pytest.param(" domain ,industry,note ", id="gv-space-around-the-edge-columns"),
        pytest.param("Domain,Industry,Note", id="ke-capitalised-by-excel"),
        pytest.param("DOMAIN;INDUSTRY;NOTE", id="ke-upper-case"),
    ],
)
def test_header_names_ignore_surrounding_whitespace_and_case(header):
    sep = ";" if ";" in header else ","
    rows, warnings = read(f"{header}\n10.0.0.1{sep} hotel{sep} beleska\n")
    assert [(r.domain, r.industry, r.note) for r in rows] == [("10.0.0.1", "hotel", "beleska")]
    assert warnings == []


def test_unknown_header_column_is_warned_once_with_the_header_row():
    """pg-: a typo in `industry` used to score every site as `other` without a word."""
    rows, warnings = read("\ndomain,industy,note\na.example,hotel,\nb.example,restaurant,\n")
    assert [r.industry for r in rows] == ["other", "other"]
    assert [(w.row, w.domain, w.message) for w in warnings] == [
        (2, None, "unknown column `industy` in the header, ignoring it (known: domain, industry, note)")
    ]


def test_every_unknown_column_is_named_in_one_warning():
    _, warnings = read("domain,Sajt,expected\na.example,x,y\n")
    assert [w.message for w in warnings] == [
        "unknown columns `sajt`, `expected` in the header, ignoring them (known: domain, industry, note)"
    ]


def test_empty_header_cell_is_not_an_unknown_column():
    """pg-: Excel writes a trailing separator when a column to the right was once used."""
    _, warnings = read("domain,industry,\na.example,hotel,\n")
    assert warnings == []


def test_excel_csv_header_names_are_stripped_and_lower_case():
    table = read_excel_csv(b" Domain ;\tIndustry\na.rs;hotel\n", "d.csv")
    assert table.fieldnames == ["domain", "industry"]
    assert table.rows == [(2, {"domain": "a.rs", "industry": "hotel"})]
