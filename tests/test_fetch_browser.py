"""Nivo 2 protiv lokalnog servera i pravog Chromiuma (§7).

Označeno `browser`: preskače se ako Playwright ili Chromium nisu instalirani.
"""

from __future__ import annotations

import asyncio
import gzip
import struct
import zlib

import pytest
from factories import run_level
from localserver import FakeSite, Response

from skener import addresses, pipeline
from skener.config import load_config
from skener.fetch.browser import est_waste_kb
from skener.models import (
    BrowserSnapshot,
    Entry,
    NetworkProfile,
    PageSnapshot,
    SiteSnapshot,
    from_dict,
    to_jsonable,
)

playwright_api = pytest.importorskip("playwright.async_api", reason="Playwright nije instaliran")
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module", autouse=True)
def chromium_se_pokrece():
    """Uvoz nije dovoljan: paket bez odgovarajućeg Chromium-a puca tek na `launch`.

    Tipično posle nadogradnje Playwright-a bez `playwright install` — to je stanje
    okruženja, ne greška u alatu, pa je preskakanje, a ne deset crvenih testova.
    """
    from skener.fetch.browser import _launch_options

    async def probaj() -> None:
        async with playwright_api.async_playwright() as pw:
            browser = await pw.chromium.launch(**_launch_options(load_config()))
            await browser.close()

    try:
        asyncio.run(probaj())
    except playwright_api.Error as exc:
        razlog = str(exc).splitlines()[0]
        pytest.skip(f"Chromium se ne pokreće ({razlog}); pokreni `playwright install chromium`")


def png(width: int, height: int) -> bytes:
    """Minimalan validan PNG — da `naturalWidth` bude stvaran, bez nove zavisnosti."""
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


TESKA_STRANA = """<!doctype html><html lang="sr"><head><title>Teška strana</title>
<style>img{{width:100px}} .daleko{{margin-top:4000px}}</style></head>
<body>
  <h2>Nema h1 na ovoj strani</h2>
  <img src="/velika.png">
  <img src="/velika.png" alt="">
  <img src="/velika.png" alt="opisana slika">
  {bez_alta}
  <div class="daleko"><img src="/lenja.png" loading="lazy"></div>
  <script src="/tezak.js"></script>
  <script>null.x = 1;</script>
  <script>undefined.y = 2;</script>
  <script>console.error("prva"); console.error("druga"); console.warn("upozorenje");</script>
</body></html>"""


def teski_sajt() -> FakeSite:
    bez_alta = "".join('<img src="/velika.png">' for _ in range(7))
    return FakeSite(
        extra={
            "/": Response(TESKA_STRANA.format(bez_alta=bez_alta).encode()),
            "/velika.png": Response(png(800, 600), headers={"content-type": "image/png"}),
            "/lenja.png": Response(png(900, 600), headers={"content-type": "image/png"}),
            "/tezak.js": Response(
                b"window.__x = '" + b"y" * 300_000 + b"';",
                headers={"content-type": "application/javascript"},
            ),
        }
    )


def snimi(site: FakeSite, config: dict | None = None):
    from skener.fetch.browser import capture_all

    fake = SiteSnapshot(
        domain=site.base_url,
        pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        entry=Entry(requested_url=site.base_url + "/", final_url=site.base_url + "/", status=200),
    )
    return asyncio.run(capture_all([fake], config or load_config()))[site.base_url]


@pytest.fixture(scope="module")
def snimak():
    with teski_sajt() as site:
        yield snimi(site)


SAOBRACAJ_OKO_LOAD = b"""<!doctype html><html><body><h1>Strana</h1>
<script>
fetch('/sporo.bin');
window.addEventListener('load', () => setTimeout(() => fetch('/posle.bin'), 100));
</script><img src="/drzi.png"></body></html>"""


@pytest.fixture(scope="module")
def oko_load():
    """Z-24: zahtev pre `load` čije telo stiže posle njega, i zahtev koji počne tek posle `load`."""
    extra = {
        "/": Response(SAOBRACAJ_OKO_LOAD),
        # `load` čeka sliku. Bez nje stiže odmah posle skripte, a Playwright uz `route` javlja
        # `request` tek kad zahtev stigne do mreže, pa je pod opterećenjem fetch viđen posle `load`.
        "/drzi.png": Response(png(1, 1), headers={"content-type": "image/png"}, delay=0.5),
        # Zaglavlja odmah, telo posle 3 s: odgovor je viđen pre `drain`, a telo stiže posle `load`.
        "/sporo.bin": Response(b"s" * 150_000, stall=3.0),
        "/posle.bin": Response(b"p" * 200_000),
    }
    with FakeSite(extra=extra) as site:
        yield snimi(site)


