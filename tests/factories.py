"""Gradivni blokovi za testove: čist sajt kao polazna tačka.

Baza je sajt na kome **nijedna provera ne sme da nađe ništa**. Svaki pozitivan
test kvari tačno jednu stvar. To je U4 pretvoren u alat: ako neka provera počne
da laje na čistu bazu, pada ceo skup testova odjednom (§1.2, §12.3).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from skener.checks import registry
from skener.config import load_config
from skener.models import (
    BrowserSnapshot,
    ConsoleStats,
    DomStats,
    Entry,
    HostVariant,
    NetworkStats,
    OpenGraph,
    PageSnapshot,
    RobotsInfo,
    SitemapInfo,
    SiteSnapshot,
    Soft404,
    Soft404Probe,
    TimingStats,
    Tls,
)

registry.load_all()
CONFIG = load_config()

# Dovoljno dug srpski tekst da jezička heuristika bude pouzdana (§5.1) i da
# stranica ne izgleda prazno politici eskalacije (§6).
SRPSKI_TEKST = (
    "Dobrodošli u našu ordinaciju. Nudimo usluge opšte stomatologije, protetike i "
    "implantologije. Naš tim čine iskusni lekari koji rade sa najsavremenijom opremom. "
    "Zakažite pregled telefonom ili putem kontakt forme. Radno vreme je od ponedeljka do "
    "petka, a subotom radimo po dogovoru. Cene usluga možete pogledati u cenovniku. "
    "Posebnu pažnju posvećujemo deci i pacijentima koji imaju strah od stomatologa. "
) * 4


def page(
    url: str,
    *,
    title: str | None = "Naslov stranice",
    description: str | None = "Opis stranice koji je jedinstven.",
    canonical: str | None = None,
    og: OpenGraph | None = None,
    lang: str | None = "sr",
    text: str = SRPSKI_TEKST,
    status: int = 200,
    html_bytes: int = 20_000,
    headers: dict[str, str] | None = None,
    h1_count_raw: int = 1,
    **kwargs: Any,
) -> PageSnapshot:
    return PageSnapshot(
        url=url,
        final_url=url,
        status=status,
        elapsed_ms=400,
        headers=headers if headers is not None else {"content-encoding": "gzip"},
        html_bytes=html_bytes,
        title=title,
        meta_description=description,
        canonical=canonical if canonical is not None else url,
        canonical_normalized=canonical if canonical is not None else url,
        og=og or OpenGraph(title="OG naslov", description="OG opis", image="https://d.rs/slika.jpg", url=url),
        lang=lang,
        h1_count_raw=h1_count_raw,
        text_sample=text[:4000],
        text_length=len(text),
        **kwargs,
    )


def clean_site(*, domain: str = "cist.rs", industry: str = "ostalo", **overrides: Any) -> SiteSnapshot:
    """Sajt bez ijednog problema. Sve provere nivoa 1 nad njim moraju biti `ok`."""
    home = page(f"https://{domain}/", raw_html=f"<html lang=sr><h1>Naslov</h1>{SRPSKI_TEKST}</html>")
    others = [
        page(f"https://{domain}/usluge", title="Usluge", description="Spisak naših usluga."),
        page(f"https://{domain}/o-nama", title="O nama", description="Ko smo i čime se bavimo."),
        page(f"https://{domain}/kontakt", title="Kontakt", description="Adresa i telefon."),
        page(f"https://{domain}/blog/prvi", title="Prvi tekst", description="Uvodni tekst bloga."),
    ]
    snapshot = SiteSnapshot(
        domain=domain,
        industry=industry,
        fetched_at="2026-09-22T09:00:00Z",
        entry=Entry(
            requested_url=f"https://{domain}/",
            final_url=f"https://{domain}/",
            redirect_chain=[f"https://{domain}/"],
            status=200,
            elapsed_ms=400,
            tls=Tls(valid=True),
        ),
        robots=RobotsInfo(status=200, body="User-agent: *\nDisallow:\n"),
        sitemap=SitemapInfo(
            status=200,
            url=f"https://{domain}/sitemap.xml",
            urls=[p.url for p in others],
        ),
        pages=[home, *others],
        soft404=Soft404(
            probes=[
                Soft404Probe(url=f"https://{domain}/abc123", status=404),
                Soft404Probe(url=f"https://{domain}/abc123.html", status=404),
            ]
        ),
        sample_source="sitemap",
        # Sve tri preostale adrese preusmeravaju na konačnu (Z-26).
        host_variants=[
            HostVariant(
                url=url,
                status=200,
                final_url=f"https://{domain}/",
                redirect_chain=[url, f"https://{domain}/"],
                canonical=f"https://{domain}/",
            )
            for url in (f"https://www.{domain}/", f"http://{domain}/", f"http://www.{domain}/")
        ],
    )
    return replace(snapshot, **overrides) if overrides else snapshot


def clean_browser(*, domain: str = "cist.rs", **overrides: Any) -> BrowserSnapshot:
    """Nacrtana stranica bez ijednog problema nivoa 2."""
    snapshot = BrowserSnapshot(
        domain=domain,
        url=f"https://{domain}/",
        fetched_at="2026-09-22T09:00:00Z",
        status="ok",
        network=NetworkStats(
            request_count=30,
            total_bytes=900_000,
            bytes_by_type={"image": 600_000, "script": 200_000, "css": 100_000},
            unmeasured_responses=0,
            # Čista stranica ne učitava ništa posle `load`, pa je „do load" isto što i ukupno.
            requests_at_load=30,
            bytes_at_load=900_000,
            bytes_by_type_at_load={"image": 600_000, "script": 200_000, "css": 100_000},
            unmeasured_at_load=0,
        ),
        timing=TimingStats(dom_content_loaded_ms=800, load_ms=1800, reached="load"),
        dom=DomStats(
            h1_count=1,
            images_total=10,
            images_without_alt_attr=0,
            images_empty_alt=2,
            oversized_images=[],
            images_unmeasured=0,
        ),
        console=ConsoleStats(errors=0, warnings=2),
    )
    return replace(snapshot, **overrides) if overrides else snapshot


def run_level(level: int, snapshot: Any, industry: str = "ostalo", browser: Any = None) -> dict[str, Any]:
    ctx = registry.Context(domain=snapshot.domain, industry=industry, config=CONFIG, browser=browser)
    return {result.check_id: result for result in registry.run(level, snapshot, ctx)}


def statuses(results: dict[str, Any]) -> dict[str, str]:
    return {check_id: result.status for check_id, result in results.items()}


def findings(results: dict[str, Any]) -> set[str]:
    return {check_id for check_id, result in results.items() if result.status == "finding"}
