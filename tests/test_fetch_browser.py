"""Level 2 against a local server and a real Chromium.

Marked `browser`: skipped when Playwright or Chromium is not installed
(`chromium_starts` in `conftest.py`).
"""

from __future__ import annotations

import asyncio
import gzip
import struct
import zlib
from pathlib import Path

import pytest
from factories import run_level
from localserver import FakeSite, Response

from sitetriage import addresses, pipeline
from sitetriage.config import load_config, user_agent
from sitetriage.fetch.browser import est_waste_kb
from sitetriage.models import (
    BrowserSnapshot,
    Entry,
    NetworkProfile,
    PageSnapshot,
    SiteSnapshot,
    from_dict,
    to_jsonable,
)

pytestmark = pytest.mark.browser


def png(width: int, height: int) -> bytes:
    """A minimal valid PNG, so `naturalWidth` is real, without a new dependency."""
    raw = b"".join(b"\x00" + b"\xc8\x32\x32" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


HEAVY_PAGE = """<!doctype html><html lang="sr"><head><title>Teška strana</title>
<style>img{{width:100px}} .daleko{{margin-top:4000px}}</style></head>
<body>
  <h2>Nema h1 na ovoj strani</h2>
  <img src="/velika.png">
  <img src="/velika.png" alt="">
  <img src="/velika.png" alt="opisana slika">
  {without_alt}
  <div class="daleko"><img src="/lenja.png" loading="lazy"></div>
  <script src="/tezak.js"></script>
  <script>null.x = 1;</script>
  <script>undefined.y = 2;</script>
  <script>console.error("prva"); console.error("druga"); console.warn("upozorenje");</script>
</body></html>"""


def heavy_site() -> FakeSite:
    without_alt = "".join('<img src="/velika.png">' for _ in range(7))
    return FakeSite(
        extra={
            "/": Response(HEAVY_PAGE.format(without_alt=without_alt).encode()),
            "/velika.png": Response(png(800, 600), headers={"content-type": "image/png"}),
            "/lenja.png": Response(png(900, 600), headers={"content-type": "image/png"}),
            "/tezak.js": Response(
                b"window.__x = '" + b"y" * 300_000 + b"';",
                headers={"content-type": "application/javascript"},
            ),
        }
    )


def capture_one(site: FakeSite, config: dict | None = None):
    from sitetriage.fetch.browser import capture_all

    fake = SiteSnapshot(
        domain=site.base_url,
        pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        entry=Entry(requested_url=site.base_url + "/", final_url=site.base_url + "/", status=200),
    )
    return asyncio.run(capture_all([fake], config or load_config()))[site.base_url]


@pytest.fixture(scope="module")
def snapshot():
    with heavy_site() as site:
        yield capture_one(site)


TRAFFIC_AROUND_LOAD = b"""<!doctype html><html><body><h1>Strana</h1>
<script>
fetch('/sporo.bin');
window.addEventListener('load', () => setTimeout(() => fetch('/posle.bin'), 100));
</script><img src="/drzi.png"></body></html>"""


@pytest.fixture(scope="module")
def around_load():
    """ADR-016: a request before `load` whose body arrives after it, and a request started after `load`."""
    extra = {
        "/": Response(TRAFFIC_AROUND_LOAD),
        # `load` waits for the image. Without it `load` comes right after the script, and with `route`
        # Playwright reports `request` only when the request reaches the network, so under load the
        # fetch was seen after `load`.
        "/drzi.png": Response(png(1, 1), headers={"content-type": "image/png"}, delay=0.5),
        # Headers at once, body after 3 s: the response is seen before `drain`, the body arrives after `load`.
        "/sporo.bin": Response(b"s" * 150_000, stall=3.0),
        "/posle.bin": Response(b"p" * 200_000),
    }
    with FakeSite(extra=extra) as site:
        yield capture_one(site)


def test_request_after_load_is_not_in_the_weight(around_load):
    network = around_load.network
    assert network.bytes_at_load < 200_000, "posle.bin (200 kB) is not in the weight"
    assert network.total_bytes - network.bytes_at_load >= 200_000, "but it is in the total, for information"
    assert network.request_count > network.requests_at_load


def test_body_arriving_after_load_for_a_request_before_load_counts(around_load):
    assert around_load.timing.load_ms < 3000, "the body of sporo.bin must arrive after `load`"
    assert around_load.network.bytes_at_load >= 150_000


# ADR-010: 600 kB on an emulated 4.8 Mb/s link (600 000 B/s) takes about 1 s.
HEAVY_JS = b"//" + b"x" * 600_000


def with_heavy_script() -> dict[str, Response]:
    return {
        "/": Response(b"<!doctype html><h1>Strana</h1><script src='/tezak.js'></script>"),
        "/tezak.js": Response(HEAVY_JS),
    }


def test_profile_slows_down_loading():
    """Only the lower bound is checked, so the test is not flaky."""
    with FakeSite(extra=with_heavy_script()) as site:
        assert capture_one(site).timing.load_ms >= 1000


def test_profile_also_applies_to_a_cross_origin_iframe(monkeypatch):
    """Full Chromium, like a system one, loads an iframe from another site in a separate process (OOPIF),
    and the profile set on the page does not slow that process down. `localhost` and `127.0.0.1` are
    two sites."""
    from sitetriage.fetch import browser

    launch_options = browser._launch_options
    monkeypatch.setattr(browser, "_launch_options", lambda c: {**launch_options(c), "channel": "chromium"})
    with FakeSite(extra=with_heavy_script()) as frame:
        port = frame.address[1]
        # conftest allows `127.0.0.1:port`, and `localhost` also resolves to `::1`
        allowlist = addresses.allowlist
        monkeypatch.setattr(addresses, "allowlist", lambda cfg: allowlist(cfg) | {("localhost", port)})
        page = f"<!doctype html><h1>Strana</h1><iframe src='http://localhost:{port}/'></iframe>"
        with FakeSite(extra={"/": Response(page.encode())}) as site:
            assert capture_one(site).timing.load_ms >= 1000


def test_light_measurement_has_no_profile_and_no_link_measurement(monkeypatch):
    """BUG-020: a site over the cap measures weight, requests and the DOM without the profile; time is left
    to full level 2."""
    from sitetriage.fetch import browser as module

    async def must_not(_config):
        raise AssertionError("the light measurement does not measure the link")

    monkeypatch.setattr(module, "measure_link", must_not)
    with heavy_site() as site:
        fake = SiteSnapshot(
            domain=site.base_url,
            pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        )
        captured = asyncio.run(module.capture_all([fake], load_config(), light=True))[site.base_url]
    assert (captured.light, captured.network_profile, captured.link_mbps) == (True, None, None)
    assert captured.status == "ok" and captured.network.bytes_at_load > 300_000
    assert captured.dom.h1_count == 0 and len(captured.dom.oversized_images) > 0


@pytest.mark.parametrize(
    "free_gb, cores, configured, expected",
    [
        pytest.param(3.5, 4, 0, 3, id="ke-machine-with-8-gb"),
        pytest.param(0.5, 4, 0, 1, id="gv-at-least-1"),
        pytest.param(20, 16, 0, 8, id="gv-at-most-8"),
        pytest.param(16, 2, 0, 4, id="gv-two-per-core"),
        pytest.param(None, 4, 0, 3, id="nv-no-meminfo"),
        pytest.param(20, 16, 5, 5, id="tab-fixed"),
    ],
)
def test_light_level_2_picks_context_count_by_machine(monkeypatch, free_gb, cores, configured, expected):
    """ADR-019: light level 2 does not measure time, so it runs at the machine's speed; full level 2 stays
    on `browser.concurrency`."""
    from sitetriage.fetch import browser as module

    config = load_config()
    config["browser"]["light_concurrency"] = configured
    kb = None if free_gb is None else int(free_gb * 1_048_576)
    monkeypatch.setattr(module, "_available_kb", lambda: kb)
    monkeypatch.setattr(module.os, "cpu_count", lambda: cores)
    assert module._context_count(config, light=True) == expected
    assert module._context_count(config, light=False) == 3


def test_free_memory_is_read_from_proc_meminfo():
    from sitetriage.fetch import browser as module

    kb = module._available_kb()
    assert kb is None if not Path("/proc/meminfo").exists() else kb > 0


def test_profile_is_in_the_snapshot_and_the_json(snapshot):
    profile = NetworkProfile(download_mbps=4.8, upload_mbps=1.5, latency_ms=150)
    assert snapshot.network_profile == profile
    assert from_dict(BrowserSnapshot, to_jsonable(snapshot)).network_profile == profile
    assert pipeline._environment([snapshot])["network_profile"] == profile
    assert snapshot.link_mbps == pipeline._environment([snapshot])["link_mbps"] == 100.0


def test_slow_link_is_in_the_snapshot_and_warns_once(monkeypatch, caplog):
    """ADR-018: the link is measured once per run, before level 2."""
    from sitetriage.fetch import browser

    async def slow(config: dict) -> float:
        return 3.2

    monkeypatch.setattr(browser, "measure_link", slow)
    with FakeSite() as site:
        captured = capture_one(site)
    assert captured.link_mbps == 3.2
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "3.2 Mb/s" in r.getMessage()]
    assert len(warnings) == 1


