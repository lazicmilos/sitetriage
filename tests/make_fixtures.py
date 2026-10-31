"""Generator of the hand-written test set: eight typical sites and the `check_id`s each must produce.

**These snapshots are written by hand, not recorded from real sites.** The domains are made
up, under the reserved TLD `.example` (RFC 2606): they describe the state the original
specification set for eight typical sites, not any real site.

That way they do the job they are meant for: they check that the chain
snapshot → checks → scoring → ranking gives the expected `check_id`s. Whether the tool sees
real sites the same way is checked by `pytest -m live` against your own domain list (see
`tests/test_live.py`).

Run it with `python tests/make_fixtures.py`. Gzip is written without a time in its header, so
running it again without changes does not change a single byte.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from sitetriage import store
from sitetriage.models import (
    BrowserSnapshot,
    ConsoleStats,
    DomStats,
    Entry,
    HostVariant,
    NetworkProfile,
    NetworkStats,
    OpenGraph,
    OversizedImage,
    PageSnapshot,
    RobotsInfo,
    SitemapInfo,
    SiteSnapshot,
    Soft404,
    Soft404Probe,
    TimingStats,
)

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED_AT = "2026-09-22T09:00:00Z"

# `None` has to mean "no tag", not "take the default"; otherwise the checks for a missing
# canonical could never be triggered from a fixture.
UNSET = object()

# Serbian text: test data for sites in Serbian.
SERBIAN = (
    "Dobrodošli. Nudimo usluge po povoljnim cenama, sa iskusnim timom i savremenom "
    "opremom. Zakažite termin telefonom ili preko kontakt forme. Radno vreme je od "
    "ponedeljka do petka. Cene možete pogledati u cenovniku, a sve dodatne informacije "
    "dobijate na licu mesta. Posebnu pažnju posvećujemo svakom klijentu. "
) * 3


def make_page(
    url: str,
    *,
    title: str | None = "Naslov",
    description: str | None | object = UNSET,
    canonical: str | None | object = UNSET,
    og: OpenGraph | None = None,
    lang: str | None = "sr",
    text: str = SERBIAN,
    h1: int = 1,
    html_bytes: int = 30_000,
    headers: dict[str, str] | None = None,
    raw_html: str | None = None,
) -> PageSnapshot:
    return PageSnapshot(
        url=url,
        final_url=url,
        status=200,
        elapsed_ms=500,
        headers=headers if headers is not None else {"content-encoding": "gzip"},
        html_bytes=html_bytes,
        title=title,
        # The default description is derived from the URL, so that every page has its own and
        # the duplicate check does not fire on a sample made for something else.
        meta_description=f"Opis stranice {url}" if description is UNSET else description,
        canonical=url if canonical is UNSET else canonical,
        canonical_normalized=url if canonical is UNSET else canonical,
        og=og or OpenGraph(title="OG", description="OG opis", image="/s.jpg", url=url),
        lang=lang,
        h1_count_raw=h1,
        text_sample=text[:4000],
        text_length=len(text),
        raw_html=raw_html,
    )


def make_site(
    domain: str,
    industry: str,
    *,
    pages: list[PageSnapshot],
    robots_status: int | None = 200,
    sitemap_status: int | None = 200,
    soft404_status: int = 404,
    elapsed_ms: int = 500,
    sample_source: str = "sitemap",
) -> SiteSnapshot:
    origin = f"https://{domain}"
    home_text = pages[0].text_sample if soft404_status == 200 else "Stranica nije pronađena."
    return SiteSnapshot(
        domain=domain,
        industry=industry,
        fetched_at=RECORDED_AT,
        entry=Entry(
            requested_url=f"{origin}/",
            final_url=f"{origin}/",
            redirect_chain=[f"{origin}/"],
            status=200,
            elapsed_ms=elapsed_ms,
        ),
        robots=RobotsInfo(
            status=robots_status,
            body="User-agent: *\nDisallow:\n" if robots_status == 200 else None,
        ),
        sitemap=SitemapInfo(
            status=sitemap_status,
            url=f"{origin}/sitemap.xml",
            urls=[p.url for p in pages[1:]] if sitemap_status == 200 else [],
        ),
        pages=pages,
        soft404=Soft404(
            probes=[
                Soft404Probe(url=f"{origin}/abc123", status=soft404_status, text_sample=home_text),
                Soft404Probe(url=f"{origin}/abc123.html", status=soft404_status, text_sample=home_text),
            ]
        ),
        sample_source=sample_source,
        # The specification says nothing about the other host variants, so all three redirect
        # to the final URL (ADR-014).
        host_variants=[
            HostVariant(
                url=url,
                status=200,
                final_url=f"{origin}/",
                redirect_chain=[url, f"{origin}/"],
                canonical=f"{origin}/",
            )
            for url in (f"https://www.{domain}/", f"http://{domain}/", f"http://www.{domain}/")
        ],
    )


def browser(
    domain: str,
    *,
    total_bytes: int = 900_000,
    request_count: int = 40,
    load_ms: int = 2000,
    h1: int = 1,
    images: int = 8,
    without_alt: int = 0,
    empty_alt: int = 0,
    oversized: int = 0,
    console_errors: int = 0,
) -> BrowserSnapshot:
    return BrowserSnapshot(
        domain=domain,
        url=f"https://{domain}/",
        fetched_at=RECORDED_AT,
        status="ok",
        network=NetworkStats(
            request_count=request_count,
            total_bytes=total_bytes,
            bytes_by_type={"image": int(total_bytes * 0.8), "script": int(total_bytes * 0.15)},
            # The specification describes the state until `load`; these pages load nothing after it.
            requests_at_load=request_count,
            bytes_at_load=total_bytes,
            bytes_by_type_at_load={"image": int(total_bytes * 0.8), "script": int(total_bytes * 0.15)},
        ),
        timing=TimingStats(dom_content_loaded_ms=load_ms // 2, load_ms=load_ms, reached="load"),
        dom=DomStats(
            h1_count=h1,
            images_total=images,
            images_without_alt_attr=without_alt,
            images_empty_alt=empty_alt,
            oversized_images=[
                OversizedImage(
                    src=f"https://{domain}/slika{i}.jpg",
                    natural=[4000, 2667],
                    client=[760, 507],
                    ratio=5.26,
                    est_waste_kb=600,
                )
                for i in range(oversized)
            ],
        ),
        console=ConsoleStats(errors=console_errors, warnings=2),
        network_profile=NetworkProfile(download_mbps=4.8, upload_mbps=1.5, latency_ms=150),
        link_mbps=100.0,
    )


# --------------------------------------------------------------------------- #
# The eight domains of the test set
# --------------------------------------------------------------------------- #
def institucija() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """The same canonical on every page, a soft 404, content drawn by JS → h1 only on level 2."""
    origin = "https://institucija.example"
    same = f"{origin}/"
    paths = ["/", "/o-nama", "/usluge/prva", "/vesti/nesto", "/kontakt", "/galerija", "/cenovnik"]
    pages = [
        make_page(
            f"{origin}{p}".rstrip("/") or same,
            title=f"Institucija{'' if p == '/' else ' — ' + p.strip('/')}",
            description=f"Opis za {p}",
            canonical=same,
            # The raw HTML is half empty: the content is drawn by JS, so level 1 does not see it.
            text=SERBIAN[:600],
            h1=0,
        )
        for p in paths
    ]
    site = make_site("institucija.example", "institution", pages=pages, soft404_status=200)
    # Weight below the threshold: this site's problem is SEO, not performance.
    return site, browser("institucija.example", total_bytes=1_200_000, request_count=45, h1=0)


def hotel_planina() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """No canonical and no og:title, no sitemap and no robots.txt, lang=zxx."""
    origin = "https://hotel-planina.example"
    pages = [
        make_page(
            f"{origin}/",
            title="Hotel Planina",
            canonical=None,
            og=OpenGraph(title=None, description="Smeštaj na planini", image="/hero.jpg"),
            lang="zxx",
            h1=0,
            raw_html="<html lang='zxx'><body>…</body></html>",
        ),
        make_page(f"{origin}/sobe", title="Sobe", canonical=f"{origin}/sobe", lang="zxx", h1=0),
        make_page(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt", lang="zxx", h1=0),
    ]
    site = make_site(
        "hotel-planina.example",
        "hotel",
        pages=pages,
        robots_status=404,
        sitemap_status=404,
        sample_source="links",
    )
    return site, browser("hotel-planina.example", h1=0)


def restoran_centar() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """No canonical; the home page transfers almost 15 MB."""
    origin = "https://restoran-centar.example"
    pages = [
        make_page(f"{origin}/", title="Restoran Centar", canonical=None),
        make_page(f"{origin}/meni", title="Meni", canonical=f"{origin}/meni"),
        make_page(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt"),
    ]
    site = make_site("restoran-centar.example", "restaurant", pages=pages)
    # The numbers of the snapshot example in the original specification.
    return site, browser("restoran-centar.example", total_bytes=14_903_221, request_count=87, load_ms=3800)


def restoran_ugao() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """No canonical, no description, no og:title and no og:description."""
    origin = "https://restoran-ugao.example"
    pages = [
        make_page(
            f"{origin}/",
            title="Restoran Ugao",
            description=None,
            canonical=None,
            og=OpenGraph(title=None, description=None, image="/s.jpg"),
        ),
        make_page(f"{origin}/meni", title="Meni", canonical=f"{origin}/meni"),
        make_page(f"{origin}/o-nama", title="O nama", canonical=f"{origin}/o-nama"),
    ]
    return make_site("restoran-ugao.example", "restaurant", pages=pages), browser("restoran-ugao.example")


def prodavnica() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """A heavy shop with many requests and no h1."""
    origin = "https://prodavnica.example"
    pages = [
        make_page(f"{origin}/", title="Prodavnica", h1=0),
        make_page(f"{origin}/proizvodi", title="Proizvodi", canonical=f"{origin}/proizvodi"),
        make_page(f"{origin}/dostava", title="Dostava", canonical=f"{origin}/dostava"),
    ]
    site = make_site("prodavnica.example", "ecommerce", pages=pages)
    return site, browser(
        "prodavnica.example",
        total_bytes=2_600_000,
        request_count=175,
        load_ms=5200,
        h1=0,
        images=40,
        oversized=4,
    )


def ordinacija() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Serbian content marked as English; 28 of 30 images without an alt attribute."""
    origin = "https://ordinacija.example"
    pages = [
        make_page(f"{origin}/", title="Ordinacija", lang="en-US"),
        make_page(f"{origin}/usluge", title="Usluge", canonical=f"{origin}/usluge", lang="en-US"),
        make_page(f"{origin}/cenovnik", title="Cenovnik", canonical=f"{origin}/cenovnik", lang="en-US"),
    ]
    site = make_site("ordinacija.example", "healthcare", pages=pages)
    return site, browser(
        "ordinacija.example", images=30, without_alt=28, empty_alt=1, total_bytes=1_100_000
    )