def test_zahtev_posle_load_ne_ulazi_u_tezinu(oko_load):
    mreza = oko_load.network
    assert mreza.bytes_at_load < 200_000, "posle.bin (200 kB) ne ulazi u težinu"
    assert mreza.total_bytes - mreza.bytes_at_load >= 200_000, "ali je u ukupnom, informativno"
    assert mreza.request_count > mreza.requests_at_load


def test_telo_koje_stigne_posle_load_za_zahtev_pre_load_se_broji(oko_load):
    assert oko_load.timing.load_ms < 3000, "telo sporo.bin mora da stigne posle `load`"
    assert oko_load.network.bytes_at_load >= 150_000


# Z-30: 600 kB na simuliranoj vezi od 4,8 Mb/s (600 000 B/s) traje oko 1 s.
TEZAK_JS = b"//" + b"x" * 600_000


def sa_teskim_skriptom() -> dict[str, Response]:
    return {
        "/": Response(b"<!doctype html><h1>Strana</h1><script src='/tezak.js'></script>"),
        "/tezak.js": Response(TEZAK_JS),
    }


def test_profil_usporava_ucitavanje():
    """Proverava se samo donja granica, da test ne bi bio nestabilan."""
    with FakeSite(extra=sa_teskim_skriptom()) as site:
        assert snimi(site).timing.load_ms >= 1000


def test_profil_vazi_i_za_iframe_sa_drugog_porekla(monkeypatch):
    """Pun Chromium, kao sistemski, učitava iframe sa drugog sajta u poseban proces (OOPIF), a
    profil postavljen na stranicu taj proces ne usporava. `localhost` i `127.0.0.1` su dva sajta."""
    from skener.fetch import browser

    pokretanje = browser._launch_options
    monkeypatch.setattr(browser, "_launch_options", lambda cfg: {**pokretanje(cfg), "channel": "chromium"})
    with FakeSite(extra=sa_teskim_skriptom()) as okvir:
        port = okvir.address[1]
        # conftest dozvoljava `127.0.0.1:port`, a `localhost` se razrešava i na `::1`
        dozvoljene = addresses.allowlist
        monkeypatch.setattr(addresses, "allowlist", lambda cfg: dozvoljene(cfg) | {("localhost", port)})
        strana = f"<!doctype html><h1>Strana</h1><iframe src='http://localhost:{port}/'></iframe>"
        with FakeSite(extra={"/": Response(strana.encode())}) as site:
            assert snimi(site).timing.load_ms >= 1000


def test_profil_je_u_snapshotu_i_jsonu(snimak):
    profil = NetworkProfile(download_mbps=4.8, upload_mbps=1.5, latency_ms=150)
    assert snimak.network_profile == profil
    assert from_dict(BrowserSnapshot, to_jsonable(snimak)).network_profile == profil
    assert pipeline._environment([snimak])["network_profile"] == profil


def test_browser_belezi_tekst_i_lang_posle_javascript_a():
    """Z-25: sirovi HTML nema ni `lang` ni tekst; oba postavlja JavaScript."""
    strana = (
        "<!doctype html><html><body><script>"
        "document.documentElement.lang = 'sr';"
        "document.body.insertAdjacentHTML("
        "'beforeend', '<p>Dobrodošli   u   ordinaciju. Zakažite pregled.</p>');"
        "</script></body></html>"
    ).encode()
    with FakeSite(extra={"/": Response(strana)}) as site:
        snimljeno = snimi(site)
    assert snimljeno.dom.lang == "sr"
    assert snimljeno.dom.text_sample == "Dobrodošli u ordinaciju. Zakažite pregled."
    assert snimljeno.dom.text_length == len(snimljeno.dom.text_sample)


def test_browser_belezi_interne_veze_iz_renderovanog_doma():
    """Z-21: vezu koju crta JavaScript vidi samo nivo 2; spoljna veza nije interna."""
    strana = (
        b"<!doctype html><html><body><a href='/o-nama'>o nama</a><a href='https://drugi.rs/'>x</a>"
        b"<script>document.body.insertAdjacentHTML('beforeend', \"<a href='/iz-js'>js</a>\")</script>"
        b"</body></html>"
    )
    with FakeSite(extra={"/": Response(strana)}) as site:
        snimljeno = snimi(site)
    assert snimljeno.dom.internal_links == [f"{site.base_url}/o-nama", f"{site.base_url}/iz-js"]
    assert snimljeno.dom.internal_links_total == 2