def test_browser_records_text_and_lang_after_javascript():
    """ADR-017: the raw HTML has neither `lang` nor text; JavaScript sets both."""
    page = (
        "<!doctype html><html><body><script>"
        "document.documentElement.lang = 'sr';"
        "document.body.insertAdjacentHTML("
        "'beforeend', '<p>Dobrodošli   u   ordinaciju. Zakažite pregled.</p>');"
        "</script></body></html>"
    ).encode()
    with FakeSite(extra={"/": Response(page)}) as site:
        captured = capture_one(site)
    assert captured.dom.lang == "sr"
    assert captured.dom.text_sample == "Dobrodošli u ordinaciju. Zakažite pregled."
    assert captured.dom.text_length == len(captured.dom.text_sample)


def test_browser_records_title_description_and_canonical_after_javascript():
    """Level 1 reads them from the raw HTML; an SPA sets them with JavaScript, and Google runs JS."""
    page = (
        b"<!doctype html><html><head></head><body><script>"
        b"document.title = 'Iz JS-a';"
        b"document.head.insertAdjacentHTML('beforeend', '<meta name=\"Description\" content=\"Opis iz JS-a\">"
        b"<link rel=\"canonical\" href=\"/zvanicna\">');"
        b"</script></body></html>"
    )
    with FakeSite(extra={"/": Response(page)}) as site:
        dom = capture_one(site).dom
    assert (dom.title, dom.meta_description, dom.canonical) == ("Iz JS-a", "Opis iz JS-a", "/zvanicna")

    with FakeSite(extra={"/": Response(b"<!doctype html><html><body>prazno</body></html>")}) as site:
        dom = capture_one(site).dom
    assert (dom.title, dom.meta_description, dom.canonical) == ("", "", "")


