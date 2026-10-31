"""Level 1 checks. Three tests per check: positive, negative and `unknown`.

The negative one matters most. It is the test against false positives, and false positives
are the one thing that turns a ranking tool into a noise generator (a deliberately clean
control site must get no findings).
"""

from __future__ import annotations

import copy

import pytest
from factories import clean_site, findings, run_level, statuses

from sitetriage.checks import registry
from sitetriage.messages import LANGS, reason, render
from sitetriage.models import Entry, HostVariant, Soft404, Soft404Probe, Tls

LEVEL1_IDS = sorted(s.check_id for s in registry.REGISTRY.values() if s.level == 1)


# --------------------------------------------------------------------------- #
# Negative: a clean site stays silent. One test covers all 20 checks.
# --------------------------------------------------------------------------- #
def test_clean_site_has_no_findings():
    results = run_level(1, clean_site())
    assert findings(results) == set()
    assert set(statuses(results).values()) == {"ok"}


def test_clean_site_covers_all_registered_checks():
    """If you add a check and do not cover it, this fails."""
    assert sorted(run_level(1, clean_site())) == LEVEL1_IDS


# --------------------------------------------------------------------------- #
# Positive: one broken thing → exactly that check
# --------------------------------------------------------------------------- #
def _all_pages(site, **attrs):
    for page in site.pages:
        for key, value in attrs.items():
            setattr(page, key, value)


POSITIVE_CASES = {
    "seo.canonical.missing": lambda s: setattr(s.home, "canonical", None),
    "seo.canonical.duplicate": lambda s: _all_pages(s, canonical_normalized="https://cist.rs/"),
    "seo.title.missing": lambda s: setattr(s.home, "title", "   "),
    "seo.title.duplicate": lambda s: _all_pages(s, title="Dobrodošli"),
    "seo.description.missing": lambda s: setattr(s.home, "meta_description", None),
    "seo.description.duplicate": lambda s: _all_pages(s, meta_description="Isti opis svuda."),
    "social.og.title.missing": lambda s: setattr(s.home.og, "title", None),
    "social.og.description.missing": lambda s: setattr(s.home.og, "description", None),
    "social.og.image.missing": lambda s: setattr(s.home.og, "image", None),
    "i18n.lang.missing": lambda s: setattr(s.home, "lang", None),
    "i18n.lang.invalid": lambda s: setattr(s.home, "lang", "zxx"),
    "i18n.lang.mismatch": lambda s: setattr(s.home, "lang", "en-US"),
    "infra.sitemap.missing": lambda s: (setattr(s.sitemap, "status", 404), s.sitemap.urls.clear()),
    "infra.robots.missing": lambda s: setattr(s.robots, "status", 404),
    "infra.soft404": lambda s: setattr(
        s,
        "soft404",
        Soft404(
            probes=[
                Soft404Probe(url="https://cist.rs/abc", status=200, text_sample="Dobrodošli"),
                Soft404Probe(url="https://cist.rs/abc.html", status=200, text_sample="Dobrodošli"),
            ]
        ),
    ),
    "perf.compression.missing": lambda s: (
        setattr(s.home, "headers", {}),
        setattr(s.home, "html_bytes", 120_000),
    ),
    "perf.redirect.chain": lambda s: setattr(
        s.entry,
        "redirect_chain",
        ["http://cist.rs/", "https://cist.rs/", "https://www.cist.rs/", "https://www.cist.rs/home"],
    ),
    "perf.html.size": lambda s: setattr(s.home, "html_bytes", 600 * 1024),
    "infra.tls.invalid": lambda s: setattr(s.entry, "tls", Tls(valid=False, error="certificate has expired")),
    "infra.unreachable": lambda s: (
        setattr(s, "entry", Entry("https://cist.rs/", error_kind="dns_nxdomain", error_detail="NXDOMAIN")),
        setattr(s, "entry_attempts", ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]),
    ),
    # http://cist.rs/ stays on http.
    "infra.https.redirect.missing": lambda s: s.host_variants.__setitem__(
        1, HostVariant(url="http://cist.rs/", status=200, final_url="http://cist.rs/")
    ),
    # https://www.cist.rs/ serves the site, without a redirect to cist.rs.
    "infra.host.duplicate": lambda s: s.host_variants.__setitem__(
        0, HostVariant(url="https://www.cist.rs/", status=200, final_url="https://www.cist.rs/")
    ),
}


