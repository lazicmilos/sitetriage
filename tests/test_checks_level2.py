"""Level 2 checks. The same three: positive, negative, `unknown`."""

from __future__ import annotations

import pytest
from factories import clean_browser, findings, run_level, statuses

from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.fetch.browser import network_conditions, network_profile
from sitetriage.messages import LANGS, reason, render
from sitetriage.models import DomStats, NetworkStats, OversizedImage, TimingStats

LEVEL2_IDS = sorted(s.check_id for s in registry.REGISTRY.values() if s.level == 2)


def test_clean_page_has_no_findings():
    results = run_level(2, clean_browser())
    assert findings(results) == set()
    assert set(statuses(results).values()) == {"ok"}


def test_all_registered_checks_are_covered():
    assert sorted(run_level(2, clean_browser())) == LEVEL2_IDS


POSITIVE_CASES = {
    "perf.page.weight": lambda b: (
        setattr(b.network, "bytes_at_load", 25_000_000),
        setattr(b.network, "total_bytes", 25_000_000),
    ),
    "perf.request.count": lambda b: (
        setattr(b.network, "requests_at_load", 175),
        setattr(b.network, "request_count", 175),
    ),
    "perf.load.time": lambda b: setattr(b.timing, "load_ms", 9_000),
    "seo.h1.missing": lambda b: setattr(b.dom, "h1_count", 0),
    "seo.h1.multiple": lambda b: setattr(b.dom, "h1_count", 5),
    "a11y.img.alt.missing": lambda b: setattr(
        b, "dom", DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=0)
    ),
    "perf.img.oversized": lambda b: setattr(
        b.dom,
        "oversized_images",
        [
            OversizedImage(
                src=f"https://cist.rs/s{i}.jpg",
                natural=[4000, 2667],
                client=[760, 507],
                ratio=5.26,
                est_waste_kb=600,
            )
            for i in range(3)
        ],
    ),
    "qa.console.errors": lambda b: setattr(b.console, "errors", 5),
}


@pytest.mark.parametrize("check_id", LEVEL2_IDS)
def test_positive_finding(check_id):
    browser = clean_browser()
    POSITIVE_CASES[check_id](browser)
    result = run_level(2, browser)[check_id]
    assert result.status == "finding", f"{check_id}: expected a finding, got {result.status}"
    found = result.findings[0]
    assert any(isinstance(v, (int, float)) for v in found.evidence.values())
    for lang in LANGS:
        assert "{" not in render(found, lang).client and "{" not in render(found, lang).tech
    assert found.level == 2


# --------------------------------------------------------------------------- #
# Tiered thresholds: one finding per check, at the highest severity that applies
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "total_bytes, expected",
    [
        # Boundary values (three points) for the thresholds calibrated on list A (ADR-020):
        # p50 2.2 MB, p75 3.6 MB, p90 7.3 MB transferred until `load` without video (docs/kalibracija.md).
        pytest.param(1_000_000, None, id="ke-light"),
        pytest.param(1_999_999, None, id="gv-2MB-minus"),
        pytest.param(2_000_000, None, id="gv-2MB"),
        pytest.param(2_000_001, "medium", id="gv-2MB-plus"),
        pytest.param(3_999_999, "medium", id="gv-4MB-minus"),
        pytest.param(4_000_000, "medium", id="gv-4MB"),
        pytest.param(4_000_001, "high", id="gv-4MB-plus"),
        pytest.param(6_999_999, "high", id="gv-7MB-minus"),
        pytest.param(7_000_000, "high", id="gv-7MB"),
        pytest.param(7_000_001, "critical", id="gv-7MB-plus"),
        pytest.param(22_100_000, "critical", id="ke-heaviest-measured"),
    ],
)
def test_page_weight_is_tiered(total_bytes, expected):
    browser = clean_browser()
    browser.network.bytes_at_load = total_bytes
    result = run_level(2, browser)["perf.page.weight"]
    if expected is None:
        assert result.status == "ok"
    else:
        assert len(result.findings) == 1, "not three findings for the same page"
        assert result.findings[0].severity == expected