def b2b_firma() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Clean SEO, slow page: the only domain that exercises the fifth escalation condition."""
    origin = "https://b2b-firma.example"
    pages = [
        make_page(f"{origin}/", title="B2B firma"),
        make_page(f"{origin}/projekti", title="Projekti", canonical=f"{origin}/projekti"),
        make_page(f"{origin}/publikacije", title="Publikacije", canonical=f"{origin}/publikacije"),
    ]
    # No level-1 finding; it reaches level 2 only because the home page answers slowly.
    site = make_site("b2b-firma.example", "b2b", pages=pages, elapsed_ms=2400)
    return site, browser("b2b-firma.example", total_bytes=2_100_000, request_count=60, load_ms=6100)


def klinika() -> tuple[SiteSnapshot, None]:
    """The control clean site. A more valuable test than all the others above."""
    origin = "https://klinika.example"
    pages = [
        make_page(f"{origin}/", title="Klinika"),
        make_page(f"{origin}/usluge", title="Usluge", canonical=f"{origin}/usluge"),
        make_page(f"{origin}/o-nama", title="O nama", canonical=f"{origin}/o-nama"),
        make_page(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt"),
    ]
    # The only gap is robots.txt (low), nothing that would lift it in the report.
    return make_site("klinika.example", "healthcare", pages=pages, robots_status=404), None


DOMAINS = {
    "institucija.example": institucija,
    "hotel-planina.example": hotel_planina,
    "restoran-centar.example": restoran_centar,
    "restoran-ugao.example": restoran_ugao,
    "prodavnica.example": prodavnica,
    "ordinacija.example": ordinacija,
    "b2b-firma.example": b2b_firma,
    "klinika.example": klinika,
}


def _without_mtime(path: Path) -> None:
    """`gzip.compress` writes the current time; without it the same input gives the same bytes."""
    path.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()), mtime=0))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for domain, build in DOMAINS.items():
        site, browser_snapshot = build()
        _without_mtime(store.write_site(FIXTURES, site, compress=True))
        if browser_snapshot is not None:
            _without_mtime(store.write_browser(FIXTURES, browser_snapshot, compress=True))
        print(f"{domain}: {len(site.pages)} pages, level 2 {'yes' if browser_snapshot else 'no'}")


if __name__ == "__main__":
    main()
