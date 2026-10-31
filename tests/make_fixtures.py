"""Generator ispitnog skupa iz §12.4.

**Ovi snapshoti su ručno napisani, nisu snimljeni sa pravih sajtova.** Domeni su
izmišljeni, pod rezervisanim TLD-om `.example` (RFC 2606): opisuju stanje koje §12.4
zadaje za osam tipičnih sajtova, a ne nijedan stvaran sajt.

Time rade posao koji im je namenjen: proveravaju da lanac
snapshot → provere → bodovanje → rangiranje daje očekivane `check_id`-eve. Da li
alat isto vidi prave sajtove, proverava `pytest -m live` nad tvojom listom domena
(vidi `tests/test_live.py`).

Pokretanje: `python tests/make_fixtures.py`. Gzip se piše bez vremena u zaglavlju,
pa ponovno pokretanje bez izmena ne menja nijedan bajt.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from skener import store
from skener.models import (
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
SNIMLJENO = "2026-09-22T09:00:00Z"

# `None` mora da znači „nema oznake", a ne „uzmi podrazumevanu" — inače se
# provere za nedostajući canonical nikad ne mogu izazvati iz fixture-a.
NEZADATO = object()

SRPSKI = (
    "Dobrodošli. Nudimo usluge po povoljnim cenama, sa iskusnim timom i savremenom "
    "opremom. Zakažite termin telefonom ili preko kontakt forme. Radno vreme je od "
    "ponedeljka do petka. Cene možete pogledati u cenovniku, a sve dodatne informacije "
    "dobijate na licu mesta. Posebnu pažnju posvećujemo svakom klijentu. "
) * 3


def stranica(
    url: str,
    *,
    title: str | None = "Naslov",
    description: str | None | object = NEZADATO,
    canonical: str | None | object = NEZADATO,
    og: OpenGraph | None = None,
    lang: str | None = "sr",
    text: str = SRPSKI,
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
        # Podrazumevani opis se izvodi iz adrese: da svaka stranica ima svoj i da
        # provera duplikata ne puca na uzorku koji je pravljen za nešto drugo.
        meta_description=f"Opis stranice {url}" if description is NEZADATO else description,
        canonical=url if canonical is NEZADATO else canonical,
        canonical_normalized=url if canonical is NEZADATO else canonical,
        og=og or OpenGraph(title="OG", description="OG opis", image="/s.jpg", url=url),
        lang=lang,
        h1_count_raw=h1,
        text_sample=text[:4000],
        text_length=len(text),
        raw_html=raw_html,
    )


def sajt(
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
        fetched_at=SNIMLJENO,
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
        # §12.4 ne kaže ništa o ostalim adresama, pa sve tri preusmeravaju na konačnu (Z-26).
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
    bez_alta: int = 0,
    prazan_alt: int = 0,
    oversized: int = 0,
    console_errors: int = 0,
) -> BrowserSnapshot:
    return BrowserSnapshot(
        domain=domain,
        url=f"https://{domain}/",
        fetched_at=SNIMLJENO,
        status="ok",
        network=NetworkStats(
            request_count=request_count,
            total_bytes=total_bytes,
            bytes_by_type={"image": int(total_bytes * 0.8), "script": int(total_bytes * 0.15)},
            # §12.4 opisuje stanje do `load`; posle njega ove stranice ne učitavaju ništa.
            requests_at_load=request_count,
            bytes_at_load=total_bytes,
            bytes_by_type_at_load={"image": int(total_bytes * 0.8), "script": int(total_bytes * 0.15)},
        ),
        timing=TimingStats(dom_content_loaded_ms=load_ms // 2, load_ms=load_ms, reached="load"),
        dom=DomStats(
            h1_count=h1,
            images_total=images,
            images_without_alt_attr=bez_alta,
            images_empty_alt=prazan_alt,
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
# Osam domena iz §12.4
# --------------------------------------------------------------------------- #
def institucija() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Canonical na svakoj strani isti, lažni 404, sadržaj iz JS-a → h1 tek na nivou 2."""
    origin = "https://institucija.example"
    isti = f"{origin}/"
    putanje = ["/", "/o-nama", "/usluge/prva", "/vesti/nesto", "/kontakt", "/galerija", "/cenovnik"]
    pages = [
        stranica(
            f"{origin}{p}".rstrip("/") or isti,
            title=f"Institucija{'' if p == '/' else ' — ' + p.strip('/')}",
            description=f"Opis za {p}",
            canonical=isti,
            # Sirovi HTML je poluprazan: sadržaj se crta iz JS-a, pa ga nivo 1 ne vidi.
            text=SRPSKI[:600],
            h1=0,
        )
        for p in putanje
    ]
    site = sajt("institucija.example", "institucija", pages=pages, soft404_status=200)
    # Težina ispod praga: problem institucije je SEO, ne performanse.
    return site, browser("institucija.example", total_bytes=1_200_000, request_count=45, h1=0)