@pytest.mark.parametrize("check_id", LEVEL1_IDS)
def test_positive_finding(check_id):
    site = clean_site()
    POSITIVE_CASES[check_id](site)
    result = run_level(1, site)[check_id]
    assert result.status == "finding", f"{check_id}: expected a finding, got {result.status}"

    found = result.findings[0]
    assert found.evidence, "a finding without evidence"
    assert any(isinstance(v, (int, float)) for v in found.evidence.values()), (
        f"{check_id}: the evidence must contain a number; \"the site is slow\" is not a finding"
    )
    for lang in LANGS:
        message = render(found, lang)
        assert message.client and "{" not in message.client
        assert message.tech and "{" not in message.tech
    assert found.check_id == check_id and found.level == 1


@pytest.mark.parametrize("check_id", LEVEL1_IDS)
def test_positive_does_not_wake_other_checks(check_id):
    """One broken thing may wake its own check, not the whole registry."""
    site = clean_site()
    POSITIVE_CASES[check_id](site)
    woken = findings(run_level(1, site))
    # `lang=zxx` legitimately also fires `invalid`; everything else must hit exactly one.
    allowed = {check_id} | ({"i18n.lang.invalid"} if check_id == "i18n.lang.invalid" else set())
    assert woken <= allowed, f"{check_id} also woke: {woken - allowed}"


# --------------------------------------------------------------------------- #
# `unknown`: missing data → a reason, not a crash and not `ok` (the third test type)
# --------------------------------------------------------------------------- #
UNKNOWN_CASES = {
    "home": (lambda s: s.pages.clear(), ["seo.canonical.missing", "seo.title.missing", "i18n.lang.missing"]),
    "pages": (
        lambda s: s.pages.__setitem__(slice(2, None), []),
        ["seo.canonical.duplicate", "seo.title.duplicate", "seo.description.duplicate"],
    ),
    "robots": (lambda s: setattr(s.robots, "status", None), ["infra.robots.missing"]),
    "sitemap": (lambda s: setattr(s.sitemap, "status", None), ["infra.sitemap.missing"]),
    "soft404": (lambda s: setattr(s, "soft404", Soft404(probes=[])), ["infra.soft404"]),
    "entry": (lambda s: setattr(s, "entry", None), ["infra.tls.invalid", "infra.unreachable"]),
}


@pytest.mark.parametrize("scenario", sorted(UNKNOWN_CASES))
def test_unknown_has_reason(scenario):
    mutate, expected_ids = UNKNOWN_CASES[scenario]
    site = clean_site()
    mutate(site)
    results = run_level(1, site)
    for check_id in expected_ids:
        result = results[check_id]
        assert result.status == "unknown", f"{check_id}: expected unknown, got {result.status}"
        assert result.reason, "unknown without a reason is a bug"


def test_empty_domain_crashes_no_check():
    """A domain that did not even respond must give 20 results, not an exception."""
    site = clean_site()
    site.pages.clear()
    site.entry = Entry(requested_url="https://cist.rs/", error_kind="dns_nxdomain", error_detail="NXDOMAIN")
    site.entry_attempts = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    site.robots.status = None
    site.sitemap.status = None
    site.soft404 = Soft404(probes=[])
    results = run_level(1, site)
    assert sorted(results) == LEVEL1_IDS
    assert results["infra.unreachable"].status == "finding"
    assert all(r.reason for r in results.values() if r.status == "unknown")


# --------------------------------------------------------------------------- #
# Edge cases the specification names explicitly
# --------------------------------------------------------------------------- #
def test_zxx_lands_in_invalid_not_mismatch():
    """The hotel-planina.example fixture: lang=zxx must land in `invalid`."""
    site = clean_site()
    site.home.lang = "zxx"
    results = run_level(1, site)
    assert results["i18n.lang.invalid"].status == "finding"
    assert results["i18n.lang.mismatch"].status == "ok"


def test_mismatch_is_unknown_when_text_is_too_short():
    """Too little text gives `unknown`, and it is also a signal to escalate to level 2."""
    site = clean_site()
    site.home.lang = "en"
    site.home.text_sample = "Kratko."
    site.home.text_length = 7
    result = run_level(1, site)["i18n.lang.mismatch"]
    assert result.status == "unknown"
    assert "premalo teksta" in reason(result.reason)


def test_content_without_diacritics_gives_no_mismatch():
    """English cannot be told from Serbian without diacritics; when you do not know, `ok`."""
    site = clean_site()
    site.home.lang = "en"
    site.home.text_sample = "Dobrodosli na sajt. Nudimo usluge i proizvode. " * 20
    site.home.text_length = len(site.home.text_sample)
    assert run_level(1, site)["i18n.lang.mismatch"].status == "ok"


def test_cyrillic_gives_mismatch():
    site = clean_site()
    site.home.lang = "de"
    site.home.text_sample = "Добродошли на сајт. Нудимо услуге и производе. " * 20
    site.home.text_length = len(site.home.text_sample)
    assert run_level(1, site)["i18n.lang.mismatch"].status == "finding"