# --------------------------------------------------------------------------- #
# Merenje težine (§7.2) — najozbiljnija zamka u projektu
# --------------------------------------------------------------------------- #
def test_tezina_se_meri_iz_mreznog_saobracaja(snimak):
    """Performance API bi ovde vratio skoro nulu za resurse sa drugog porekla."""
    assert snimak.status == "ok"
    assert snimak.network.total_bytes > 300_000, "skripta od 300 kB mora da se vidi u zbiru"
    # Deset `<img>` sa istim URL-om je jedan zahtev — browser ih sam sažima.
    assert snimak.network.request_count >= 4
    assert snimak.network.bytes_by_type.get("script", 0) > 250_000
    assert snimak.network.bytes_by_type.get("image", 0) > 0


def test_tezina_broji_prenete_bajtove_a_ne_raspakovane():
    """BUG-016: rečenica kaže „prenosi X MB", pa se broji ono što je stvarno preneto.

    `response.body()` vraća raspakovano telo. JS i CSS putuju sažeti, pa je zbir za
    sajtove sa mnogo skripti bio i nekoliko puta veći od stvarnog prenosa.
    """
    skripta = b"window.__x = '" + b"y" * 300_000 + b"';"
    strana = b"<html><head><title>S</title></head><body><h1>S</h1><script src='/s.js'></script></body></html>"
    with FakeSite(
        extra={
            "/": Response(strana),
            "/s.js": Response(
                skripta, headers={"content-type": "application/javascript", "content-encoding": "gzip"}
            ),
        }
    ) as site:
        snimak = snimi(site)
    assert snimak.network.bytes_by_type["script"] == len(gzip.compress(skripta))


def test_nemereni_odgovori_se_broje_a_ne_prećutkuju(snimak):
    assert snimak.network.unmeasured_responses == 0


def test_preusmerenja_se_ne_broje_kao_nemerena():
    with FakeSite(
        extra={
            "/": Response(b"", status=302, headers={"Location": "/kraj"}),
            "/kraj": Response(b"<html><h1>Kraj</h1></html>"),
        }
    ) as site:
        snimak = snimi(site)
    assert snimak.network.unmeasured_responses == 0
    assert snimak.dom.h1_count == 1


def test_timing_se_belezi(snimak):
    assert snimak.timing.reached == "load"
    assert snimak.timing.load_ms is not None and snimak.timing.load_ms > 0


# --------------------------------------------------------------------------- #
# DOM (§7.4, §7.5)
# --------------------------------------------------------------------------- #
def test_h1_se_broji_iz_nacrtane_strane(snimak):
    assert snimak.dom.h1_count == 0
    assert run_level(2, snimak)["seo.h1.missing"].status == "finding"


def test_alt_stanja_se_broje_odvojeno(snimak):
    """Tri stanja, ne dva (§7.4)."""
    assert snimak.dom.images_total == 11
    assert snimak.dom.images_without_alt_attr == 9
    assert snimak.dom.images_empty_alt == 1


def test_lenja_slika_se_meri_jer_se_skroluje_do_dna(snimak):
    """Bez skrola bi imala naturalWidth == 0 i tiho ispala iz merenja (§15, zamka 2)."""
    assert snimak.dom.images_unmeasured == 0
    assert any("lenja.png" in image.src for image in snimak.dom.oversized_images)


def test_predimenzionirane_slike_sa_procenjenim_viskom(snimak):
    assert len(snimak.dom.oversized_images) >= 4
    najgora = snimak.dom.oversized_images[0]
    assert najgora.ratio > 2.5
    assert najgora.natural[0] in (800, 900) and najgora.client[0] == 100
    assert najgora.est_waste_kb > 0
    assert run_level(2, snimak)["perf.img.oversized"].status == "finding"


def test_console_greske_se_broje(snimak):
    assert snimak.console.errors >= 4  # dva pageerror-a i dva console.error
    assert snimak.console.warnings >= 1
    assert snimak.console.samples


