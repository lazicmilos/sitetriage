"""Nivo 1: dohvatanje i sklapanje `SiteSnapshot` (§4, §8).

Jedini sloj nivoa 1 koji dodiruje mrežu. Provere odavde ne uvoze ništa — dobijaju
gotov snapshot (§2.1).

Dva semafora (§8.1): globalni ograničava tebe, po-hostu štiti njih. Po-hostu je
uvek 1 i to je granica između alata i napada.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import socket
import ssl
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpcore
import httpx

from skener import __version__, addresses, store
from skener.config import get, user_agent
from skener.fetch import page as page_builder
from skener.fetch import robots as robots_parser
from skener.fetch import sitemap as sitemap_parser
from skener.fetch.urls import host_of, normalize
from skener.models import (
    Budget,
    DomainInput,
    Entry,
    HostVariant,
    RobotsInfo,
    SitemapInfo,
    SiteSnapshot,
    SnapshotError,
    Soft404,
    Soft404Probe,
    Tls,
)

log = logging.getLogger("skener.fetch")

# Statusi na koje se odustaje od domena za ovaj prolaz (§8.3) — ne pokušava se ponovo.
ODUSTANI_STATUSI = {429, 503}
PROBE_SUFFIXES = ("", ".html")
# DNS greška je greška imena, pa ni http na istom imenu ne pomaže.
DNS = frozenset({"dns", "dns_nxdomain", "dns_nodata", "dns_temporary"})
# `dns_nodata`: ime postoji, ali nema adresu. Na Windows-u je EAI_NODATA isto što i EAI_NONAME,
# pa ide prvi i tamo ga NONAME prepiše; oba znače da sajt ne radi.
DNS_ERRNO = {
    socket.EAI_NODATA: "dns_nodata",
    socket.EAI_NONAME: "dns_nxdomain",
    socket.EAI_AGAIN: "dns_temporary",
}


@dataclass
class Outcome:
    """Ishod jednog zahteva. Nikad izuzetak — orkestrator vidi samo objekte (§8.2)."""

    url: str
    status: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    elapsed_ms: int = 0
    error_kind: str | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and self.error_kind is None


class DomainBudget:
    """Tvrd budžet po domenu (§4.2): broj zahteva i sekundi iz `[http]` u skener.toml.

    Kad se potroši, ono što je prikupljeno ide dalje, ostalo je `unknown`.
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
            self.aborted_reason = f"potrošen budžet od {self.max_requests} zahteva"
            return False
        if time.monotonic() - self.started >= self.max_seconds:
            self.aborted_reason = f"potrošen budžet od {self.max_seconds:g} s"
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