@pytest.mark.parametrize(
    "lang, text",
    [
        pytest.param("ru", "Добро пожаловать на сайт. Мы предлагаем услуги. ", id="ke-russian-cyrillic"),
        pytest.param("mk-MK", "Добредојдовте на сајтот. Нудиме услуги. ", id="ke-macedonian"),
        pytest.param("hr", "Dobrodošli na stranicu. Nudimo usluge i proizvode, čišćenje. ", id="ke-croatian"),
        pytest.param(" sr-Latn ", "Dobrodošli na sajt. Nudimo usluge, čišćenje. ", id="ke-sr-whitespace"),
    ],
)
def test_same_script_language_is_not_mismatch(lang, text):
    """The detector sees only Cyrillic and č/ć/š/ž/đ: Russian with lang="ru" is not "Serbian content"."""
    site = clean_site()
    site.home.lang = lang
    site.home.text_sample = text * 20
    site.home.text_length = len(site.home.text_sample)
    assert run_level(1, site)["i18n.lang.mismatch"].status == "ok"


def test_incomplete_certificate_chain_is_unknown():
    """A browser fills in the intermediate certificate itself, so "the visitor sees a warning" is unproven."""
    site = clean_site()
    site.entry.tls = Tls(
        valid=False,
        error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer "
        "certificate (_ssl.c:1000)",
    )
    result = run_level(1, site)["infra.tls.invalid"]
    assert result.status == "unknown"
    assert "lanac" in reason(result.reason)


def test_expired_certificate_stays_a_finding():
    site = clean_site()
    site.entry.tls = Tls(valid=False, error="certificate verify failed: certificate has expired")
    assert run_level(1, site)["infra.tls.invalid"].status == "finding"


def test_one_probe_200_other_404_is_not_a_finding():
    """One probe can hit an existing URL by chance."""
    site = clean_site()
    site.soft404 = Soft404(
        probes=[
            Soft404Probe(url="https://cist.rs/abc", status=200),
            Soft404Probe(url="https://cist.rs/abc.html", status=404),
        ]
    )
    assert run_level(1, site)["infra.soft404"].status == "ok"


def test_soft404_records_similarity_with_home_page():
    """Similarity ≥ 90 % is hard evidence and must go into `evidence`."""
    site = clean_site()
    text = site.home.text_sample
    site.soft404 = Soft404(
        probes=[
            Soft404Probe(url="https://cist.rs/abc", status=200, text_sample=text),
            Soft404Probe(url="https://cist.rs/abc.html", status=200, text_sample=text),
        ]
    )
    evidence = run_level(1, site)["infra.soft404"].findings[0].evidence
    assert evidence["similarity"] == 1.0
    assert evidence["hard_evidence"] is True


def test_duplicate_requires_different_path_groups():
    """The same title on eight blog posts is not the same as a whole site as one page."""
    site = clean_site()
    site.pages = [
        copy.deepcopy(site.home),
        *[
            p
            for p in (
                copy.deepcopy(site.pages[1]),
                copy.deepcopy(site.pages[1]),
                copy.deepcopy(site.pages[1]),
            )
        ],
    ]
    for index, page in enumerate(site.pages[1:], start=1):
        page.url = page.final_url = f"https://cist.rs/blog/{index}"
        page.title = "Isti naslov"
        page.canonical_normalized = f"https://cist.rs/blog/{index}"
    assert run_level(1, site)["seo.title.duplicate"].status == "ok"


def test_duplicate_counts_a_page_once_even_when_two_urls_lead_to_it():
    """A language URL that leads back to the home page is not one more page with the same title (BUG-029)."""
    site = clean_site()
    _all_pages(site, title="Dobrodošli")
    site.pages[1].final_url = site.home.final_url
    assert run_level(1, site)["seo.title.duplicate"].findings[0].evidence["page_count"] == 4


