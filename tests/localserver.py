"""A fake site on `localhost` for integration tests.

The fetcher and browser layers cannot be tested against real sites: a test against a real
domain depends on whether that site happens to be online this morning. Network code and the
code that draws conclusions are separate layers, so checks are tested on snapshots and only
the fetching layers need a server. This one is broken on purpose in exactly the ways a test
asks for, so the tests stay offline and deterministic.
"""

from __future__ import annotations

import gzip
import threading
import time
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Response:
    body: bytes = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    # Headers and the first byte at once, the rest only after `stall` seconds, like a stream
    # or a video that never finishes. `delay` comes before the headers, this after them.
    stall: float = 0.0
    # The body is already compressed as `content-encoding` says, so it is sent as is (a bomb of
    # a few kB).
    encoded: bool = False
    # The body in chunks, without Content-Length and until the connection closes: a stream that
    # never ends or that trickles.
    chunks: Callable[[], Iterable[bytes]] | None = None


def bomb(size: int, *, encoding: str = "gzip", prefix: bytes = b"") -> bytes:
    """`prefix` followed by spaces up to `size` bytes, compressed chunk by chunk: 64 MB becomes ~65 kB.

    `gzip` is the gzip wrapper, `deflate` the zlib wrapper (the way most servers send it).
    """
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31 if encoding == "gzip" else 15)
    parts = [compressor.compress(prefix)]
    remaining, block = size - len(prefix), b" " * (1 << 20)
    while remaining > 0:
        parts.append(compressor.compress(block[: min(remaining, len(block))]))
        remaining -= len(block)
    return b"".join(parts) + compressor.flush()


def endless(chunk: bytes = b"x" * 65536, *, pause: float = 0.0) -> Callable[[], Iterable[bytes]]:
    """A body that never ends: fast (`pause=0`) or drop by drop, just under the read timeout."""

    def chunks() -> Iterable[bytes]:
        while True:
            yield chunk
            if pause:
                time.sleep(pause)

    return chunks


def html(title: str, *, body: str = "", head: str = "") -> bytes:
    """A Serbian page. The text is test data, long enough and with diacritics for the language check."""
    return (
        f"<!doctype html><html lang='sr'><head><title>{title}</title>{head}</head>"
        f"<body><h1>{title}</h1><p>Sadržaj stranice o uslugama i cenama, sa dijakriticima "
        f"čćšžđ, dovoljno dug da jezička heuristika bude pouzdana. {'Tekst. ' * 60}</p>"
        f"{body}</body></html>"
    ).encode()


SITEMAP_INDEX = (
    b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<sitemap><loc>{base}/sitemap-1.xml</loc></sitemap></sitemapindex>"
)
SITEMAP_URLS = (
    b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<url><loc>{base}/usluge</loc></url>"
    b"<url><loc>{base}/o-nama</loc></url>"
    b"<url><loc>{base}/kontakt</loc></url>"
    b"<url><loc>{base}/blog/prvi</loc></url>"
    b"<url><loc>{base}/blog/drugi</loc></url>"
    b"<url><loc>{base}/tajno/nesto</loc></url>"
    b"</urlset>"
)

ROBOTS = b"""User-agent: *
Disallow: /tajno
Sitemap: {base}/sitemap.xml
"""


# Addresses of the local servers that are running. `127.0.0.1` is a private address and the
# scanner does not open it (ADR-006), so `conftest.py` allows exactly these, not every private
# address.
RUNNING: set[FakeSite] = set()


def allowed_addresses() -> frozenset[tuple[str, int]]:
    return frozenset(site.address for site in RUNNING)


class FakeSite:
    """Serves prepared responses and records what was requested.

    `allowed=False` makes a server the scanner must not open: the target of a redirect or of
    a resource in the SSRF protection tests.
    """

    def __init__(
        self,
        *,
        soft404: bool = False,
        extra: dict[str, Response | Callable[[], Response]] | None = None,
        allowed: bool = True,
    ) -> None:
        self.allowed = allowed
        self.soft404 = soft404
        self.extra = extra or {}
        self.requests: list[str] = []
        self.concurrent_peak = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ------------------------------------------------------------------ server
    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return host, port

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeSite:
        self._thread.start()
        if self.allowed:
            RUNNING.add(self)
        return self

    def __exit__(self, *_exc: object) -> None:
        RUNNING.discard(self)
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def paths(self) -> list[str]:
        return list(self.requests)

    # ----------------------------------------------------------------- content
    def route(self, path: str) -> Response:
        base = self.base_url.encode()
        routes: dict[str, Response] = {
            "/": Response(
                html(
                    "Početna",
                    head=(
                        f"<link rel='canonical' href='{self.base_url}/'>"
                        "<meta name='description' content='Opis početne strane.'>"
                        "<meta property='og:title' content='OG naslov'>"
                        "<meta property='og:description' content='OG opis'>"
                        "<meta property='og:image' content='/slika.jpg'>"
                    ),
                    body="<a href='/usluge'>usluge</a><a href='/o-nama'>o nama</a>",
                )
            ),
            "/robots.txt": Response(ROBOTS.replace(b"{base}", base), headers={"content-type": "text/plain"}),
            "/sitemap.xml": Response(
                SITEMAP_INDEX.replace(b"{base}", base), headers={"content-type": "application/xml"}
            ),
            "/sitemap-1.xml": Response(
                SITEMAP_URLS.replace(b"{base}", base), headers={"content-type": "application/xml"}
            ),
            "/usluge": Response(html("Usluge")),
            "/o-nama": Response(html("O nama")),
            "/kontakt": Response(html("Kontakt")),
            "/blog/prvi": Response(html("Prvi tekst")),
            "/blog/drugi": Response(html("Drugi tekst")),
            "/tajno/nesto": Response(html("Tajna strana")),
        }
        routes.update(self.extra)

        if path in routes:
            found = routes[path]
            return found() if callable(found) else found
        if self.soft404:
            # A site that answers a missing address with its home page: a soft 404.
            return routes["/"]
        return Response(b"<html><h1>404</h1></html>", status=404)

    # ----------------------------------------------------------------- handler
    def _handler(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 — the name is set by the library
                with site._lock:
                    site.requests.append(self.path)
                    site._in_flight += 1
                    site.concurrent_peak = max(site.concurrent_peak, site._in_flight)
                try:
                    response = site.route(self.path)
                    if response.delay:
                        time.sleep(response.delay)
                    body = response.body
                    headers = dict(response.headers)
                    if headers.get("content-encoding") == "gzip" and not response.encoded:
                        body = gzip.compress(body)
                    if headers.get("content-encoding") == "deflate" and not response.encoded:
                        body = zlib.compress(body)
                    self.send_response(response.status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    if response.chunks is not None:
                        self.send_header("Connection", "close")
                    else:
                        self.send_header("Content-Length", str(len(body)))
                    if "content-type" not in {k.lower() for k in headers}:
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    if response.chunks is not None:
                        for chunk in response.chunks():
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        return
                    if response.stall:
                        self.wfile.write(body[:1])
                        self.wfile.flush()
                        time.sleep(response.stall)
                        body = body[1:]
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up mid-response, which is the point of `stall`
                finally:
                    with site._lock:
                        site._in_flight -= 1

            def log_message(self, *_args: object) -> None:
                """Silence; otherwise the tests print the access log."""

        return Handler