@pytest.mark.parametrize("count, expected", [(50, None), (75, "medium"), (175, "high")])
def test_request_count_is_tiered(count, expected):
    browser = clean_browser()
    browser.network.requests_at_load = count
    result = run_level(2, browser)["perf.request.count"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


@pytest.mark.parametrize("load_ms, expected", [(2_000, None), (7_000, "medium"), (10_000, "high")])
def test_load_time_is_tiered(load_ms, expected):
    browser = clean_browser()
    browser.timing.load_ms = load_ms
    result = run_level(2, browser)["perf.load.time"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


def test_one_speed_source_for_sentence_and_measurement():
    """ADR-010: the speed from `[network_profile]` goes both to Chromium and into the sentences; there is no
    second key."""
    cfg = load_config()
    assert "mobile_speed_mbps" not in cfg["thresholds"]["perf"]
    cfg["network_profile"]["download_mbps"] = 9.6
    profile = network_profile(cfg)
    assert network_conditions(profile)["downloadThroughput"] == 1_200_000, "CDP takes bytes per second"
    browser = clean_browser(network_profile=profile)
    browser.network.bytes_at_load = 20_000_000
    browser.timing.load_ms = 9_000
    ctx = registry.Context(domain=browser.domain, industry="other", config=cfg)
    found = {r.check_id: r.findings[0] for r in registry.run(2, browser, ctx) if r.status == "finding"}
    speeds = [found[c].evidence["speed_mbps"] for c in ("perf.page.weight", "perf.load.time")]
    assert speeds == [9.6, 9.6]


@pytest.mark.parametrize("reached, load_ms", [("load", 9_000), ("timeout", None)])
def test_load_time_without_network_profile_is_unknown(reached, load_ms):
    """A snapshot without a profile was measured on the real connection: a sentence about the simulated
    connection would not be true."""
    browser = clean_browser(network_profile=None)
    browser.timing = TimingStats(load_ms=load_ms, reached=reached)
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "unknown" and "bez mrežnog profila" in reason(result.reason)


@pytest.mark.parametrize("reached, load_ms", [("load", 9_000), ("timeout", None)])
def test_load_time_on_link_slower_than_profile_is_unknown(reached, load_ms):
    """ADR-018: the profile only slows down; on a slower link the time was measured at that link's speed,
    so it is overestimated."""
    browser = clean_browser(link_mbps=5.0)
    browser.timing = TimingStats(load_ms=load_ms, reached=reached)
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "unknown"
    assert "5" in reason(result.reason) and "9,6 Mb/s" in reason(result.reason)
    assert run_level(2, clean_browser(link_mbps=9.6))["perf.load.time"].status == "ok", "limit is inclusive"


def test_load_time_on_light_level2_is_not_applicable():
    """BUG-020: a site outside the limit was measured without a profile, so there is no time. That is not an
    unknown."""
    result = run_level(2, clean_browser(light=True, network_profile=None, link_mbps=None))["perf.load.time"]
    assert result.status == "not_applicable" and result.reason.code == "requires.level2_full"
    assert "lagano" in reason(result.reason)


def test_load_time_without_measured_link_is_unknown():
    result = run_level(2, clean_browser(link_mbps=None))["perf.load.time"]
    assert result.status == "unknown" and "nije izmerena" in reason(result.reason)


# --------------------------------------------------------------------------- #
# Three states of the alt attribute, not two
# --------------------------------------------------------------------------- #
def test_empty_alt_is_not_an_error():
    """`alt=""` is the correct way to mark a decorative image.

    A tool that reports it tells the client that something done right is broken,
    and you send that in an email.
    """
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_without_alt_attr=0, images_empty_alt=20)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


def test_evidence_tells_missing_attribute_from_empty():
    """The ordinacija.example fixture: the evidence must say 28/30 and tell the states apart."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=2)
    evidence = run_level(2, browser)["a11y.img.alt.missing"].findings[0].evidence
    assert evidence["without_alt"] == 28
    assert evidence["total"] == 30
    assert evidence["empty_alt"] == 2


def test_few_images_give_no_finding():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=4, images_without_alt_attr=4)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


@pytest.mark.parametrize(
    "industry, expected",
    [("other", "low"), ("hotel", "low"), ("healthcare", "medium"), ("institution", "medium")],
)
def test_alt_severity_depends_on_industry(industry, expected):
    """Healthcare and institutions have legal exposure on accessibility."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=10, images_without_alt_attr=6)
    result = run_level(2, browser, industry=industry)["a11y.img.alt.missing"]
    assert result.findings[0].severity == expected


def test_high_share_becomes_high_regardless_of_industry():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28)
    result = run_level(2, browser, industry="other")["a11y.img.alt.missing"]
    assert result.findings[0].severity == "high"


# --------------------------------------------------------------------------- #
# `unknown`: a measurement you do not trust is worse than none (ADR-016)
# --------------------------------------------------------------------------- #
def test_weight_without_load_is_unknown():
    """ADR-016: without `load` the "until load" measure is incomplete, so even a weight of 20 MB is not a
    claim."""
    browser = clean_browser()
    browser.timing.reached = "timeout"
    browser.network.total_bytes = browser.network.bytes_at_load = 20_000_000
    result = run_level(2, browser)["perf.page.weight"]
    assert result.status == "unknown" and result.reason.code == "load_incomplete"