def hotel_planina() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Nema canonical ni og:title, nema sitemap ni robots, lang=zxx."""
    origin = "https://hotel-planina.example"
    pages = [
        stranica(
            f"{origin}/",
            title="Hotel Planina",
            canonical=None,
            og=OpenGraph(title=None, description="Smeštaj na planini", image="/hero.jpg"),
            lang="zxx",
            h1=0,
            raw_html="<html lang='zxx'><body>…</body></html>",
        ),
        stranica(f"{origin}/sobe", title="Sobe", canonical=f"{origin}/sobe", lang="zxx", h1=0),
        stranica(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt", lang="zxx", h1=0),
    ]
    site = sajt(
        "hotel-planina.example",
        "hotel",
        pages=pages,
        robots_status=404,
        sitemap_status=404,
        sample_source="links",
    )
    return site, browser("hotel-planina.example", h1=0)


def restoran_centar() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Nema canonical; početna prenosi skoro 15 MB."""
    origin = "https://restoran-centar.example"
    pages = [
        stranica(f"{origin}/", title="Restoran Centar", canonical=None),
        stranica(f"{origin}/meni", title="Meni", canonical=f"{origin}/meni"),
        stranica(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt"),
    ]
    site = sajt("restoran-centar.example", "restoran", pages=pages)
    # Brojevi iz primera u §3.3.
    return site, browser("restoran-centar.example", total_bytes=14_903_221, request_count=87, load_ms=3800)


def restoran_ugao() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Nema canonical, opis ni og:title i og:description."""
    origin = "https://restoran-ugao.example"
    pages = [
        stranica(
            f"{origin}/",
            title="Restoran Ugao",
            description=None,
            canonical=None,
            og=OpenGraph(title=None, description=None, image="/s.jpg"),
        ),
        stranica(f"{origin}/meni", title="Meni", canonical=f"{origin}/meni"),
        stranica(f"{origin}/o-nama", title="O nama", canonical=f"{origin}/o-nama"),
    ]
    return sajt("restoran-ugao.example", "restoran", pages=pages), browser("restoran-ugao.example")


def prodavnica() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Teška prodavnica sa mnogo zahteva i bez h1."""
    origin = "https://prodavnica.example"
    pages = [
        stranica(f"{origin}/", title="Prodavnica", h1=0),
        stranica(f"{origin}/proizvodi", title="Proizvodi", canonical=f"{origin}/proizvodi"),
        stranica(f"{origin}/dostava", title="Dostava", canonical=f"{origin}/dostava"),
    ]
    site = sajt("prodavnica.example", "ecommerce", pages=pages)
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
    """Srpski sadržaj označen kao engleski; 28 od 30 slika bez alt atributa."""
    origin = "https://ordinacija.example"
    pages = [
        stranica(f"{origin}/", title="Ordinacija", lang="en-US"),
        stranica(f"{origin}/usluge", title="Usluge", canonical=f"{origin}/usluge", lang="en-US"),
        stranica(f"{origin}/cenovnik", title="Cenovnik", canonical=f"{origin}/cenovnik", lang="en-US"),
    ]
    site = sajt("ordinacija.example", "zdravstvo", pages=pages)
    return site, browser(
        "ordinacija.example", images=30, bez_alta=28, prazan_alt=1, total_bytes=1_100_000
    )


def b2b_firma() -> tuple[SiteSnapshot, BrowserSnapshot]:
    """Čist SEO, spora stranica — jedini domen koji proverava peti uslov eskalacije."""
    origin = "https://b2b-firma.example"
    pages = [
        stranica(f"{origin}/", title="B2B firma"),
        stranica(f"{origin}/projekti", title="Projekti", canonical=f"{origin}/projekti"),
        stranica(f"{origin}/publikacije", title="Publikacije", canonical=f"{origin}/publikacije"),
    ]
    # Nijedan nalaz nivoa 1; na nivo 2 stiže samo zato što početna odgovara sporo.
    site = sajt("b2b-firma.example", "b2b", pages=pages, elapsed_ms=2400)
    return site, browser("b2b-firma.example", total_bytes=2_100_000, request_count=60, load_ms=6100)


def klinika() -> tuple[SiteSnapshot, None]:
    """Kontrolni čist sajt. Vredniji test od svih prethodnih (§12.4)."""
    origin = "https://klinika.example"
    pages = [
        stranica(f"{origin}/", title="Klinika"),
        stranica(f"{origin}/usluge", title="Usluge", canonical=f"{origin}/usluge"),
        stranica(f"{origin}/o-nama", title="O nama", canonical=f"{origin}/o-nama"),
        stranica(f"{origin}/kontakt", title="Kontakt", canonical=f"{origin}/kontakt"),
    ]
    # Jedini propust je robots.txt (low) — ništa što bi ga podiglo u izveštaju.
    return sajt("klinika.example", "zdravstvo", pages=pages, robots_status=404), None


DOMENI = {
    "institucija.example": institucija,
    "hotel-planina.example": hotel_planina,
    "restoran-centar.example": restoran_centar,
    "restoran-ugao.example": restoran_ugao,
    "prodavnica.example": prodavnica,
    "ordinacija.example": ordinacija,
    "b2b-firma.example": b2b_firma,
    "klinika.example": klinika,
}


def _bez_vremena(path: Path) -> None:
    """`gzip.compress` upisuje trenutno vreme; bez njega isti ulaz daje iste bajtove."""
    path.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()), mtime=0))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for domain, build in DOMENI.items():
        site, browser_snapshot = build()
        _bez_vremena(store.write_site(FIXTURES, site, compress=True))
        if browser_snapshot is not None:
            _bez_vremena(store.write_browser(FIXTURES, browser_snapshot, compress=True))
        print(f"{domain}: {len(site.pages)} stranica, nivo 2 {'da' if browser_snapshot else 'ne'}")


if __name__ == "__main__":
    main()