def test_browser_identifies_with_its_own_user_agent_plus_operator_identity():
    """BUG-019: with a UA that is not a browser, ads ran extra auctions and Google Fonts sent a larger
    format, so weight, requests and time were higher than for a visitor in Chrome."""
    page = (
        b"<!doctype html><html><body><p id='u'></p>"
        b"<script>u.textContent = navigator.userAgent</script></body></html>"
    )
    with FakeSite(extra={"/": Response(page)}) as site:
        ua = capture_one(site).dom.text_sample
    assert ua.startswith("Mozilla/5.0 ") and "Chrome/" in ua, ua
    assert ua.endswith(" " + user_agent(load_config())), ua
    # BUG-021: bot protection refuses "HeadlessChrome" with a 403.
    assert "Headless" not in ua, ua


def test_error_page_on_level_2_is_a_failed_capture():
    """BUG-021: a 403 bot protection page was measured as the home page (1 request, 358 B)."""
    with FakeSite(extra={"/": Response(b"<h1>Forbidden</h1>", status=403)}) as site:
        captured = capture_one(site)
    assert captured.status == "failed"
    assert [(e.stage, e.kind) for e in captured.errors] == [("http_status", "403")]


def test_browser_records_internal_links_from_the_rendered_dom():
    """ADR-015: only level 2 sees a link drawn by JavaScript; an external link is not internal."""
    page = (
        b"<!doctype html><html><body><a href='/o-nama'>o nama</a><a href='https://drugi.rs/'>x</a>"
        b"<script>document.body.insertAdjacentHTML('beforeend', \"<a href='/iz-js'>js</a>\")</script>"
        b"</body></html>"
    )
    with FakeSite(extra={"/": Response(page)}) as site:
        captured = capture_one(site)
    assert captured.dom.internal_links == [f"{site.base_url}/o-nama", f"{site.base_url}/iz-js"]
    assert captured.dom.internal_links_total == 2


# --------------------------------------------------------------------------- #
# Weight measurement (ADR-016): the most serious pitfall in the project
# --------------------------------------------------------------------------- #
def test_weight_is_measured_from_network_traffic(snapshot):
    """The Performance API would return almost zero here for cross-origin resources."""
    assert snapshot.status == "ok"
    assert snapshot.network.total_bytes > 300_000, "the 300 kB script must show in the total"
    # Ten `<img>` with the same URL are one request: the browser merges them itself.
    assert snapshot.network.request_count >= 4
    assert snapshot.network.bytes_by_type.get("script", 0) > 250_000
    assert snapshot.network.bytes_by_type.get("image", 0) > 0


