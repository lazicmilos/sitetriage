"""Level 1: fetching and assembling the `SiteSnapshot`.

The only level 1 layer that touches the network. Checks import nothing from here; they get
a finished snapshot.

Two semaphores: the global one limits you, the per-host one protects them. The per-host one is
always 1, and that is the line between a tool and an attack.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import random
import socket
import ssl
import time
import zlib
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpcore
import httpx

from sitetriage import __version__, addresses, store
from sitetriage.config import get, user_agent
from sitetriage.fetch import page as page_builder
from sitetriage.fetch import robots as robots_parser
from sitetriage.fetch import sitemap as sitemap_parser
from sitetriage.fetch.urls import host_of, normalize, same_site
from sitetriage.models import (
    Budget,
    DomainInput,
    Entry,
    HostVariant,
    PageSnapshot,
    RobotsInfo,
    SitemapInfo,
    SiteSnapshot,
    SnapshotError,
    Soft404,
    Soft404Probe,
    Tls,
)

log = logging.getLogger("sitetriage.fetch")

# Statuses on which the domain is given up for this run, without a retry.
GIVE_UP_STATUSES = {429, 503}
PROBE_SUFFIXES = ("", ".html")
# A DNS error is an error of the name, so http on the same name does not help either.
DNS = frozenset({"dns", "dns_nxdomain", "dns_nodata", "dns_temporary"})
# `dns_nodata`: the name exists but has no address. On Windows EAI_NODATA is the same as EAI_NONAME,
# so it goes first and NONAME overwrites it there; both mean the site is unreachable.
DNS_ERRNO = {
    socket.EAI_NODATA: "dns_nodata",
    socket.EAI_NONAME: "dns_nxdomain",
    socket.EAI_AGAIN: "dns_temporary",
}
# Encodings we decompress ourselves, chunk by chunk. Only these are announced to the server: httpx
# would announce br and zstd as soon as their package is installed, and we do not decompress them.
ACCEPT_ENCODING = "gzip, deflate"
# One decompression call returns at most this many bytes at once. httpx decompresses every received
# chunk completely, and 64 kB of gzip can be 64 MB.
DECOMPRESSED_PER_STEP = 64 * 1024


@dataclass
class Outcome:
    """The outcome of one request. Never an exception: the orchestrator sees only objects."""

    url: str
    status: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    # The body was longer than `http.max_body_kb` (after decompression), so `body` is only its start.
    truncated: bool = False
    elapsed_ms: int = 0
    error_kind: str | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and self.error_kind is None


class _Zlib:
    """One `Content-Encoding` (gzip or deflate), decompressed in bounded chunks."""

    def __init__(self, encoding: str) -> None:
        self._decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS)
        # deflate without a zlib header (raw) is common; httpx recognizes it by the error on the first chunk.
        self._raw_deflate_possible = encoding == "deflate"

    def decode(self, data: bytes) -> Iterator[bytes]:
        while True:
            try:
                chunk = self._decompressor.decompress(data, DECOMPRESSED_PER_STEP)
            except zlib.error as exc:
                if not self._raw_deflate_possible:
                    raise httpx.DecodingError(str(exc)) from exc
                self._raw_deflate_possible = False
                self._decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                continue
            self._raw_deflate_possible = False
            if chunk:
                yield chunk
            data = self._decompressor.unconsumed_tail
            if not data and len(chunk) < DECOMPRESSED_PER_STEP:
                return

    def flush(self) -> Iterator[bytes]:
        if rest := self._decompressor.flush():
            yield rest


class _Decoder:
    """`Content-Encoding` like httpx, but no step produces more than `DECOMPRESSED_PER_STEP`.

    An unknown encoding is skipped, as in httpx: the body stays as it arrived.
    """

    def __init__(self, encodings: Iterable[str]) -> None:
        # The encoding applied last is decompressed first.
        kinds = [e.strip().lower() for e in encodings]
        self._stages = [_Zlib(e) for e in reversed(kinds) if e in ("gzip", "deflate")]

    def decode(self, data: bytes) -> Iterator[bytes]:
        return self._through(data, 0)

    def flush(self) -> Iterator[bytes]:
        for i, stage in enumerate(self._stages):
            for chunk in stage.flush():
                yield from self._through(chunk, i + 1)

    def _through(self, data: bytes, start: int) -> Iterator[bytes]:
        if start == len(self._stages):
            if data:
                yield data
            return
        for chunk in self._stages[start].decode(data):
            yield from self._through(chunk, start + 1)


async def _read_body(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    """(body, truncated): at most `limit` decompressed bytes. The rest is not read, the connection closes."""
    decoder = _Decoder(response.headers.get_list("content-encoding", split_commas=True))
    chunks: list[bytes] = []
    received = 0

    def add(new: Iterator[bytes]) -> bool:
        nonlocal received
        for chunk in new:
            if received + len(chunk) > limit:
                chunks.append(chunk[: limit - received])
                return True
            chunks.append(chunk)
            received += len(chunk)
        return False

    async with contextlib.aclosing(response.aiter_raw()) as raw:
        async for piece in raw:
            if add(decoder.decode(piece)):
                return b"".join(chunks), True
    return b"".join(chunks), add(decoder.flush())


class DomainBudget:
    """Hard per-domain budget: a number of requests and seconds from `[http]` in sitetriage.toml.

    When it is used up, what was collected goes on, and the rest is `unknown`.
    """

    def __init__(self, max_requests: int, max_seconds: float) -> None:
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self.started = time.monotonic()
        self.requests_made = 0
        self.aborted_reason: str | None = None

    def take(self) -> bool:
        if self.aborted_reason:
            return False
        if self.requests_made >= self.max_requests:
            self.aborted_reason = f"budget of {self.max_requests} requests exhausted"
            return False
        if time.monotonic() - self.started >= self.max_seconds:
            self.aborted_reason = f"budget of {self.max_seconds:g} s exhausted"
            return False
        self.requests_made += 1
        return True

    def abort(self, reason: str) -> None:
        self.aborted_reason = self.aborted_reason or reason

    def snapshot(self) -> Budget:
        return Budget(
            max_requests=self.max_requests,
            requests_made=self.requests_made,
            elapsed_ms=int((time.monotonic() - self.started) * 1000),
            exhausted=bool(self.aborted_reason),
            aborted_reason=self.aborted_reason,
        )


def _cause_chain(exc: BaseException) -> list[BaseException]:
    """The exception and all its causes: httpx wraps the real error in two or three layers of its own."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _classify(exc: Exception) -> tuple[str, str]:
    """Network exception → (kind, detail). The kind decides whether the request is retried."""
    for link in _cause_chain(exc):
        if isinstance(link, addresses.BlockedAddress):
            return "blocked", str(link)
        if isinstance(link, NoConnection):
            return "no_connection", str(link)
        if isinstance(link, socket.gaierror):
            # Constants from `socket`, not numbers: the numbers differ between Linux and Windows.
            return DNS_ERRNO.get(link.errno, "dns"), str(link)
        if isinstance(link, ssl.SSLCertVerificationError):
            return "tls", str(link)
        if isinstance(link, ssl.SSLError):
            # An interrupted handshake is no evidence about the certificate (BUG-004): a server may
            # drop the connection with a Python client and show a browser a valid certificate. So it
            # goes through the ordinary fallback to http, without a certificate finding.
            return "tls_handshake", str(link)
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout", str(exc)
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout", str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", str(exc)
    if isinstance(exc, httpx.TooManyRedirects):
        return "too_many_redirects", str(exc)
    return "connection", f"{type(exc).__name__}: {exc}"


