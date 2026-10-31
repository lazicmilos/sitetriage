"""Level 2: Playwright, assembling the `BrowserSnapshot`.

Playwright is imported lazily, so the tool works when level 2 is not installed.

The most serious pitfall in the project is measuring weight. `encodedBodySize` from the
Performance API returns 0 for cross-origin resources without `Timing-Allow-Origin`, so a
site with all its images on a CDN comes out at 2 kB. That is why this module listens to
network traffic and adds up the real responses (ADR-016).
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import os
import socket
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sitetriage import __version__, addresses, store
from sitetriage.config import get, user_agent
from sitetriage.fetch.http import measure_link
from sitetriage.fetch.page import LINKS_KEPT, TEXT_SAMPLE_CHARS, internal
from sitetriage.fetch.urls import collapse_ws
from sitetriage.models import (
    BrowserSnapshot,
    ConsoleStats,
    DomStats,
    NetworkProfile,
    NetworkStats,
    OversizedImage,
    SiteSnapshot,
    SnapshotError,
    TimingStats,
)

log = logging.getLogger("sitetriage.browser")

CONSOLE_SAMPLES = 5
CLOSE_TIMEOUT_S = 10
# Responses without a body by definition: they are not "unmeasured", their size is known and zero.
NO_BODY_STATUSES = {204, 304}

_SCROLL = """
async () => {
  await new Promise((resolve) => {
    let moved = 0;
    const step = () => {
      window.scrollBy(0, window.innerHeight);
      moved += window.innerHeight;
      if (moved < document.body.scrollHeight && moved < 50000) setTimeout(step, 100);
      else resolve();
    };
    step();
  });
  window.scrollTo(0, 0);
}
"""

_DOM = """
(ratio) => {
  const images = Array.from(document.images);
  let withoutAlt = 0, emptyAlt = 0, unmeasured = 0;
  const oversized = [];
  for (const img of images) {
    // Three states, not two: a missing attribute is an error, alt="" is correct.
    if (!img.hasAttribute('alt')) withoutAlt++;
    else if (img.getAttribute('alt').trim() === '') emptyAlt++;

    const cw = img.clientWidth, ch = img.clientHeight;
    const nw = img.naturalWidth, nh = img.naturalHeight;
    if (cw === 0 || nw === 0) { unmeasured++; continue; }
    if (nw / cw > ratio) {
      oversized.push({ src: img.currentSrc || img.src, nw, nh, cw, ch, ratio: nw / cw });
    }
  }
  return {
    h1: document.querySelectorAll('h1').length,
    total: images.length,
    withoutAlt, emptyAlt, unmeasured, oversized,
    links: Array.from(document.links, (a) => a.href),
    lang: document.documentElement.getAttribute('lang'),
    text: document.body ? document.body.innerText : '',
    title: document.title,
    description: document.querySelector('meta[name="description" i]')?.getAttribute('content') ?? '',
    canonical: document.querySelector('link[rel~="canonical" i]')?.getAttribute('href') ?? '',
  };
}
"""

_TIMING = """
() => {
  const nav = performance.getEntriesByType('navigation')[0];
  if (!nav) return null;
  return {
    dcl: Math.round(nav.domContentLoadedEventEnd) || null,
    load: Math.round(nav.loadEventEnd) || null,
  };
}
"""


class _Recorder:
    """Adds up the real responses as they arrive (ADR-016).

    Every request belongs to the phase in which it **started**: before or after the `load` of the
    main document. The body of a request started before `load` counts towards "until load" even
    when it arrives later. After `load` come analytics, chat and lazy images, so the same site once
    had 179 and another time 281 requests; the number that goes to the client must repeat.
    """

    def __init__(self) -> None:
        self.request_count = 0
        self.total_bytes = 0
        self.by_type: dict[str, int] = {}
        self.unmeasured = 0
        self.requests_at_load = 0
        self.bytes_at_load = 0
        self.by_type_at_load: dict[str, int] = {}
        self.unmeasured_at_load = 0
        self.bytes_by_url: dict[str, int] = {}
        self.console_errors = 0
        self.console_warnings = 0
        self.samples: list[str] = []
        self._loaded = False
        # By `id`, because fake requests in tests have no hash; the value keeps the object alive, so the
        # `id` is not reused.
        self._pre_load: dict[int, Any] = {}
        self._tasks: dict[asyncio.Task, bool] = {}

    def on_request(self, request: Any) -> None:
        self.request_count += 1
        if not self._loaded:
            self.requests_at_load += 1
            self._pre_load[id(request)] = request

    def on_load(self, _page: Any) -> None:
        self._loaded = True

    def on_response(self, response: Any) -> None:
        at_load = id(response.request) in self._pre_load
        self._tasks[asyncio.create_task(self._measure(response, at_load))] = at_load

    def on_console(self, message: Any) -> None:
        if message.type == "error":
            self.console_errors += 1
            if len(self.samples) < CONSOLE_SAMPLES:
                self.samples.append(message.text[:300])
        elif message.type == "warning":
            self.console_warnings += 1

    def on_page_error(self, error: Any) -> None:
        self.console_errors += 1
        if len(self.samples) < CONSOLE_SAMPLES:
            self.samples.append(str(error)[:300])

    async def _measure(self, response: Any, at_load: bool) -> None:
        url = response.url
        # `data:` and `blob:` are already in the HTML; counting them counts them twice.
        if url.startswith(("data:", "blob:")):
            return
        status = response.status
        # Redirects have no body; counting them as "unmeasured" would falsely push the count over
        # the threshold.
        if 300 <= status < 400:
            return

        size: int | None = 0 if status in NO_BODY_STATUSES else None
        if size is None:
            try:
                # Transferred bytes, not the decompressed body: the sentence says "transfers X MB", and JS
                # and CSS travel compressed (BUG-016). It throws for cached and aborted responses.
                size = (await response.request.sizes())["responseBodySize"]
            except Exception:  # noqa: BLE001
                header = response.headers.get("content-length")
                size = int(header) if header and header.isdigit() else None

        if size is None:
            # Do not count zero: zero is exactly the Performance API error described above.
            self.unmeasured += 1
            self.unmeasured_at_load += at_load
            return

        kind = _resource_type(response)
        self.total_bytes += size
        self.by_type[kind] = self.by_type.get(kind, 0) + size
        self.bytes_by_url[url] = size
        if at_load:
            self.bytes_at_load += size
            self.by_type_at_load[kind] = self.by_type_at_load.get(kind, 0) + size

    async def drain(self, timeout: float) -> None:
        """A body that does not arrive within `timeout` is unmeasured, not zero.

        A stream or a video never finishes, and the size measurement waits for it without
        end; on klinika.example that blocked the whole run forever (BUG-002).
        """
        if self._tasks:
            _done, pending = await asyncio.wait(self._tasks, timeout=timeout)
            for task in pending:
                task.cancel()
                self.unmeasured += 1
                self.unmeasured_at_load += self._tasks[task]
            self._tasks.clear()


def _resource_type(response: Any) -> str:
    try:
        kind = response.request.resource_type
    except Exception:  # noqa: BLE001
        return "other"
    return kind if kind in {"image", "script", "stylesheet", "document", "font", "media"} else "other"


def est_waste_kb(transfer_bytes: int, natural: Sequence[int], client: Sequence[int]) -> float:
    """Estimated waste of an oversized image: rough, but it gives a number you can write in an email."""
    natural_area = natural[0] * natural[1]
    if not transfer_bytes or natural_area <= 0:
        return 0.0
    used = (client[0] * client[1] * 4) / natural_area
    return round(max(transfer_bytes / 1024 * (1 - used), 0.0), 1)


def network_profile(config: dict) -> NetworkProfile:
    profile = get(config, "network_profile")
    return NetworkProfile(profile["download_mbps"], profile["upload_mbps"], profile["latency_ms"])


def network_conditions(profile: NetworkProfile) -> dict[str, Any]:
    """Parameters for CDP `Network.emulateNetworkConditions`, which takes throughput in bytes per second:
    4.8 Mb/s = 600 000 B/s."""
    return {
        "offline": False,
        "latency": profile.latency_ms,
        "downloadThroughput": profile.download_mbps * 1_000_000 / 8,
        "uploadThroughput": profile.upload_mbps * 1_000_000 / 8,
    }


class _LoadSlot:
    """Exclusive right to load until `load` (BUG-006).

    Three sites loading at the same time share one connection and make each other's
    load time up to 4.6× longer. So they load one at a time; scrolling, the DOM and the
    weight measurement still run in parallel. It is released exactly once, however the
    measurement ended.
    """

    def __init__(self, lock: asyncio.Lock | None) -> None:
        self._lock = lock
        self._held = False

    async def acquire(self) -> None:
        if self._lock is not None:
            await self._lock.acquire()
            self._held = True

    def release(self) -> None:
        if self._held:
            self._held = False
            self._lock.release()


async def capture(
    browser: Any,
    site: SiteSnapshot,
    config: dict,
    ua: str,
    slot: _LoadSlot | None = None,
    light: bool = False,
) -> BrowserSnapshot:
    """A new context per domain = an empty cache.

    Without it a second domain on the same CDN measures a falsely lower weight.
    `slot` is released as soon as the page has loaded, so the next site measures its own time
    without someone else's traffic on the connection.
    """
    from playwright.async_api import Error as PlaywrightError

    url = (site.home.final_url if site.home else None) or (
        site.entry.final_url if site.entry else f"https://{site.domain}/"
    )
    snapshot = BrowserSnapshot(
        domain=site.domain,
        url=url,
        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        scanner_version=__version__,
        browser_version=browser.version,
        light=light,
    )
    timeout_ms = get(config, "browser.timeout_s") * 1000
    recorder = _Recorder()
    context = await browser.new_context(
        viewport={
            "width": get(config, "browser.viewport_width"),
            "height": get(config, "browser.viewport_height"),
        },
        device_scale_factor=1,
        user_agent=ua,
        ignore_https_errors=True,  # an invalid certificate is a level 1 finding, not a reason to stop level 2
        # `route` does not see requests sent by a service worker (ADR-006).
        service_workers="block",
    )
    try:
        await context.route("**/*", _address_guard(addresses.allowlist(config), PlaywrightError, site.domain))
        page = await context.new_page()
        if not light:
            # Before navigation, so the first request also goes over the emulated link (ADR-010).
            profile = network_profile(config)
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.emulateNetworkConditions", network_conditions(profile))
            snapshot.network_profile = profile
        page.on("request", recorder.on_request)
        page.on("load", recorder.on_load)
        page.on("response", recorder.on_response)
        page.on("console", recorder.on_console)
        page.on("pageerror", recorder.on_page_error)

        reached = "error"
        debug = {"domain": site.domain}
        log.debug("goto %s (light %s)", url, light, extra=debug)
        try:
            response = await page.goto(url, wait_until="load", timeout=timeout_ms)
            reached = "load"
            log.debug("reached load: status %s", response.status if response else None, extra=debug)
            # An error page (e.g. a 403 from bot protection) is not the home page; measuring it gives a
            # false weight and false findings (BUG-021).
            if response is not None and response.status >= 400:
                snapshot.errors.append(SnapshotError("http_status", str(response.status), response.url))
                snapshot.status = "failed"
                return snapshot
        except PlaywrightError as exc:
            if "Timeout" not in type(exc).__name__ and "imeout" not in str(exc):
                snapshot.errors.append(SnapshotError("goto", type(exc).__name__, str(exc)[:300]))
                log.debug("goto failed: %s", type(exc).__name__, extra=debug)
                snapshot.status = "failed"
                return snapshot
            reached = "timeout"
            log.debug("goto timed out after %d ms", timeout_ms, extra=debug)

        if reached == "load":
            # Network idle is welcome, not required.
            with contextlib.suppress(PlaywrightError):
                await page.wait_for_load_state(
                    "networkidle", timeout=get(config, "browser.idle_after_load_ms")
                )
        if slot is not None:
            slot.release()

        # Without scrolling all lazy images have naturalWidth == 0 and the check silently finds
        # nothing.
        try:
            await page.evaluate(_SCROLL)
            await page.wait_for_timeout(get(config, "browser.scroll_pause_ms"))
        except PlaywrightError as exc:
            snapshot.errors.append(SnapshotError("scroll", type(exc).__name__, str(exc)[:200]))

        await recorder.drain(get(config, "browser.drain_timeout_s"))
        snapshot.timing = await _read_timing(page, reached, PlaywrightError)
        snapshot.dom = await _read_dom(page, recorder, config, PlaywrightError, snapshot)
        snapshot.network = NetworkStats(
            request_count=recorder.request_count,
            total_bytes=recorder.total_bytes,
            bytes_by_type=recorder.by_type,
            unmeasured_responses=recorder.unmeasured,
            requests_at_load=recorder.requests_at_load,
            bytes_at_load=recorder.bytes_at_load,
            bytes_by_type_at_load=recorder.by_type_at_load,
            unmeasured_at_load=recorder.unmeasured_at_load,
        )
        log.debug(
            "measured %d requests, %d bytes (%d requests, %d bytes until load), %d unmeasured",
            recorder.request_count,
            recorder.total_bytes,
            recorder.requests_at_load,
            recorder.bytes_at_load,
            recorder.unmeasured,
            extra=debug,
        )
        snapshot.console = ConsoleStats(
            errors=recorder.console_errors,
            warnings=recorder.console_warnings,
            samples=recorder.samples,
        )
        snapshot.status = "ok" if reached == "load" else "partial"
    except Exception as exc:  # noqa: BLE001 — an exception never leaves the domain
        snapshot.errors.append(SnapshotError("browser", type(exc).__name__, str(exc)[:300]))
        snapshot.status = "failed"
    finally:
        if slot is not None:
            slot.release()
        # Closing can hang too; after the hard limit it must not extend it.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(context.close(), CLOSE_TIMEOUT_S)
    return snapshot


async def _read_timing(page: Any, reached: str, error_type: type) -> TimingStats:
    try:
        raw = await page.evaluate(_TIMING)
    except error_type:
        raw = None
    if not raw:
        return TimingStats(reached=reached)
    return TimingStats(
        dom_content_loaded_ms=raw.get("dcl"),
        load_ms=raw.get("load") if reached == "load" else None,
        reached=reached,
    )


async def _read_dom(
    page: Any, recorder: _Recorder, config: dict, error_type: type, snapshot: BrowserSnapshot
) -> DomStats:
    try:
        raw = await page.evaluate(_DOM, get(config, "thresholds.perf.image_ratio"))
    except error_type as exc:
        snapshot.errors.append(SnapshotError("dom", type(exc).__name__, str(exc)[:200]))
        return DomStats()

    oversized = [
        OversizedImage(
            src=item["src"],
            natural=[item["nw"], item["nh"]],
            client=[item["cw"], item["ch"]],
            ratio=round(item["ratio"], 2),
            est_waste_kb=est_waste_kb(
                recorder.bytes_by_url.get(item["src"], 0),
                [item["nw"], item["nh"]],
                [item["cw"], item["ch"]],
            ),
        )
        for item in raw["oversized"]
    ]
    oversized.sort(key=lambda image: -image.est_waste_kb)
    # Links and text drawn by JavaScript are seen only by level 2 (ADR-015, ADR-017).
    links = internal(raw["links"], snapshot.url)
    text = collapse_ws(raw["text"]) or ""
    return DomStats(
        h1_count=raw["h1"],
        images_total=raw["total"],
        images_without_alt_attr=raw["withoutAlt"],
        images_empty_alt=raw["emptyAlt"],
        oversized_images=oversized,
        images_unmeasured=raw["unmeasured"],
        internal_links=links[:LINKS_KEPT],
        internal_links_total=len(links),
        lang=raw["lang"],
        text_sample=text[:TEXT_SAMPLE_CHARS],
        text_length=len(text),
        title=raw["title"],
        meta_description=raw["description"],
        canonical=raw["canonical"],
    )


async def _capture_within_limit(
    browser: Any,
    site: SiteSnapshot,
    config: dict,
    ua: str,
    load_lock: asyncio.Lock | None = None,
    light: bool = False,
) -> BrowserSnapshot:
    """Hard per-domain limit: the last defence against a hang we do not know about yet.

    One hanging domain must not stop the other 199. Waiting for the loading turn is not
    work on the domain, so it does not count towards the limit.
    """
    limit_s = get(config, "browser.max_seconds_per_domain")
    slot = _LoadSlot(load_lock)
    await slot.acquire()
    started = time.monotonic()
    try:
        snapshot = await asyncio.wait_for(capture(browser, site, config, ua, slot, light), limit_s)
    except TimeoutError:
        log.error("level 2 aborted after %s s", limit_s, extra={"domain": site.domain})
        snapshot = BrowserSnapshot(
            domain=site.domain,
            url=(site.home.final_url if site.home else None) or "",
            fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            status="failed",
            errors=[SnapshotError("browser", "timeout", f"aborted after the hard limit of {limit_s} s")],
        )
    finally:
        slot.release()
    snapshot.elapsed_ms = round((time.monotonic() - started) * 1000)
    return snapshot


def _quiet_on_closed_context(previous: Callable | None) -> Callable:
    """After the hard limit Playwright's navigation is left without a reader; when the context
    closes, its error is an expected consequence of the abort, not a fault (BUG-007). Everything else
    goes to the handler that was installed before level 2.
    """

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if type(context.get("exception")).__name__ == "TargetClosedError":
            return
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    return handler


def _address_guard(allowed: addresses.Allowlist, error_type: type, domain: str) -> Any:
    """Every browser request goes through the same address check as level 1 (ADR-006).

    Chromium resolves the name itself, so there is a window between this check and its
    connection, and `route` does not see WebSocket or redirects. That is why production also
    adds an egress filter at the network level; this is the first line of defence, not the only one.

    For a refused request Chromium reports only `ERR_BLOCKED_BY_CLIENT`, both when the address is
    private and when DNS did not answer. So the reason goes to the log, once per host.
    """
    verdicts: dict[tuple[str, int], str | None] = {}

    async def handler(route: Any) -> None:
        parts = urlsplit(route.request.url)
        allowed_request = False
        if parts.scheme in ("http", "https") and parts.hostname:
            port = parts.port or (443 if parts.scheme == "https" else 80)
            key = (parts.hostname, port)
            if key not in verdicts:
                verdicts[key] = await _refusal_reason(parts.hostname, port, allowed)
                if verdicts[key]:
                    reason = verdicts[key]
                    log.info("level 2 refuses %s:%d: %s", *key, reason, extra={"domain": domain})
            allowed_request = verdicts[key] is None
        # After the hard limit the context is closed, so the route's answer has nowhere to go.
        with contextlib.suppress(error_type):
            if allowed_request:
                await route.continue_()
            else:
                await route.abort("blockedbyclient")

    return handler


async def _refusal_reason(host: str, port: int, allowed: addresses.Allowlist) -> str | None:
    """The reason the request must not go, or `None`. Chromium picks the address itself, so the request
    may go only if all addresses are allowed, and a failed DNS lookup is a refusal: nobody knows where
    the connection would go."""
    loop = asyncio.get_running_loop()
    try:
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            if exc.errno != socket.EAI_AGAIN:
                raise
            # A temporary error is retried once, as on level 1: the verdict holds for the whole domain.
            await asyncio.sleep(0.5)
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return f"DNS did not resolve the name ({exc})"
    ips = sorted({info[4][0] for info in infos})
    blocked = [ip for ip in ips if not addresses.may_connect(ip, host, port, allowed)]
    if not ips or blocked:
        return f"address is not public: {', '.join(blocked) or '—'}"
    return None


async def _browser_ua(browser: Any, config: dict) -> str:
    """The UA Chromium sends itself, with the operator identity at the end, as Googlebot does.

    Services a site loads choose content by UA: for a UA that is not a browser, ads run extra
    auctions and Google Fonts sends a larger format, so weight, requests and time were up to twice
    as high as for a visitor in Chrome (BUG-019). Bot protection refuses the "HeadlessChrome" part
    with a 403, so it becomes "Chrome"; the operator identity stays (BUG-021).
    """
    cdp = await browser.new_browser_cdp_session()
    try:
        ua = (await cdp.send("Browser.getVersion"))["userAgent"].replace("HeadlessChrome/", "Chrome/")
        return f"{ua} {user_agent(config)}"
    finally:
        await cdp.detach()


class BrowserLaunchError(Exception):
    """Chromium did not start: Playwright is installed, but its browser is missing or broken (BUG-01).

    It concerns the whole run, not one domain, so `capture_all` lets it through to the pipeline.
    """


def _launch_options(config: dict) -> dict[str, Any]:
    """An installed Chromium instead of Playwright's, when the environment already has one.

    Without site isolation: full Chromium loads an iframe from another site (YouTube, maps) in a separate
    process, and the network profile set on the page does not slow that process down (ADR-010).
    """
    path = get(config, "browser.executable_path") or os.environ.get("SITETRIAGE_CHROMIUM", "")
    options: dict[str, Any] = {"args": ["--disable-site-isolation-trials"]}
    return options | ({"executable_path": path} if path else {})


async def capture_all(
    sites: Iterable[SiteSnapshot],
    config: dict,
    snapshot_dir: Path | None = None,
    on_done: Callable[[BrowserSnapshot], None] | None = None,
    *,
    light: bool = False,
) -> dict[str, BrowserSnapshot]:
    """One browser instance for the whole run, a new context per domain.

    `on_done` is called for every finished domain, after the write to disk. `light` measures without
    the profile and without the loading queue: weight, requests and the DOM, but not time (BUG-020).
    """
    sites = list(sites)
    if not sites:
        return {}

    # Once per run, before the first site: the profile can only slow down (ADR-018). Without the
    # profile the link does not matter.
    link_mbps = None if light else await measure_link(config)
    required = get(config, "network_profile.min_link_ratio") * get(config, "network_profile.download_mbps")
    if link_mbps is not None and link_mbps < required:
        log.warning(
            "the real link is %s Mb/s, but measuring under the profile needs at least %g Mb/s; "
            "load time will be unknown",
            link_mbps,
            required,
        )

    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(_quiet_on_closed_context(previous))
    try:
        return await _capture_all(sites, config, snapshot_dir, on_done, link_mbps, light)
    finally:
        # Leftover errors of closed contexts arrive when the garbage collector picks up abandoned
        # futures. So that is done here, while the handler is still installed (BUG-007), and
        # afterwards the loop gets its own back: in a long-lived process level 2 must not
        # change global state for good.
        gc.collect()
        loop.set_exception_handler(previous)


def _available_kb() -> int | None:
    """`MemAvailable` from /proc/meminfo; outside Linux there is none."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def _context_count(config: dict, light: bool) -> int:
    """How many domains go through the browser at once; every context costs hundreds of MB of RAM.

    Full level 2 loads one at a time (BUG-006), so `browser.concurrency` is enough for it. For light
    level 2 the number of contexts is exactly what sets the speed, and the machine sets the limit: one
    per free GB, at most two per core and at most 8 (ADR-019). `browser.light_concurrency` ≥ 1 fixes it.
    """
    if not light:
        return get(config, "browser.concurrency")
    if configured := get(config, "browser.light_concurrency"):
        return configured
    kb = _available_kb()
    if kb is None:
        return get(config, "browser.concurrency")
    return max(1, min(8, kb // 1_048_576, 2 * (os.cpu_count() or 1)))


async def _capture_all(
    sites: list[SiteSnapshot],
    config: dict,
    snapshot_dir: Path | None,
    on_done: Callable[[BrowserSnapshot], None] | None,
    link_mbps: float | None,
    light: bool = False,
) -> dict[str, BrowserSnapshot]:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    results: dict[str, BrowserSnapshot] = {}
    at_once = _context_count(config, light)
    log.info("level 2%s: %d domains at once", " light" if light else "", at_once)
    limit = asyncio.Semaphore(at_once)
    # Pages load one at a time; the rest of the measurement runs in parallel (BUG-006, ADR-018).
    load_lock = asyncio.Lock() if get(config, "browser.serial_load") and not light else None

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(**_launch_options(config))
        except PlaywrightError as exc:
            raise BrowserLaunchError(str(exc).strip().splitlines()[0]) from exc
        try:
            ua = await _browser_ua(browser, config)

            async def one(site: SiteSnapshot) -> tuple[str, BrowserSnapshot]:
                async with limit:
                    log.info("level 2 starts", extra={"domain": site.domain})
                    snapshot = await _capture_within_limit(browser, site, config, ua, load_lock, light)
                    snapshot.link_mbps = link_mbps
                    if snapshot_dir is not None:
                        store.write_browser(snapshot_dir, snapshot)
                    log.info(
                        "level 2 done: %d B in %d requests (%s)",
                        snapshot.network.total_bytes,
                        snapshot.network.request_count,
                        snapshot.timing.reached,
                        extra={"domain": site.domain},
                    )
                    if on_done is not None:
                        on_done(snapshot)
                    return site.domain, snapshot

            gathered = await asyncio.gather(*(one(s) for s in sites), return_exceptions=True)
        finally:
            await browser.close()

    for site, item in zip(sites, gathered, strict=True):
        if isinstance(item, BaseException):
            log.error("level 2 lost: %r", item, extra={"domain": site.domain})
            results[site.domain] = BrowserSnapshot(
                domain=site.domain,
                errors=[SnapshotError("browser", type(item).__name__, str(item)[:300])],
            )
        else:
            results[item[0]] = item[1]
    return results