def _lanac(exc: BaseException) -> list[BaseException]:
    """Izuzetak i svi njegovi uzroci: httpx umota pravu grešku u dva-tri svoja sloja."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _classify(exc: Exception) -> tuple[str, str]:
    """Mrežni izuzetak → (vrsta, detalj). Vrsta odlučuje da li se ponavlja (§4.6)."""
    for link in _lanac(exc):
        if isinstance(link, addresses.BlockedAddress):
            return "blocked", str(link)
        if isinstance(link, NoConnection):
            return "no_connection", str(link)
        if isinstance(link, socket.gaierror):
            # Konstante iz `socket`, ne brojevi: brojevi se razlikuju između Linux-a i Windows-a.
            return DNS_ERRNO.get(link.errno, "dns"), str(link)
        if isinstance(link, ssl.SSLCertVerificationError):
            return "tls", str(link)
        if isinstance(link, ssl.SSLError):
            # Prekinuto rukovanje nije dokaz o sertifikatu (BUG-004): server ume da prekine
            # vezu sa Python klijentom, a browseru pokaže ispravan sertifikat. Zato ide
            # kroz običan pad na http, bez nalaza o sertifikatu.
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


async def _razresi(host: str, port: int) -> list[tuple]:
    """DNS kroz petlju; testovi ga zamenjuju lažnim, da proveru ne rade nad pravim imenom."""
    return await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_ADDRCONFIG
    )


class NoConnection(httpcore.ConnectError):
    """TCP veza nije uspostavljena ni sa jednom adresom: odbijena, nedostupna ili istekla.

    Nastaje samo u `_JavneAdrese.connect_tcp`, pre TLS-a i pre HTTP-a, pa je jedino ona dokaz da
    server ne odgovara (Z-20). Prekid posle uspostavljene veze to nije: server je tu, samo ne
    odgovara nama (BUG-004).
    """


class _JavneAdrese(httpcore.AsyncNetworkBackend):
    """Veza ide samo na adresu koja je prošla proveru (ADR-006).

    Provera je posle DNS-a, na mestu gde se otvara TCP veza, i veza ide baš na proverenu
    adresu. Tako je pokriveno svako preusmerenje, a DNS rebinding ne prolazi: ime koje se
    između dva upita prebaci na privatnu adresu dobija vezu samo na onu proverenu. SNI i
    `Host` i dalje nose ime domena, jer ih httpcore uzima iz zahteva, ne odavde.
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
            infos = await _razresi(host, port)
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        ips = list(dict.fromkeys(info[4][0] for info in infos))
        javne = [ip for ip in ips if addresses.may_connect(ip, host, port, self._allowed)]
        if not javne:
            raise addresses.BlockedAddress(f"adresa nije javna: {host} → {', '.join(ips) or '—'}")
        greska: Exception | None = None
        prihvacena = False
        for ip in javne:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore.ConnectTimeout as exc:
                raise NoConnection(f"{ip}:{port} connect timeout") from exc
            except httpcore.ConnectError as exc:
                greska = exc
                # Reset stiže tek posle prihvaćene veze, pa i kad ga vidi još `connect`, server je tu.
                prihvacena = prihvacena or any(isinstance(e, ConnectionResetError) for e in _lanac(exc))
        if prihvacena:
            raise greska  # type: ignore[misc]
        raise NoConnection(f"{', '.join(javne)}:{port} {greska}") from greska