async def _resolve(host: str, port: int) -> list[tuple]:
    """DNS through the event loop; tests replace it with a fake, so the check does not run on a real name."""
    return await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_ADDRCONFIG
    )


class NoConnection(httpcore.ConnectError):
    """No TCP connection was established with any address: refused, unreachable or timed out.

    It is raised only in `_PublicAddresses.connect_tcp`, before TLS and before HTTP, so it alone is
    evidence that the server does not answer (ADR-013). A drop after an established connection is
    not: the server is there, it just does not answer us (BUG-004).
    """


class _PublicAddresses(httpcore.AsyncNetworkBackend):
    """A connection goes only to an address that passed the check (ADR-006).

    The check runs after DNS, where the TCP connection is opened, and the connection goes to
    exactly the checked address. That covers every redirect, and DNS rebinding does not get
    through: a name that switches to a private address between two lookups gets a connection
    only to the checked one. SNI and `Host` still carry the domain name, because httpcore takes
    them from the request, not from here.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend, allowed: addresses.Allowlist) -> None:
        self._inner = inner
        self._allowed = allowed

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            infos = await _resolve(host, port)
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        ips = list(dict.fromkeys(info[4][0] for info in infos))
        public = [ip for ip in ips if addresses.may_connect(ip, host, port, self._allowed)]
        if not public:
            raise addresses.BlockedAddress(f"address is not public: {host} → {', '.join(ips) or '—'}")
        error: Exception | None = None
        accepted = False
        for ip in public:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore.ConnectTimeout as exc:
                raise NoConnection(f"{ip}:{port} connect timeout") from exc
            except httpcore.ConnectError as exc:
                error = exc
                # A reset only arrives after an accepted connection, so even when `connect` still sees it,
                # the server is there.
                accepted = accepted or any(isinstance(e, ConnectionResetError) for e in _cause_chain(exc))
        if accepted:
            raise error  # type: ignore[misc]
        raise NoConnection(f"{', '.join(public)}:{port} {error}") from error


def public_transport(config: dict, *, verify: bool, max_connections: int) -> httpx.AsyncHTTPTransport:
    """A transport that opens only addresses that pass the check (ADR-006), with the allowlist of `config`.

    Every client that sends a request goes through it, the link probe included (BUG-05). The client must
    also have `trust_env=False`: a proxy from the environment would resolve the name itself.
    """
    transport = httpx.AsyncHTTPTransport(verify=verify, limits=httpx.Limits(max_connections=max_connections))
    # httpx 0.28 has no public parameter for the network backend. If this field is renamed,
    # the protection must not disappear silently, so the tool then refuses to run.
    pool = transport._pool
    if not hasattr(pool, "_network_backend"):
        raise RuntimeError("httpcore no longer has _network_backend; SSRF protection cannot be installed")
    pool._network_backend = _PublicAddresses(pool._network_backend, addresses.allowlist(config))
    return transport


class Fetcher:
    """Shares the semaphores and connections between all domains in a run."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._global = asyncio.Semaphore(get(config, "http.concurrency"))
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next_allowed: dict[str, float] = {}
        self._delay_range = [ms / 1000 for ms in get(config, "http.delay_ms")]
        self._client: httpx.AsyncClient | None = None
        self._insecure: httpx.AsyncClient | None = None

    # ---------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> Fetcher:
        self._client = self._make_client(verify=True)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        for client in (self._client, self._insecure):
            if client is not None:
                await client.aclose()

    def _make_client(self, *, verify: bool) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=public_transport(
                self.config, verify=verify, max_connections=get(self.config, "http.concurrency") * 2
            ),
            # No HTTP(S)_PROXY from the environment: a proxy resolves the name itself, bypassing the check.
            trust_env=False,
            follow_redirects=True,
            headers={"User-Agent": user_agent(self.config), "Accept-Encoding": ACCEPT_ENCODING},
            timeout=httpx.Timeout(
                get(self.config, "http.timeout_total_s"),
                connect=get(self.config, "http.timeout_connect_s"),
                read=get(self.config, "http.timeout_read_s"),
            ),
        )

    def _pick_client(self, *, verify: bool) -> httpx.AsyncClient:
        if verify:
            assert self._client is not None, "Fetcher used outside `async with`"
            return self._client
        if self._insecure is None:
            self._insecure = self._make_client(verify=False)
        return self._insecure

    # ----------------------------------------------------------------- requests
    async def request(
        self,
        url: str,
        budget: DomainBudget,
        *,
        verify: bool = True,
        crawl_delay: float | None = None,
        retries: int = 1,
        stop_at: str | None = None,
    ) -> Outcome:
        if not budget.take():
            return Outcome(url=url, error_kind="budget", error_detail=budget.aborted_reason)

        # The key is the host without a leading `www.`: `www.x.rs` and `x.rs` are the same server and share
        # the queue and the delay (ADR-014).
        host = (host_of(url) or url).removeprefix("www.")
        lock = self._host_locks.setdefault(host, asyncio.Lock())

        # The delay is awaited under the host lock but outside the global semaphore, so that sleeping
        # does not hold a slot another domain could use.
        async with lock:
            await self._wait_turn(host, crawl_delay)
            async with self._global:
                # Only the server's work is measured. Waiting in the queue and the politeness delay are
                # our time; with them the "home page answers in > 1500 ms" escalation fires for everyone.
                started = time.monotonic()
                outcome = await self._send(url, verify=verify, stop_at=stop_at)
                outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._host_next_allowed[host] = time.monotonic() + random.uniform(*self._delay_range)

        if outcome.status in GIVE_UP_STATUSES:
            budget.abort(f"server returned {outcome.status}, giving up on the domain for this run")
            return outcome
        if retries > 0 and _should_retry(outcome):
            await asyncio.sleep(random.uniform(0.5, 1.5))
            return await self.request(
                url, budget, verify=verify, crawl_delay=crawl_delay, retries=retries - 1, stop_at=stop_at
            )
        return outcome

    async def _wait_turn(self, host: str, crawl_delay: float | None) -> None:
        earliest = self._host_next_allowed.get(host, 0.0)
        if crawl_delay:
            max_delay = get(self.config, "http.max_crawl_delay_s")
            earliest = max(earliest, self._host_next_allowed.get(host, 0.0) + min(crawl_delay, max_delay))
        wait = earliest - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _send(self, url: str, *, verify: bool, stop_at: str | None = None) -> Outcome:
        """`stop_at`: a URL that was already downloaded. A redirect to it is not followed, and the
        outcome is the response that points to it, without a body (ADR-014).

        The whole request, with redirects and body, has the deadline `http.timeout_total_s`: a body
        that trickles in byte by byte never trips the read timeout, and would hold the domain's slot
        until the end of the run.
        """
        client = self._pick_client(verify=verify)
        deadline = get(self.config, "http.timeout_total_s")
        try:
            async with asyncio.timeout(deadline):
                return await self._download(client, url, stop_at)
        except TimeoutError:
            detail = f"request longer than {deadline:g} s (http.timeout_total_s)"
            return Outcome(url=url, error_kind="timeout", error_detail=detail)
        except Exception as exc:  # noqa: BLE001 — an exception never leaves the domain
            kind, detail = _classify(exc)
            return Outcome(url=url, error_kind=kind, error_detail=detail)

    async def _download(self, client: httpx.AsyncClient, url: str, stop_at: str | None) -> Outcome:
        """Redirects are followed by hand: httpx would read and decompress the body of every hop in full.

        The body of the final response is read up to `http.max_body_kb` decompressed bytes, and the
        body of a hop that redirects is not read at all.
        """
        limit = get(self.config, "http.max_body_kb") * 1024
        request = client.build_request("GET", url)
        chain: list[str] = []
        while True:
            response = await client.send(request, stream=True, follow_redirects=False)
            try:
                chain.append(str(response.url))
                if response.next_request is None:
                    body, truncated = await _read_body(response, limit)
                    return Outcome(
                        url=url,
                        status=response.status_code,
                        final_url=str(response.url),
                        redirect_chain=chain,
                        headers=dict(response.headers),
                        body=body,
                        truncated=truncated,
                    )
                next_url = str(response.next_request.url)
                if stop_at is not None and normalize(next_url) == normalize(stop_at):
                    chain.append(next_url)
                    status = response.status_code
                    return Outcome(url=url, status=status, final_url=next_url, redirect_chain=chain)
                if len(chain) > client.max_redirects:
                    raise httpx.TooManyRedirects("Exceeded maximum allowed redirects.")
                request = response.next_request
            finally:
                await response.aclose()