def test_weight_counts_transferred_bytes_not_decompressed():
    """BUG-016: the sentence says "transfers X MB", so what was really transferred is counted.

    `response.body()` returns the decompressed body. JS and CSS travel compressed, so for sites
    with many scripts the total was even several times the real transfer.
    """
    script = b"window.__x = '" + b"y" * 300_000 + b"';"
    page = b"<html><head><title>S</title></head><body><h1>S</h1><script src='/s.js'></script></body></html>"
    with FakeSite(
        extra={
            "/": Response(page),
            "/s.js": Response(
                script, headers={"content-type": "application/javascript", "content-encoding": "gzip"}
            ),
        }
    ) as site:
        captured = capture_one(site)
    assert captured.network.bytes_by_type["script"] == len(gzip.compress(script))


def test_unmeasured_responses_are_counted_not_hidden(snapshot):
    assert snapshot.network.unmeasured_responses == 0


def test_redirects_are_not_counted_as_unmeasured():
    with FakeSite(
        extra={
            "/": Response(b"", status=302, headers={"Location": "/kraj"}),
            "/kraj": Response(b"<html><h1>Kraj</h1></html>"),
        }
    ) as site:
        captured = capture_one(site)
    assert captured.network.unmeasured_responses == 0
    assert captured.dom.h1_count == 1


def test_timing_is_recorded(snapshot):
    assert snapshot.timing.reached == "load"
    assert snapshot.timing.load_ms is not None and snapshot.timing.load_ms > 0


# --------------------------------------------------------------------------- #
# DOM: accessibility and oversized images
# --------------------------------------------------------------------------- #
def test_h1_is_counted_from_the_rendered_page(snapshot):
    assert snapshot.dom.h1_count == 0
    assert run_level(2, snapshot)["seo.h1.missing"].status == "finding"


def test_alt_states_are_counted_separately(snapshot):
    """Three states, not two: missing, empty (decorative) and present."""
    assert snapshot.dom.images_total == 11
    assert snapshot.dom.images_without_alt_attr == 9
    assert snapshot.dom.images_empty_alt == 1


def test_lazy_image_is_measured_because_the_page_is_scrolled_to_the_bottom(snapshot):
    """Without scrolling it would have naturalWidth == 0 and silently drop out of the measurement."""
    assert snapshot.dom.images_unmeasured == 0
    assert any("lenja.png" in image.src for image in snapshot.dom.oversized_images)


def test_oversized_images_with_estimated_waste(snapshot):
    assert len(snapshot.dom.oversized_images) >= 4
    worst = snapshot.dom.oversized_images[0]
    assert worst.ratio > 2.5
    assert worst.natural[0] in (800, 900) and worst.client[0] == 100
    assert worst.est_waste_kb > 0


def test_the_same_image_repeated_on_the_page_is_one_image(snapshot):
    """BUG-030: /velika.png ten times and /lenja.png once are two images, below the threshold of three."""
    assert len({image.src for image in snapshot.dom.oversized_images}) == 2
    assert run_level(2, snapshot)["perf.img.oversized"].status == "ok"


def test_console_errors_are_counted(snapshot):
    assert snapshot.console.errors >= 4  # two pageerrors and two console.error calls
    assert snapshot.console.warnings >= 1
    assert snapshot.console.samples


# --------------------------------------------------------------------------- #
# An empty cache per domain
# --------------------------------------------------------------------------- #
def test_second_run_measures_the_same_because_the_cache_is_empty():
    """A new context per domain; otherwise a second site on the same CDN comes out lighter."""
    with heavy_site() as site:
        first = capture_one(site)
        second = capture_one(site)
    assert second.network.total_bytes == pytest.approx(first.network.total_bytes, rel=0.02)
    assert second.network.unmeasured_responses == 0


# --------------------------------------------------------------------------- #
# Hangs, recorded on klinika.example: one response whose body never arrived blocked the
# whole run forever (BUG-002). Everything here must finish in time.
# --------------------------------------------------------------------------- #
STREAM_PAGE = b"""<!doctype html><html lang="sr"><head><title>Strim</title></head>
<body><h1>Strana sa strimom</h1><script>fetch('/strim').then(r => r.text())</script></body></html>"""