def test_compression_is_not_reported_for_small_html():
    """The 50 kB floor exists so that small pages do not make noise."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 20_000
    assert run_level(1, site)["perf.compression.missing"].status == "ok"


# --------------------------------------------------------------------------- #
# BUG-003: a status ≠ 200 is not the same as "does not exist". Only 404 and 410
# claim that; 401/403/429/5xx mean access was refused, so we do not know.
# Equivalence classes of the status: exists / not found / unknown.
# --------------------------------------------------------------------------- #
EXISTS, NOT_FOUND, UNKNOWN = "ok", "finding", "unknown"

FILE_STATUSES = [
    pytest.param(200, EXISTS, id="ke-exists-200"),
    pytest.param(404, NOT_FOUND, id="ke-not-found-404"),
    pytest.param(410, NOT_FOUND, id="ke-not-found-410"),
    pytest.param(401, UNKNOWN, id="ke-refused-401"),
    pytest.param(403, UNKNOWN, id="ke-refused-403"),
    pytest.param(429, UNKNOWN, id="ke-refused-429"),
    pytest.param(500, UNKNOWN, id="ke-server-error-500"),
    pytest.param(503, UNKNOWN, id="ke-server-error-503"),
]


@pytest.mark.parametrize("status, expected", FILE_STATUSES)
def test_robots_status_decides_outcome(status, expected):
    site = clean_site()
    site.robots.status = status
    result = run_level(1, site)["infra.robots.missing"]
    assert result.status == expected
    if expected == UNKNOWN:
        assert str(status) in reason(result.reason)


@pytest.mark.parametrize("status, expected", FILE_STATUSES)
def test_sitemap_status_decides_outcome(status, expected):
    site = clean_site()
    site.sitemap.status = status
    if status != 200:
        site.sitemap.urls.clear()
    result = run_level(1, site)["infra.sitemap.missing"]
    assert result.status == expected
    if expected == UNKNOWN:
        assert str(status) in reason(result.reason)


def test_dead_first_sitemap_next_to_a_working_one_is_not_a_finding():
    """`status` is the status of the first `Sitemap:` in robots.txt; URLs from the second mean one exists."""
    site = clean_site()
    site.sitemap.status = 404
    assert site.sitemap.urls
    assert run_level(1, site)["infra.sitemap.missing"].status == "ok"


def test_sitemap_200_without_any_url_is_a_finding():
    """Boundary value: the file exists, but it is empty."""
    site = clean_site()
    site.sitemap.urls.clear()
    assert run_level(1, site)["infra.sitemap.missing"].status == NOT_FOUND


def _probes(domain: str, first: int, second: int) -> Soft404:
    return Soft404(
        probes=[
            Soft404Probe(url=f"https://{domain}/abc123", status=first),
            Soft404Probe(url=f"https://{domain}/abc123.html", status=second),
        ]
    )


@pytest.mark.parametrize(
    "first, second, expected",
    [
        pytest.param(200, 200, NOT_FOUND, id="tab-both-200"),
        pytest.param(404, 404, EXISTS, id="tab-both-404"),
        pytest.param(410, 404, EXISTS, id="tab-410-and-404"),
        pytest.param(200, 404, EXISTS, id="tab-200-and-404"),
        pytest.param(403, 403, UNKNOWN, id="tab-both-refused"),
        pytest.param(200, 403, UNKNOWN, id="tab-200-and-refused"),
        pytest.param(404, 503, UNKNOWN, id="tab-404-and-error"),
        pytest.param(429, 429, UNKNOWN, id="tab-both-429"),
    ],
)
def test_soft404_decision_table(first, second, expected):
    """Decision table over the statuses of the two probes; `NOT_FOUND` here means a finding."""
    site = clean_site()
    site.soft404 = _probes(site.domain, first, second)
    assert run_level(1, site)["infra.soft404"].status == expected


def test_blocked_site_gets_no_findings_from_refused_requests():
    """BUG-003, recorded: the whole site returns 403 "Checking your browser before accessing"."""
    site = clean_site()
    site.robots.status = 403
    site.sitemap.status = 403
    site.sitemap.urls.clear()
    site.soft404 = _probes(site.domain, 403, 403)
    results = run_level(1, site)
    for check_id in ("infra.robots.missing", "infra.sitemap.missing", "infra.soft404"):
        assert results[check_id].status == UNKNOWN, check_id
        assert "403" in reason(results[check_id].reason)


# --------------------------------------------------------------------------- #
# A language finding may claim only what is true (ADR-022)
# --------------------------------------------------------------------------- #
def test_mismatch_message_claims_nothing_about_search_engines():
    """Google determines the page language from the content and does not use the `lang` attribute.

    The claim "search engines offer it to the wrong market" would be false in an email to the
    client. The accurate and verifiable argument is the screen reader.
    """
    site = clean_site()
    site.home.lang = "en-US"
    found = run_level(1, site)["i18n.lang.mismatch"].findings[0]
    assert "pretraživač" not in render(found).client.lower()
    assert "čitač" in render(found).client.lower()
    assert found.severity == "medium"


# --------------------------------------------------------------------------- #
# BUG-004: a site fetched over http after https failed. The certificate was
# not checked, so "ok" must not stand
# --------------------------------------------------------------------------- #
def test_tls_is_unknown_when_https_failed_and_site_was_fetched_over_http():
    from sitetriage.models import SnapshotError

    site = clean_site()
    site.entry.requested_url = "http://cist.rs/"
    site.errors.append(SnapshotError("entry", "tls_handshake", "UNEXPECTED_EOF_WHILE_READING"))
    result = run_level(1, site)["infra.tls.invalid"]
    assert result.status == "unknown"
    assert "UNEXPECTED_EOF_WHILE_READING" in reason(result.reason)