# --------------------------------------------------------------------------- #
# Prazan keš po domenu (§15, zamka 10)
# --------------------------------------------------------------------------- #
def test_drugi_prolaz_meri_isto_jer_je_kes_prazan():
    """Nov kontekst po domenu; inače drugi sajt sa istog CDN-a ispadne lakši."""
    with teski_sajt() as site:
        prvi = snimi(site)
        drugi = snimi(site)
    assert drugi.network.total_bytes == pytest.approx(prvi.network.total_bytes, rel=0.02)
    assert drugi.network.unmeasured_responses == 0


# --------------------------------------------------------------------------- #
# Zastoji — snimljeno na klinika.example: jedan odgovor čije telo nikad ne stigne
# je zauvek blokirao ceo prolaz. Sve ovde mora da se završi u roku.
# --------------------------------------------------------------------------- #
STRIM_STRANA = b"""<!doctype html><html lang="sr"><head><title>Strim</title></head>
<body><h1>Strana sa strimom</h1><script>fetch('/strim').then(r => r.text())</script></body></html>"""


def test_telo_koje_ne_stigne_je_nemereno_a_ne_zastoj():
    """Strim ili video koji se ne završi: `load` stigne, telo odgovora nikad."""
    import time

    cfg = load_config()
    cfg["browser"]["drain_timeout_s"] = 2
    with FakeSite(
        extra={
            "/": Response(STRIM_STRANA),
            "/strim": Response(b"x" * 10_000, headers={"content-type": "text/plain"}, stall=120),
        }
    ) as site:
        started = time.monotonic()
        snimak = snimi(site, cfg)
        trajanje = time.monotonic() - started

    assert trajanje < 20, f"nivo 2 je čekao telo strima {trajanje:.0f} s"
    assert snimak.status == "ok"
    assert snimak.dom.h1_count == 1, "ostatak merenja mora da preživi"
    assert snimak.network.unmeasured_responses >= 1, "strim je nemeren, ne nula bajtova"


def test_tvrdi_limit_po_domenu_prekida_nivo_2():
    """Poslednja odbrana: bilo koji zastoj koji još ne znamo ne sme da zaustavi prolaz."""
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
        snimak = snimi(site, cfg)
        trajanje = time.monotonic() - started

    assert trajanje < 15, f"tvrdi limit od 3 s nije poštovan: {trajanje:.0f} s"
    assert snimak.status == "failed"
    assert any("tvrdog limita" in e.detail for e in snimak.errors), snimak.errors


# --------------------------------------------------------------------------- #
# Formula za procenu viška (§7.5) — čista funkcija, bez browsera
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "transfer_kb, natural, client, expected",
    [
        (2150, [4000, 2667], [760, 507], 1838.0),  # primer iz §3.3: ≈ 1840 kB
        (100, [100, 100], [100, 100], 0.0),  # slika tačne veličine nema višak
        (0, [4000, 2667], [760, 507], 0.0),  # bez izmerenog prenosa nema procene
    ],
)
def test_procena_viska(transfer_kb, natural, client, expected):
    assert est_waste_kb(transfer_kb * 1024, natural, client) == pytest.approx(expected, abs=2.0)


def test_neizmerena_slika_ne_daje_negativan_visak():
    assert est_waste_kb(1000, [10, 10], [500, 500]) == 0.0


# --------------------------------------------------------------------------- #
# BUG-006: vreme učitavanja se meri dok niko drugi ne učitava
# --------------------------------------------------------------------------- #
def test_ucitavanja_razlicitih_sajtova_se_ne_preklapaju():
    """Tri sajta koja se učitavaju istovremeno dele vezu i produžavaju jedan drugom
    `load` do 4,6× (izmereno u prolazu nad 100 domena). Učitavanje do `load` zato
    ide jedno po jedno; skrol i čitanje DOM-a i dalje idu paralelno.
    """
    import time

    from skener.fetch.browser import capture_all

    trenuci: dict[str, dict[str, float]] = {}

    def strana(ime: str):
        def odgovor() -> Response:
            trenuci.setdefault(ime, {})["html"] = time.monotonic()
            return Response(b"<html><h1>Strana</h1><img src='/spora.png'></html>")

        return odgovor

    def slika(ime: str):
        def odgovor() -> Response:
            trenuci.setdefault(ime, {})["slika"] = time.monotonic()
            return Response(png(10, 10), headers={"content-type": "image/png"}, delay=1.0)

        return odgovor

    with FakeSite(extra={"/": strana("a"), "/spora.png": slika("a")}) as a, FakeSite(
        extra={"/": strana("b"), "/spora.png": slika("b")}
    ) as b:
        sajtovi = [
            SiteSnapshot(
                domain=s.base_url,
                pages=[PageSnapshot(url=s.base_url + "/", final_url=s.base_url + "/", status=200)],
                entry=Entry(requested_url=s.base_url + "/", final_url=s.base_url + "/", status=200),
            )
            for s in (a, b)
        ]
        cfg = load_config()
        cfg["browser"]["concurrency"] = 2
        asyncio.run(capture_all(sajtovi, cfg))

    prvi, drugi = sorted(trenuci.values(), key=lambda t: t["html"])
    # Slika prvog sajta kasni 1 s i drži njegov `load`; drugi sme da krene tek posle.
    assert drugi["html"] >= prvi["slika"] + 0.9, (
        f"drugi sajt je počeo {drugi['html'] - prvi['html']:.2f} s posle prvog, dok se prvi još učitavao"
    )