def test_weight_and_request_count_ignore_what_starts_after_load():
    """After `load` come analytics, chat and lazy images: the same site had 179, then 281 requests."""
    browser = clean_browser()
    browser.network.total_bytes = 20_000_000
    browser.network.request_count = 281
    results = run_level(2, browser)
    assert results["perf.page.weight"].status == "ok"
    assert results["perf.request.count"].status == "ok"


def test_total_after_load_is_only_in_the_technical_sentence():
    browser = clean_browser()
    browser.network.bytes_at_load = 6_000_000
    browser.network.total_bytes = 9_000_000
    found = run_level(2, browser)["perf.page.weight"].findings[0]
    assert found.severity == "high", "6 MB until load, not 9 MB in total"
    assert "prenosi 6 MB" in render(found, "sr").client
    assert "9000000" in render(found, "sr").tech


def test_too_many_unmeasured_responses_is_unknown():
    browser = clean_browser()
    browser.network = NetworkStats(
        request_count=40, requests_at_load=40, bytes_at_load=500_000, unmeasured_at_load=9
    )
    result = run_level(2, browser)["perf.page.weight"]
    assert result.status == "unknown"
    assert "nije izmereno" in reason(result.reason)


def test_failed_browser_gives_unknown_everywhere():
    browser = clean_browser(status="failed")
    results = run_level(2, browser)
    assert sorted(results) == LEVEL2_IDS
    assert set(statuses(results).values()) == {"unknown"}
    assert all(r.reason for r in results.values())


def test_timeout_without_exceeding_threshold_is_unknown_not_ok():
    """Measurements after a timeout are incomplete, and the checks must know it."""
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    results = run_level(2, browser)
    assert results["perf.page.weight"].status == "unknown"
    assert results["perf.request.count"].status == "unknown"


def test_images_are_unknown_when_page_did_not_finish_loading():
    """Zero images after a cut-off does not mean the site has none, nor that they all have a description."""
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    browser.dom = DomStats(h1_count=1, images_total=0)
    result = run_level(2, browser)["a11y.img.alt.missing"]
    assert result.status == "unknown" and "slike nisu prebrojane" in reason(result.reason)


def test_timeout_is_itself_a_load_time_finding():
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "finding"
    assert result.findings[0].severity == "high"


def test_h1_is_unknown_when_page_did_not_finish_loading():
    """An empty h1 after a timeout is not a finding: the h1 can arrive later."""
    browser = clean_browser()
    browser.dom.h1_count = 0
    browser.timing = TimingStats(load_ms=None, reached="timeout")
    assert run_level(2, browser)["seo.h1.missing"].status == "unknown"