def test_body_that_never_arrives_is_unmeasured_not_a_hang():
    """A stream or video that never ends: `load` arrives, the response body never does."""
    import time

    cfg = load_config()
    cfg["browser"]["drain_timeout_s"] = 2
    with FakeSite(
        extra={
            "/": Response(STREAM_PAGE),
            "/strim": Response(b"x" * 10_000, headers={"content-type": "text/plain"}, stall=120),
        }
    ) as site:
        started = time.monotonic()
        captured = capture_one(site, cfg)
        duration = time.monotonic() - started

    assert duration < 20, f"level 2 waited {duration:.0f} s for the stream body"
    assert captured.status == "ok"
    assert captured.dom.h1_count == 1, "the rest of the measurement must survive"
    assert captured.network.unmeasured_responses >= 1, "the stream is unmeasured, not zero bytes"


def test_hard_per_domain_limit_aborts_level_2():
    """The last defence: any hang we do not know about yet must not stop the run."""
    import time

    cfg = load_config()
    cfg["browser"]["max_seconds_per_domain"] = 3
    with FakeSite(
        extra={
            "/": Response(b"<html><h1>Spora</h1><img src='/spora.png'></html>"),
            "/spora.png": Response(png(10, 10), headers={"content-type": "image/png"}, delay=30),
        }
    ) as site:
        started = time.monotonic()
        captured = capture_one(site, cfg)
        duration = time.monotonic() - started

    assert duration < 15, f"the 3 s hard limit was not respected: {duration:.0f} s"
    assert captured.status == "failed"
    assert any("hard limit" in e.detail for e in captured.errors), captured.errors
    assert captured.elapsed_ms >= 3000


def test_level_2_duration_is_in_the_snapshot():
    """ADR-020: the `browser.max_seconds_per_domain` limit is set from the duration distribution."""
    import time

    with FakeSite(
        extra={
            "/": Response(b"<html><h1>Strana</h1><img src='/spora.png'></html>"),
            "/spora.png": Response(png(10, 10), headers={"content-type": "image/png"}, delay=1.0),
        }
    ) as site:
        started = time.monotonic()
        captured = capture_one(site)
        duration_ms = (time.monotonic() - started) * 1000

    assert 1000 <= captured.elapsed_ms <= duration_ms


# --------------------------------------------------------------------------- #
# The waste estimate formula: a pure function, no browser
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "transfer_kb, natural, client, expected",
    [
        (2150, [4000, 2667], [760, 507], 1838.0),  # the worked example from the specification: ≈ 1840 kB
        (100, [100, 100], [100, 100], 0.0),  # an image of the right size has no waste
        (0, [4000, 2667], [760, 507], 0.0),  # no estimate without a measured transfer
    ],
)
def test_waste_estimate(transfer_kb, natural, client, expected):
    assert est_waste_kb(transfer_kb * 1024, natural, client) == pytest.approx(expected, abs=2.0)


def test_unmeasured_image_gives_no_negative_waste():
    assert est_waste_kb(1000, [10, 10], [500, 500]) == 0.0


# --------------------------------------------------------------------------- #
# BUG-006: load time is measured while nobody else is loading
# --------------------------------------------------------------------------- #
def two_loads(serial_load: bool) -> tuple[dict[str, float], dict[str, float]]:
    """The moments two sites requested their HTML and image; the image is 1 s late and holds `load`."""
    import time

    from sitetriage.fetch.browser import capture_all

    moments: dict[str, dict[str, float]] = {}

    def page(name: str):
        def response() -> Response:
            moments.setdefault(name, {})["html"] = time.monotonic()
            return Response(b"<html><h1>Strana</h1><img src='/spora.png'></html>")

        return response

    def image(name: str):
        def response() -> Response:
            moments.setdefault(name, {})["image"] = time.monotonic()
            return Response(png(10, 10), headers={"content-type": "image/png"}, delay=1.0)

        return response

    with FakeSite(extra={"/": page("a"), "/spora.png": image("a")}) as a, FakeSite(
        extra={"/": page("b"), "/spora.png": image("b")}
    ) as b:
        sites = [
            SiteSnapshot(
                domain=s.base_url,
                pages=[PageSnapshot(url=s.base_url + "/", final_url=s.base_url + "/", status=200)],
                entry=Entry(requested_url=s.base_url + "/", final_url=s.base_url + "/", status=200),
            )
            for s in (a, b)
        ]
        cfg = load_config()
        cfg["browser"]["concurrency"] = 2
        cfg["browser"]["serial_load"] = serial_load
        asyncio.run(capture_all(sites, cfg))

    first, second = sorted(moments.values(), key=lambda t: t["html"])
    return first, second