def test_prekid_posle_tvrdog_limita_ne_ostavlja_gresku_u_logu(caplog):
    """BUG-007: posle prekida Playwright-ova navigacija ostane bez čitaoca, pa asyncio
    kasnije prijavi „Future exception was never retrieved" — ERROR za nešto što nije kvar.
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
        snimak = snimi(site, cfg)
        gc.collect()

    assert snimak.status == "failed"
    zaostale = [r.getMessage() for r in caplog.records if r.name == "asyncio"]
    assert not zaostale, zaostale


def test_rukovalac_izuzetaka_se_vraca_posle_nivoa_2():
    """Nivo 2 utišava greške zatvorenih konteksta samo dok traje. Web worker živi dugo,
    pa njegova petlja posle nivoa 2 mora imati svoj rukovalac, a ne naš."""
    from skener.fetch.browser import capture_all

    def nas(loop, context):
        loop.default_exception_handler(context)

    async def glavni(site):
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(nas)
        fake = SiteSnapshot(
            domain=site.base_url,
            pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        )
        await capture_all([fake], load_config())
        return loop.get_exception_handler()

    with FakeSite() as site:
        assert asyncio.run(glavni(site)) is nas


def test_rukovalac_utisava_samo_zatvoren_kontekst():
    """Sve osim greške zatvorenog konteksta ide rukovaocu koji je bio pre nivoa 2."""
    from skener.fetch.browser import _tiho_za_zatvoren_kontekst

    class TargetClosedError(Exception):
        pass

    primljeno = []
    rukovalac = _tiho_za_zatvoren_kontekst(lambda _loop, context: primljeno.append(context))
    rukovalac(None, {"exception": TargetClosedError()})
    rukovalac(None, {"exception": ValueError("pravi kvar")})
    assert [type(c["exception"]).__name__ for c in primljeno] == ["ValueError"]


def test_stranica_koja_se_ne_otvara_je_failed_sa_razlogom():
    """Greška pri otvaranju koja nije istek (odbijena veza) → `failed`, ne pad."""
    from skener.fetch.browser import capture_all

    mrtav = SiteSnapshot(
        domain="http://127.0.0.1:1",
        pages=[PageSnapshot(url="http://127.0.0.1:1/", final_url="http://127.0.0.1:1/", status=200)],
        entry=Entry(requested_url="http://127.0.0.1:1/", final_url="http://127.0.0.1:1/", status=200),
    )
    cfg = load_config()
    cfg["net"]["allowed_private"] = ["127.0.0.1:1"]  # da pukne odbijena veza, a ne zaštita adresa
    snimak = asyncio.run(capture_all([mrtav], cfg))["http://127.0.0.1:1"]
    assert snimak.status == "failed"
    assert snimak.errors and snimak.errors[0].stage == "goto"
    assert "ERR_BLOCKED_BY_CLIENT" not in snimak.errors[0].detail


def test_sistemski_chromium_iz_konfiguracije_i_okruzenja(monkeypatch):
    from skener.fetch.browser import _launch_options

    cfg = load_config()
    monkeypatch.delenv("SKENER_CHROMIUM", raising=False)
    assert "executable_path" not in _launch_options(cfg)
    monkeypatch.setenv("SKENER_CHROMIUM", "/usr/bin/chromium")
    assert _launch_options(cfg)["executable_path"] == "/usr/bin/chromium"
    cfg["browser"]["executable_path"] = "/opt/chrome"
    assert _launch_options(cfg)["executable_path"] == "/opt/chrome", "fajl ima prednost"