async def measure_link(config: dict) -> float | None:
    """The real link speed in Mb/s, measured before level 2 (ADR-018), or `None` when the measurement fails.

    At most `probe_max_s` seconds are downloaded, so a slow link is measured, not waited for. The time
    includes setting up the connection, so the number is a little lower than the real one: the error
    errs on the side of caution.
    """
    url, max_s = get(config, "network_profile.probe_url"), get(config, "network_profile.probe_max_s")
    received, started = 0, time.monotonic()
    try:
        async with asyncio.timeout(max_s), httpx.AsyncClient(
            # The same address check and allowlist as level 1, and no proxy from the environment (ADR-006).
            transport=public_transport(config, verify=True, max_connections=1),
            trust_env=False,
            headers={"User-Agent": user_agent(config)},
            timeout=None,
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_raw():
                received += len(chunk)
    except TimeoutError:
        pass  # the deadline passed mid-download: what arrived is measured
    except Exception as exc:  # noqa: BLE001 — without a measurement the load time is `unknown`, the run goes on
        kind, detail = _classify(exc)
        log.warning("real link not measured (%s): %s: %s", url, kind, detail)
        return None
    if not received:
        log.warning("real link not measured (%s): no byte arrived in %g s", url, max_s)
        return None
    return round(received * 8 / (time.monotonic() - started) / 1_000_000, 1)


def _should_retry(outcome: Outcome) -> bool:
    """4xx is an answer, not an error, so it is not retried. A temporary DNS error (EAI_AGAIN) is
    retried, a name that does not exist is not."""
    retried = {"no_connection", "connect_timeout", "read_timeout", "timeout", "connection", "dns_temporary"}
    if outcome.error_kind in retried:
        return True
    return outcome.status is not None and 500 <= outcome.status < 600


# --------------------------------------------------------------------------- #
# A run over one domain
# --------------------------------------------------------------------------- #
async def fetch_site(fetcher: Fetcher, target: DomainInput) -> SiteSnapshot:
    """Assembles the `SiteSnapshot`. An exception never leaves this function."""
    cfg = fetcher.config
    domain = target.domain
    budget = DomainBudget(
        get(cfg, "http.max_requests_per_domain"), get(cfg, "http.max_seconds_per_domain")
    )
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = SiteSnapshot(
        domain=domain,
        industry=target.industry,
        fetched_at=fetched_at,
        scanner_version=__version__,
        entry_attempts=[fetched_at],
    )
    problem = addresses.input_problem(domain, addresses.allowlist(cfg))
    if problem:
        # Not a single request: an IP address, a port or a user name bypass the name that is checked.
        url = entry_candidates(domain)[0]
        snapshot.entry = Entry(requested_url=url, error_kind="blocked", error_detail=problem)
        snapshot.budget = budget.snapshot()
        return snapshot

    entry_outcome, tls_error = await _fetch_entry(fetcher, domain, budget, snapshot)
    snapshot.entry = _entry_from(entry_outcome, tls_error)
    verify = tls_error is None
    # A site that accepts a connection on neither https nor http gets neither robots.txt nor a sitemap.
    if entry_outcome.error_kind in DNS | {"blocked"} or snapshot.entry_unreachable():
        snapshot.budget = budget.snapshot()
        return snapshot

    home = _home(entry_outcome)
    if (target_url := page_builder.redirect_stub(home)) and entry_outcome.status == 200:
        followed = await fetcher.request(target_url, budget, verify=verify)
        if followed.ok and followed.status == 200:
            # A page that only redirects with a script or meta refresh is a hop, like an HTTP
            # redirect: the page it leads to is scored (BUG-022).
            entry_outcome = replace(
                followed,
                url=entry_outcome.url,
                redirect_chain=entry_outcome.redirect_chain + followed.redirect_chain,
                elapsed_ms=entry_outcome.elapsed_ms + followed.elapsed_ms,
            )
            snapshot.entry = _entry_from(entry_outcome, tls_error)
            home = _home(entry_outcome)
    snapshot.pages.append(home)
    base_url = home.final_url or home.url
    # All further URLs use the *final* origin: if the domain redirected to www
    # or to https, robots and the sitemap live there, not at the requested URL.
    origin = _origin_of(base_url)

    rules = await _fetch_robots(fetcher, origin, budget, snapshot, verify=verify)
    crawl_delay = rules.crawl_delay
    # Before the sitemap: three requests for two findings, and a large sitemap can eat the whole budget.
    snapshot.host_variants = await _fetch_variants(fetcher, home, budget, crawl_delay)
    candidates = await _collect_sitemap(
        fetcher, origin, budget, snapshot, rules, verify=verify, crawl_delay=crawl_delay
    )
    links = page_builder.internal_links(home.raw_html, base_url)
    snapshot.home_links = links[: page_builder.LINKS_KEPT]
    snapshot.sample_source = "sitemap" if candidates else "links" if links else "none"

    # A tool that reports a missing robots.txt but ignores it when it exists
    # is inconsistent in a way people notice.
    def allowed(urls: list[str]) -> list[str]:
        return [url for url in urls if robots_parser.allows(rules, url)]

    size = get(cfg, "sitemap.sample_size")
    sample = sitemap_parser.sample(base_url, allowed(candidates), size)
    if len(sample) < size:
        # The sitemap lists too few URLs: the sample is topped up with links from the home page (ADR-015).
        top_up = [url for url in allowed(links) if url not in sample]
        sample += sitemap_parser.sample(base_url, top_up, size - len(sample) + 1)[1:]

    # The probes go before the sample: two requests for a `high` finding. After the sample a large
    # sitemap (a Yoast index with 9 sitemaps) leaves them without budget (BUG-001).
    # They go to the origin, not the home page path: `/index.php/<token>` on PHP returns 200
    # through PATH_INFO and gives a false `infra.soft404`.
    await _probe_soft404(
        fetcher, domain, origin, budget, snapshot, verify=verify, crawl_delay=crawl_delay
    )
    await _fetch_sample(fetcher, sample[1:], budget, snapshot, verify=verify, crawl_delay=crawl_delay)

    snapshot.budget = budget.snapshot()
    return snapshot


def _home(outcome: Outcome) -> PageSnapshot:
    return page_builder.build(
        outcome.url,
        final_url=outcome.final_url,
        status=outcome.status,
        headers=outcome.headers,
        body=outcome.body,
        elapsed_ms=outcome.elapsed_ms,
        redirect_hops=max(len(outcome.redirect_chain) - 1, 0),
        keep_raw_html=True,
        truncated=outcome.truncated,
    )


def _origin_of(url: str) -> str:
    parts = httpx.URL(url)
    return f"{parts.scheme}://{parts.netloc.decode()}"


def entry_candidates(domain: str) -> list[str]:
    """The URLs tried for the entry request, in order.

    The domain may also be a full origin (`http://localhost:8123`), useful for staging
    with a port, and the only way to test the fetcher against a local server. A port and a
    private address need explicit permission in `[net] allowed_private` (ADR-006).
    """
    if "://" in domain:
        return [domain if domain.endswith("/") else f"{domain}/"]
    return [f"https://{domain}/", f"http://{domain}/"]


async def _fetch_entry(
    fetcher: Fetcher, domain: str, budget: DomainBudget, snapshot: SiteSnapshot
) -> tuple[Outcome, str | None]:
    """https, then http; an invalid certificate is a finding, not a reason to drop the domain.

    Also returns the TLS error (`None` = the certificate passed): the retry without verification
    succeeds without an error, so the reason would otherwise vanish from the evidence.
    """
    candidates = entry_candidates(domain)
    outcome = await fetcher.request(candidates[0], budget)

    if outcome.error_kind == "tls":
        # An expired certificate is a valuable finding for a sale and the worst possible reason
        # for the whole domain to drop out of the report, so the fetch is retried without verification.
        snapshot.errors.append(SnapshotError("entry", "tls", outcome.error_detail or ""))
        retry = await fetcher.request(candidates[0], budget, verify=False)
        return (retry if retry.ok else outcome), outcome.error_detail or "unknown TLS error"

    if not outcome.ok and outcome.error_kind not in DNS | {"budget", "blocked"} and len(candidates) > 1:
        snapshot.errors.append(SnapshotError("entry", outcome.error_kind or "?", outcome.error_detail or ""))
        fallback = await fetcher.request(candidates[1], budget)
        if fallback.ok:
            return fallback, None
        # The http error too, because "unreachable" requires that neither https nor http got a
        # connection (ADR-013).
        error = SnapshotError("entry", fallback.error_kind or "?", fallback.error_detail or "")
        snapshot.errors.append(error)
    return outcome, None


def _entry_from(outcome: Outcome, tls_error: str | None) -> Entry:
    return Entry(
        requested_url=outcome.url,
        final_url=outcome.final_url,
        redirect_chain=outcome.redirect_chain,
        status=outcome.status,
        elapsed_ms=outcome.elapsed_ms,
        tls=Tls(valid=tls_error is None, error=tls_error),
        error_kind=outcome.error_kind,
        error_detail=outcome.error_detail,
    )


async def _fetch_robots(
    fetcher: Fetcher, origin: str, budget: DomainBudget, snapshot: SiteSnapshot, *, verify: bool
) -> robots_parser.RobotsRules:
    outcome = await fetcher.request(f"{origin}/robots.txt", budget, verify=verify, retries=0)
    body = outcome.body.decode("utf-8", errors="replace") if outcome.ok and outcome.body else None
    rules = robots_parser.parse(body if outcome.status == 200 else None)
    snapshot.robots = RobotsInfo(
        status=outcome.status,
        body=body if outcome.status == 200 else None,
        disallow=list(rules.disallow),
        allow=list(rules.allow),
        crawl_delay=rules.crawl_delay,
        sitemaps=list(rules.sitemaps),
        error=outcome.error_detail,
    )
    if outcome.error_kind:
        snapshot.errors.append(SnapshotError("robots", outcome.error_kind, outcome.error_detail or ""))
    return rules


def variant_urls(final_url: str) -> list[str]:
    """The other three URLs of the final origin: http/https × www/without www (ADR-014).

    An entry with a port or an IP address has none: there neither `www` nor the other scheme gives the
    same site.
    """
    url = httpx.URL(final_url)
    if url.port is not None or not url.host or addresses.is_ip(url.host):
        return []
    bare = url.host.removeprefix("www.")
    every = [f"{scheme}://{host}/" for scheme in ("https", "http") for host in (bare, f"www.{bare}")]
    return [variant for variant in every if variant != f"{url.scheme}://{url.host}/"]


async def _fetch_variants(
    fetcher: Fetcher, home: PageSnapshot, budget: DomainBudget, crawl_delay: float | None
) -> list[HostVariant] | None:
    """With certificate verification and without a retry: a variant's TLS error is data about it.

    A variant that redirects to the home page gets its status and canonical, and the home page is not
    requested again: on slow hosting that cost 3 × several seconds of budget (run D on list A).
    """
    final_url = home.final_url or home.url
    urls = variant_urls(final_url)
    if not urls:
        return None
    variants = []
    for url in urls:
        outcome = await fetcher.request(url, budget, crawl_delay=crawl_delay, retries=0, stop_at=final_url)
        status, canonical = outcome.status, None
        if outcome.final_url and normalize(outcome.final_url) == normalize(final_url):
            status, canonical = home.status, home.canonical_normalized
        elif outcome.status == 200 and outcome.body:
            variant_page = page_builder.build(
                url, final_url=outcome.final_url, status=200, headers=outcome.headers, body=outcome.body
            )
            canonical = variant_page.canonical_normalized
        variants.append(
            HostVariant(
                url=url,
                status=status,
                final_url=outcome.final_url,
                redirect_chain=outcome.redirect_chain,
                canonical=canonical,
                error_kind=outcome.error_kind,
                error_detail=outcome.error_detail,
            )
        )
    return variants


async def _collect_sitemap(
    fetcher: Fetcher,
    origin: str,
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    rules: robots_parser.RobotsRules,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> list[str]:
    """Recursion through `sitemapindex`, within the `[sitemap]` limits."""
    cfg = fetcher.config
    max_depth = get(cfg, "sitemap.max_depth")
    max_files = get(cfg, "sitemap.max_files")
    max_urls = get(cfg, "sitemap.max_urls")
    max_bytes = get(cfg, "sitemap.max_kb") * 1024

    # A `Sitemap:` from robots.txt wins over guessing. When robots.txt also lists sitemaps of
    # other domains (one robots.txt for a whole chain of sites), they would use up `max_files` before
    # this site's nested sitemaps (BUG-027). A foreign sitemap is read only when it is the only one
    # listed (a sitemap on a CDN).
    own = [url for url in rules.sitemaps if same_site(url, origin)]
    start = own or list(rules.sitemaps) or [f"{origin}/sitemap.xml"]
    info = SitemapInfo(url=start[0])
    queue: list[tuple[str, int]] = [(url, 0) for url in start]
    seen: set[str] = set()
    collected: list[str] = []
    files_read = 0

    while queue and files_read < max_files and len(collected) < max_urls:
        url, depth = queue.pop(0)
        canonical = normalize(url)
        if not canonical or canonical in seen or depth > max_depth:
            continue
        seen.add(canonical)

        outcome = await fetcher.request(
            canonical, budget, verify=verify, crawl_delay=crawl_delay, retries=0
        )
        if info.status is None or canonical == normalize(start[0]):
            info.status = outcome.status
        if outcome.error_kind == "budget":
            break
        files_read += 1
        if not outcome.ok or outcome.status != 200:
            continue

        # A truncated body is part of a sitemap: what follows the limit is unknown, as for a too large one.
        if outcome.truncated:
            kind, locations = "too_large", []
        else:
            kind, locations = sitemap_parser.parse(outcome.body, max_bytes=max_bytes)
        info.depth_reached = max(info.depth_reached, depth)
        if kind == "too_large":
            # The sitemap exists but was not read: that is not "no sitemap", and the URL list is incomplete.
            info.truncated = True
            info.error = f"{canonical}: larger than the limit (sitemap.max_kb, http.max_body_kb)"
        elif kind == "index":
            info.nested_count += len(locations)
            queue.extend((loc, depth + 1) for loc in locations)
        elif kind == "urlset":
            room = max_urls - len(collected)
            collected.extend(locations[:room])
            if len(locations) > room:
                info.truncated = True

    info.urls = collected
    snapshot.sitemap = info
    return collected


async def _fetch_sample(
    fetcher: Fetcher,
    urls: Sequence[str],
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> None:
    for url in urls:
        outcome = await fetcher.request(url, budget, verify=verify, crawl_delay=crawl_delay)
        if outcome.error_kind == "budget":
            break
        snapshot.pages.append(
            page_builder.build(
                url,
                final_url=outcome.final_url,
                status=outcome.status,
                headers=outcome.headers,
                body=outcome.body,
                elapsed_ms=outcome.elapsed_ms,
                redirect_hops=max(len(outcome.redirect_chain) - 1, 0),
                truncated=outcome.truncated,
            )
        )


def probe_urls(domain: str, origin: str) -> list[str]:
    """Deterministic soft-404 probes, `sha1(domain)[:16]`, so tests are repeatable."""
    token = hashlib.sha1(domain.encode()).hexdigest()[:16]
    base = origin.rstrip("/")
    return [f"{base}/{token}{suffix}" for suffix in PROBE_SUFFIXES]


async def _probe_soft404(
    fetcher: Fetcher,
    domain: str,
    origin: str,
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> None:
    probes: list[Soft404Probe] = []
    for url in probe_urls(domain, origin):
        outcome = await fetcher.request(
            url, budget, verify=verify, crawl_delay=crawl_delay, retries=0
        )
        if outcome.error_kind == "budget":
            break
        sample = ""
        if outcome.ok and outcome.body:
            sample = page_builder.build(
                url, final_url=outcome.final_url, status=outcome.status, body=outcome.body
            ).text_sample
        probes.append(
            Soft404Probe(
                url=url,
                status=outcome.status,
                final_url=outcome.final_url,
                text_sample=sample,
                error=outcome.error_detail,
            )
        )
    snapshot.soft404 = Soft404(probes=probes)


# --------------------------------------------------------------------------- #
# A run over the domain list
# --------------------------------------------------------------------------- #
async def scan_domains(
    targets: Iterable[DomainInput],
    config: dict,
    snapshot_dir: Path | None = None,
    on_done: Callable[[SiteSnapshot], None] | None = None,
) -> list[SiteSnapshot]:
    """A snapshot goes to disk as soon as its domain is done: if the process dies on the 190th, you have 189.

    `on_done` is called for every finished domain, after the write to disk. A domain that looks
    unreachable after the first attempt goes to the end of the queue and gets a second attempt, with
    a new budget, no earlier than `http.second_attempt_after_s` after the first (ADR-013).
    """
    targets = list(targets)
    results: list[SiteSnapshot] = []
    # The time budget is for work on the domain, not for waiting in the queue behind the other 199:
    # `DomainBudget` is created in `fetch_site`, so a domain enters it only when its turn comes.
    in_flight = asyncio.Semaphore(get(config, "http.domain_concurrency"))
    second_after = get(config, "http.second_attempt_after_s")

    async with Fetcher(config) as fetcher:

        async def attempt(target: DomainInput) -> SiteSnapshot:
            async with in_flight:
                log.info("level 1 starts", extra={"domain": target.domain})
                try:
                    return await fetch_site(fetcher, target)
                except Exception as exc:  # noqa: BLE001 — domain boundary
                    log.error("level 1 crashed: %s", exc, extra={"domain": target.domain})
                    return SiteSnapshot(
                        domain=target.domain,
                        industry=target.industry,
                        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        errors=[SnapshotError("fetch", type(exc).__name__, str(exc))],
                    )

        async def one(target: DomainInput) -> SiteSnapshot:
            snapshot = await attempt(target)
            if cause := snapshot.entry_unreachable():
                domain = {"domain": target.domain}
                log.info("unreachable (%s); second attempt in %g s", cause, second_after, extra=domain)
                # Waits outside the semaphore: meanwhile another domain gets the slot.
                await asyncio.sleep(second_after)
                first = snapshot.entry_attempts
                snapshot = await attempt(target)
                snapshot.entry_attempts = first + snapshot.entry_attempts
            if snapshot_dir is not None:
                store.write_site(snapshot_dir, snapshot)
            log.info(
                "level 1 done: %d pages, %d requests",
                len(snapshot.pages),
                snapshot.budget.requests_made,
                extra={"domain": target.domain},
            )
            if on_done is not None:
                on_done(snapshot)
            return snapshot

        # A bare `gather` would let one exception bring down the whole run.
        gathered = await asyncio.gather(*(one(t) for t in targets), return_exceptions=True)

    for target, item in zip(targets, gathered, strict=True):
        if isinstance(item, BaseException):
            log.error("domain lost: %r", item, extra={"domain": target.domain})
            results.append(SiteSnapshot(domain=target.domain, industry=target.industry))
        else:
            results.append(item)
    return results