def test_zero_oversized_with_unmeasured_images_is_unknown():
    """Without this you cannot tell whether "0 oversized" is a result or a failed measurement."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_unmeasured=15)
    result = run_level(2, browser)["perf.img.oversized"]
    assert result.status == "unknown"
    assert "nije izmereno" in reason(result.reason)


def _image(src: str, waste_kb: float) -> OversizedImage:
    return OversizedImage(src=src, natural=[900, 900], client=[255, 280], ratio=3.53, est_waste_kb=waste_kb)


def test_svg_and_data_images_are_not_oversized():
    """BUG-023: an SVG placeholder for lazy loading (data:, viewBox 0 0 0 0) gave "about 0 kB"."""
    browser = clean_browser()
    browser.dom.oversized_images = [
        _image("data:image/svg+xml,%3Csvg%20viewBox='0%200%200%200'%3E%3C/svg%3E", 0),
        _image("data:image/png;base64,iVBORw0KGgo=", 0),
        _image("https://cist.rs/logo.svg?v=2", 4),
        _image("https://cist.rs/ikona.SVG", 3),
    ]
    assert run_level(2, browser)["perf.img.oversized"].status == "ok"


def test_oversized_images_without_measured_transfer_are_unknown_not_0_kb():
    """BUG-023: without a measured transfer the waste is 0, and the sentence said "about 0 kB"."""
    browser = clean_browser()
    browser.dom.oversized_images = [_image(f"https://cist.rs/s{i}.webp", 0) for i in range(3)]
    result = run_level(2, browser)["perf.img.oversized"]
    assert result.status == "unknown"
    assert reason(result.reason) == "3 prevelike slike nemaju izmeren prenos, pa višak nije poznat"


def test_finding_counts_only_images_with_measured_waste():
    browser = clean_browser()
    browser.dom.oversized_images = [_image(f"https://cist.rs/s{i}.jpg", 100) for i in range(3)]
    browser.dom.oversized_images.append(_image("https://cist.rs/nemerena.jpg", 0))
    found = run_level(2, browser)["perf.img.oversized"].findings[0]
    assert (found.evidence["image_count"], found.evidence["kb"]) == (3, 300)
    assert "nemerena" not in " ".join(found.evidence_urls)


def test_same_image_several_times_on_page_counts_once_with_largest_waste():
    """BUG-030: cloned slides counted the same image, downloaded once, as several images."""
    browser = clean_browser()
    browser.dom.oversized_images = [
        _image("https://cist.rs/slajd.jpg", 300),
        _image("https://cist.rs/slajd.jpg", 300),
        _image("https://cist.rs/slajd.jpg", 120),
        _image("https://cist.rs/logo.png", 50),
        _image("https://cist.rs/baner.jpg", 80),
    ]
    found = run_level(2, browser)["perf.img.oversized"].findings[0]
    assert (found.evidence["image_count"], found.evidence["kb"], found.evidence["worst_image"]) == (
        3, 430, "https://cist.rs/slajd.jpg"
    )
    assert found.evidence_urls == ["https://cist.rs/slajd.jpg", "https://cist.rs/baner.jpg", "https://cist.rs/logo.png"]


@pytest.mark.parametrize(
    "images, expected",
    [
        pytest.param([("a.jpg", 100)] * 3, "ok", id="gv-1-image-3-times"),
        pytest.param([("a.jpg", 100), ("a.jpg", 100), ("b.jpg", 100)], "ok", id="gv-2-images-minus"),
        pytest.param([("a.jpg", 100), ("a.jpg", 100), ("b.jpg", 100), ("c.jpg", 100)], "finding",
                     id="gv-3-images"),
        pytest.param([("a.jpg", 350)] * 3, "ok", id="gv-700kB-duplicates-sum-1050"),
        pytest.param([("a.jpg", 400), ("b.jpg", 300)] * 2, "ok", id="gv-700kB-without-duplicates"),
        pytest.param([("a.jpg", 401), ("b.jpg", 300)] * 2, "finding", id="gv-700kB-plus"),
        pytest.param([("a.jpg", 0)] * 3, "ok", id="unmeasured-same-3-times-is-not-unknown"),
    ],
)
def test_oversized_threshold_after_removing_duplicates(images, expected):
    """BUG-030: the threshold (≥ 3 images or > 700 kB) is measured over distinct images."""
    browser = clean_browser()
    browser.dom.oversized_images = [_image(f"https://cist.rs/{name}", kb) for name, kb in images]
    assert run_level(2, browser)["perf.img.oversized"].status == expected


def test_repeated_svg_and_data_images_still_do_not_count():
    browser = clean_browser()
    browser.dom.oversized_images = [_image("https://cist.rs/a.svg", 400)] * 3 + [
        _image("data:image/png;base64,AAA=", 400)
    ] * 3 + [_image("https://cist.rs/b.jpg", 100)]
    assert run_level(2, browser)["perf.img.oversized"].status == "ok"


def test_large_byte_waste_fires_finding_below_three_images():
    """The threshold is ≥ 3 images **or** waste > 700 kB."""
    browser = clean_browser()
    browser.dom.oversized_images = [
        OversizedImage(
            src="https://cist.rs/hero.jpg",
            natural=[4000, 2667],
            client=[760, 507],
            ratio=5.26,
            est_waste_kb=1840,
        )
    ]
    assert run_level(2, browser)["perf.img.oversized"].status == "finding"


# --------------------------------------------------------------------------- #
# ADR-016: video does not count toward the weight threshold; it downloads for as
# long as the measurement allows
# --------------------------------------------------------------------------- #
def test_video_does_not_count_toward_weight_threshold():
    """The same site transferred 77 MB of video in one run and 39 MB in another."""
    browser = clean_browser()
    browser.network.bytes_at_load = 23_800_000
    browser.network.bytes_by_type_at_load = {"media": 22_000_000, "image": 1_500_000, "script": 300_000}
    assert run_level(2, browser)["perf.page.weight"].status == "ok"


def test_weight_finding_mentions_video_separately():
    browser = clean_browser()
    browser.network.bytes_at_load = 30_000_000
    browser.network.bytes_by_type_at_load = {"media": 8_000_000, "image": 21_000_000, "script": 1_000_000}
    found = run_level(2, browser)["perf.page.weight"].findings[0]
    assert found.severity == "critical", "22 MB without video is above 7 MB"
    assert found.evidence["mb"] == 22.0
    assert found.evidence["video_mb"] == 8.0
    assert found.variant == "video"
    assert "video" in render(found, "sr").client and "video" in render(found, "en").client