class Fetcher:
    """Deli semafore i konekcije između svih domena u prolazu."""

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
        transport = httpx.AsyncHTTPTransport(
            verify=verify, limits=httpx.Limits(max_connections=get(self.config, "http.concurrency") * 2)
        )
        # httpx 0.28 nema javni parametar za mrežni backend. Ako se to polje preimenuje,
        # zaštita ne sme tiho da nestane, pa alat tada odbija da radi.
        pool = transport._pool
        if not hasattr(pool, "_network_backend"):
            raise RuntimeError("httpcore više nema _network_backend; SSRF zaštita ne može da se postavi")
        pool._network_backend = _JavneAdrese(pool._network_backend, addresses.allowlist(self.config))
        return httpx.AsyncClient(
            transport=transport,
            # Bez HTTP(S)_PROXY iz okruženja: proxy sam razrešava ime, pa bi zaobišao proveru.
            trust_env=False,
            follow_redirects=True,
            headers={"User-Agent": user_agent(self.config)},
            timeout=httpx.Timeout(
                get(self.config, "http.timeout_total_s"),
                connect=get(self.config, "http.timeout_connect_s"),
                read=get(self.config, "http.timeout_read_s"),
            ),
        )

    def _pick_client(self, *, verify: bool) -> httpx.AsyncClient:
        if verify:
            assert self._client is not None, "Fetcher se koristi van `async with`"
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
    ) -> Outcome:
        if not budget.take():
            return Outcome(url=url, error_kind="budget", error_detail=budget.aborted_reason)

        # Ključ je host bez vodećeg `www.`: `www.x.rs` i `x.rs` su isti server i dele red i pauzu (Z-26).
        host = (host_of(url) or url).removeprefix("www.")
        lock = self._host_locks.setdefault(host, asyncio.Lock())

        # Pauza se čeka pod ključem hosta ali van globalnog semafora, da spavanje
        # ne drži slot koji drugi domen može da koristi.
        async with lock:
            await self._wait_turn(host, crawl_delay)
            async with self._global:
                # Meri se samo rad servera. Čekanje u redu i pauza pristojnosti su naše
                # vreme — sa njima „početna odgovara > 1500 ms" pali svakome (§6).
                started = time.monotonic()
                outcome = await self._send(url, verify=verify)
                outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._host_next_allowed[host] = time.monotonic() + random.uniform(*self._delay_range)

        if outcome.status in ODUSTANI_STATUSI:
            budget.abort(f"server vratio {outcome.status}, odustajem od domena za ovaj prolaz")
            return outcome
        if retries > 0 and _should_retry(outcome):
            await asyncio.sleep(random.uniform(0.5, 1.5))
            return await self.request(
                url, budget, verify=verify, crawl_delay=crawl_delay, retries=retries - 1
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

    async def _send(self, url: str, *, verify: bool) -> Outcome:
        client = self._pick_client(verify=verify)
        try:
            response = await client.get(url)
        except Exception as exc:  # noqa: BLE001 — izuzetak nikad ne napušta domen (§8.2)
            kind, detail = _classify(exc)
            return Outcome(url=url, error_kind=kind, error_detail=detail)

        chain = [str(r.request.url) for r in response.history] + [str(response.url)]
        return Outcome(
            url=url,
            status=response.status_code,
            final_url=str(response.url),
            redirect_chain=chain,
            headers=dict(response.headers),
            body=response.content,
        )


def _should_retry(outcome: Outcome) -> bool:
    """4xx je odgovor, ne greška — bez ponovnog pokušaja (§4.6)."""
    if outcome.error_kind in {"no_connection", "connect_timeout", "read_timeout", "timeout", "connection"}:
        return True
    return outcome.status is not None and 500 <= outcome.status < 600


# --------------------------------------------------------------------------- #
# Prolaz nad jednim domenom
# --------------------------------------------------------------------------- #
async def fetch_site(fetcher: Fetcher, target: DomainInput) -> SiteSnapshot:
    """Sklapa `SiteSnapshot`. Izuzetak nikad ne napušta ovu funkciju (§8.2)."""
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
        # Nijedan zahtev: IP adresa, port ili korisničko ime zaobilaze ime koje se proverava.
        url = entry_candidates(domain)[0]
        snapshot.entry = Entry(requested_url=url, error_kind="blocked", error_detail=problem)
        snapshot.budget = budget.snapshot()
        return snapshot

    entry_outcome, tls_error = await _fetch_entry(fetcher, domain, budget, snapshot)
    snapshot.entry = _entry_from(entry_outcome, tls_error)
    verify = tls_error is None
    # Sajt koji ne prihvata vezu ni na https ni na http ne dobija ni robots.txt ni mapu sajta.
    if entry_outcome.error_kind in DNS | {"blocked"} or snapshot.entry_unreachable():
        snapshot.budget = budget.snapshot()
        return snapshot

    home = page_builder.build(
        entry_outcome.url,
        final_url=entry_outcome.final_url,
        status=entry_outcome.status,
        headers=entry_outcome.headers,
        body=entry_outcome.body,
        elapsed_ms=entry_outcome.elapsed_ms,
        redirect_hops=max(len(entry_outcome.redirect_chain) - 1, 0),
        keep_raw_html=True,
    )
    snapshot.pages.append(home)
    base_url = home.final_url or home.url
    # Sve dalje adrese idu sa *konačnog* porekla: ako je domen preusmerio na www
    # ili na https, robots i sitemap žive tamo, ne na traženoj adresi.
    origin = _origin_of(base_url)

    rules = await _fetch_robots(fetcher, origin, budget, snapshot, verify=verify)
    crawl_delay = rules.crawl_delay
    # Pre mape sajta: tri zahteva za dva nalaza, a velika mapa ume da pojede ceo budžet.
    snapshot.host_variants = await _fetch_variants(fetcher, base_url, budget, crawl_delay)
    candidates = await _collect_sitemap(
        fetcher, origin, budget, snapshot, rules, verify=verify, crawl_delay=crawl_delay
    )
    links = page_builder.internal_links(home.raw_html, base_url)
    snapshot.home_links = links[: page_builder.LINKS_KEPT]
    snapshot.sample_source = "sitemap" if candidates else "links" if links else "none"

    # Alat koji prijavljuje da robots.txt nedostaje, a ignoriše ga kad postoji,
    # je nekonzistentan na način koji se primeti (§4.3).
    def allowed(urls: list[str]) -> list[str]:
        return [url for url in urls if robots_parser.allows(rules, url)]

    size = get(cfg, "sitemap.sample_size")
    sample = sitemap_parser.sample(base_url, allowed(candidates), size)
    if len(sample) < size:
        # Mapa sajta ne navodi dovoljno adresa: uzorak se dopunjava vezama sa početne (Z-21).
        dopuna = [url for url in allowed(links) if url not in sample]
        sample += sitemap_parser.sample(base_url, dopuna, size - len(sample) + 1)[1:]

    # Sonde idu pre uzorka: dva zahteva za `high` nalaz. Posle uzorka ih velika mapa
    # sajta (Yoast indeks sa 9 mapa) ostavi bez budžeta.
    # Idu na poreklo, ne na putanju početne: `/index.php/<token>` na PHP-u vraća 200
    # preko PATH_INFO-a i daje lažni `infra.soft404` (§5.2).
    await _probe_soft404(
        fetcher, domain, origin, budget, snapshot, verify=verify, crawl_delay=crawl_delay
    )
    await _fetch_sample(fetcher, sample[1:], budget, snapshot, verify=verify, crawl_delay=crawl_delay)

    snapshot.budget = budget.snapshot()
    return snapshot


def _origin_of(url: str) -> str:
    parts = httpx.URL(url)
    return f"{parts.scheme}://{parts.netloc.decode()}"


def entry_candidates(domain: str) -> list[str]:
    """Adrese kojima se pokušava ulaz, redom.

    Domen sme da bude i pun origin (`http://localhost:8123`) — korisno za staging
    sa portom, i jedini način da se fetcher testira protiv lokalnog servera. Port i
    privatna adresa traže izričitu dozvolu u `[net] allowed_private` (ADR-006).
    """
    if "://" in domain:
        return [domain if domain.endswith("/") else f"{domain}/"]
    return [f"https://{domain}/", f"http://{domain}/"]


async def _fetch_entry(
    fetcher: Fetcher, domain: str, budget: DomainBudget, snapshot: SiteSnapshot
) -> tuple[Outcome, str | None]:
    """https pa http; nevalidan sertifikat je nalaz, ne razlog da domen ispadne (§4.6).

    Vraća i TLS grešku (`None` = sertifikat prošao): ponovni dohvat bez provere
    uspe bez greške, pa bi razlog iz dokaza inače nestao.
    """
    candidates = entry_candidates(domain)
    outcome = await fetcher.request(candidates[0], budget)

    if outcome.error_kind == "tls":
        # Istekao sertifikat je vredan nalaz za prodaju i najgori mogući razlog
        # da ti ceo domen ispadne iz izveštaja — zato se dohvat ponavlja bez provere.
        snapshot.errors.append(SnapshotError("entry", "tls", outcome.error_detail or ""))
        retry = await fetcher.request(candidates[0], budget, verify=False)
        return (retry if retry.ok else outcome), outcome.error_detail or "nepoznata TLS greška"

    if not outcome.ok and outcome.error_kind not in DNS | {"budget", "blocked"} and len(candidates) > 1:
        snapshot.errors.append(SnapshotError("entry", outcome.error_kind or "?", outcome.error_detail or ""))
        fallback = await fetcher.request(candidates[1], budget)
        if fallback.ok:
            return fallback, None
        # I greška http-a, jer „ne radi" traži da ni https ni http nisu dobili vezu (Z-20).
        greska = SnapshotError("entry", fallback.error_kind or "?", fallback.error_detail or "")
        snapshot.errors.append(greska)
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
    """Preostale tri adrese konačnog porekla: http/https × www/bez www (Z-26).

    Ulaz sa portom ili IP adresom ih nema: tamo ni `www` ni druga šema ne daju isti sajt.
    """
    url = httpx.URL(final_url)
    if url.port is not None or not url.host or addresses.is_ip(url.host):
        return []
    bez = url.host.removeprefix("www.")
    sve = [f"{sema}://{host}/" for sema in ("https", "http") for host in (bez, f"www.{bez}")]
    return [adresa for adresa in sve if adresa != f"{url.scheme}://{url.host}/"]


async def _fetch_variants(
    fetcher: Fetcher, final_url: str, budget: DomainBudget, crawl_delay: float | None
) -> list[HostVariant] | None:
    """Sa proverom sertifikata i bez ponovnog pokušaja: TLS greška varijante je podatak o njoj."""
    urls = variant_urls(final_url)
    if not urls:
        return None
    variants = []
    for url in urls:
        outcome = await fetcher.request(url, budget, crawl_delay=crawl_delay, retries=0)
        canonical = None
        if outcome.status == 200 and outcome.body:
            strana = page_builder.build(
                url, final_url=outcome.final_url, status=200, headers=outcome.headers, body=outcome.body
            )
            canonical = strana.canonical_normalized
        variants.append(
            HostVariant(
                url=url,
                status=outcome.status,
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
    """Rekurzija kroz `sitemapindex` sa ograničenjima iz §4.4."""
    cfg = fetcher.config
    max_depth = get(cfg, "sitemap.max_depth")
    max_files = get(cfg, "sitemap.max_files")
    max_urls = get(cfg, "sitemap.max_urls")

    # `Sitemap:` iz robots.txt ima prednost nad pogađanjem (§4.3).
    start = list(rules.sitemaps) or [f"{origin}/sitemap.xml"]
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

        kind, locations = sitemap_parser.parse(outcome.body)
        info.depth_reached = max(info.depth_reached, depth)
        if kind == "index":
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
            )
        )


def probe_urls(domain: str, origin: str) -> list[str]:
    """Determinističke sonde po §5.2 — `sha1(domain)[:16]`, da testovi budu ponovljivi."""
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
# Prolaz nad listom domena
# --------------------------------------------------------------------------- #
async def scan_domains(
    targets: Iterable[DomainInput],
    config: dict,
    snapshot_dir: Path | None = None,
    on_done: Callable[[SiteSnapshot], None] | None = None,
) -> list[SiteSnapshot]:
    """Snapshot ide na disk čim je domen gotov — ako proces pukne na 190., imaš 189 (§8.2).

    `on_done` se zove za svaki završen domen, posle upisa na disk. Domen koji posle prvog
    pokušaja izgleda kao da ne radi ide na kraj reda i dobija drugi pokušaj, sa novim
    budžetom, najranije `http.second_attempt_after_s` posle prvog (Z-20).
    """
    targets = list(targets)
    results: list[SiteSnapshot] = []
    # Budžet od 25 s je za rad na domenu, ne za čekanje u redu iza ostalih 199:
    # `DomainBudget` nastaje u `fetch_site`, pa domen ulazi tamo tek kad dobije red.
    in_flight = asyncio.Semaphore(get(config, "http.domain_concurrency"))
    second_after = get(config, "http.second_attempt_after_s")

    async with Fetcher(config) as fetcher:

        async def attempt(target: DomainInput) -> SiteSnapshot:
            async with in_flight:
                log.info("nivo 1 počinje", extra={"domain": target.domain})
                try:
                    return await fetch_site(fetcher, target)
                except Exception as exc:  # noqa: BLE001 — granica domena
                    log.error("nivo 1 pukao: %s", exc, extra={"domain": target.domain})
                    return SiteSnapshot(
                        domain=target.domain,
                        industry=target.industry,
                        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        errors=[SnapshotError("fetch", type(exc).__name__, str(exc))],
                    )

        async def one(target: DomainInput) -> SiteSnapshot:
            snapshot = await attempt(target)
            if razlog := snapshot.entry_unreachable():
                domen = {"domain": target.domain}
                log.info("ne radi (%s); drugi pokušaj za %g s", razlog, second_after, extra=domen)
                # Čeka van semafora: mesto u redu za to vreme dobija drugi domen.
                await asyncio.sleep(second_after)
                first = snapshot.entry_attempts
                snapshot = await attempt(target)
                snapshot.entry_attempts = first + snapshot.entry_attempts
            if snapshot_dir is not None:
                store.write_site(snapshot_dir, snapshot)
            log.info(
                "nivo 1 gotov: %d stranica, %d zahteva",
                len(snapshot.pages),
                snapshot.budget.requests_made,
                extra={"domain": target.domain},
            )
            if on_done is not None:
                on_done(snapshot)
            return snapshot

        # Goli `gather` bi jednim izuzetkom oborio ceo prolaz — tačno greška iz §8.2.
        gathered = await asyncio.gather(*(one(t) for t in targets), return_exceptions=True)

    for target, item in zip(targets, gathered, strict=True):
        if isinstance(item, BaseException):
            log.error("domen izgubljen: %r", item, extra={"domain": target.domain})
            results.append(SiteSnapshot(domain=target.domain, industry=target.industry))
        else:
            results.append(item)
    return results