def test_loads_of_different_sites_do_not_overlap():
    """Three sites loading at the same time share the connection and make each other's `load` up to
    4.6× longer (measured in the run over 100 domains). So loading until `load` goes one at a time;
    scrolling and reading the DOM still run in parallel.
    """
    first, second = two_loads(serial_load=True)
    # The first site's image is 1 s late and holds its `load`; the second may start only after that.
    assert second["html"] >= first["image"] + 0.9, (
        f"the second site started {second['html'] - first['html']:.2f} s after the first, "
        f"while the first was still loading"
    )


def test_without_serial_loading_sites_load_in_parallel():
    """ADR-018: under the network profile every context has its own link, so an experiment measures this."""
    first, second = two_loads(serial_load=False)
    assert second["html"] < first["image"] + 0.5, "the second site waited for the first to load"


def test_abort_after_the_hard_limit_leaves_no_error_in_the_log(caplog):
    """BUG-007: after the abort Playwright's navigation is left without a reader, so asyncio later
    reports "Future exception was never retrieved": an ERROR for something that is not a fault.
    """
    import gc
    import logging

    cfg = load_config()
    cfg["browser"]["max_seconds_per_domain"] = 2
    with caplog.at_level(logging.ERROR, logger="asyncio"), FakeSite(
        extra={
            "/": Response(b"<html><h1>Spora</h1><img src='/spora.png'></html>"),
            "/spora.png": Response(png(10, 10), headers={"content-type": "image/png"}, delay=20),
        }
    ) as site:
        captured = capture_one(site, cfg)
        gc.collect()

    assert captured.status == "failed"
    leftovers = [r.getMessage() for r in caplog.records if r.name == "asyncio"]
    assert not leftovers, leftovers


def test_exception_handler_is_restored_after_level_2():
    """Level 2 silences the errors of closed contexts only while it runs. A web worker lives long,
    so after level 2 its loop must have its own handler, not ours."""
    from sitetriage.fetch.browser import capture_all

    def ours(loop, context):
        loop.default_exception_handler(context)

    async def main(site):
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(ours)
        fake = SiteSnapshot(
            domain=site.base_url,
            pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        )
        await capture_all([fake], load_config())
        return loop.get_exception_handler()

    with FakeSite() as site:
        assert asyncio.run(main(site)) is ours


def test_handler_silences_only_a_closed_context():
    """Everything except a closed-context error goes to the handler installed before level 2."""
    from sitetriage.fetch.browser import _quiet_on_closed_context

    class TargetClosedError(Exception):
        pass

    received = []
    handler = _quiet_on_closed_context(lambda _loop, context: received.append(context))
    handler(None, {"exception": TargetClosedError()})
    handler(None, {"exception": ValueError("a real fault")})
    assert [type(c["exception"]).__name__ for c in received] == ["ValueError"]


def test_page_that_does_not_open_is_failed_with_a_reason():
    """An error on opening that is not a timeout (refused connection) → `failed`, not a crash."""
    from sitetriage.fetch.browser import capture_all

    dead = SiteSnapshot(
        domain="http://127.0.0.1:1",
        pages=[PageSnapshot(url="http://127.0.0.1:1/", final_url="http://127.0.0.1:1/", status=200)],
        entry=Entry(requested_url="http://127.0.0.1:1/", final_url="http://127.0.0.1:1/", status=200),
    )
    cfg = load_config()
    cfg["net"]["allowed_private"] = ["127.0.0.1:1"]  # so the refused connection fails, not the address guard
    captured = asyncio.run(capture_all([dead], cfg))["http://127.0.0.1:1"]
    assert captured.status == "failed"
    assert captured.errors and captured.errors[0].stage == "goto"
    assert "ERR_BLOCKED_BY_CLIENT" not in captured.errors[0].detail


def test_system_chromium_from_config_and_environment(monkeypatch):
    from sitetriage.fetch.browser import _launch_options

    cfg = load_config()
    monkeypatch.delenv("SITETRIAGE_CHROMIUM", raising=False)
    assert "executable_path" not in _launch_options(cfg)
    monkeypatch.setenv("SITETRIAGE_CHROMIUM", "/usr/bin/chromium")
    assert _launch_options(cfg)["executable_path"] == "/usr/bin/chromium"
    cfg["browser"]["executable_path"] = "/opt/chrome"
    assert _launch_options(cfg)["executable_path"] == "/opt/chrome", "the config file wins"
