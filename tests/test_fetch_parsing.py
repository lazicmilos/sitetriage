"""Parsiranje robots.txt, sitemapa i HTML-a. Čiste funkcije, bez mreže (§12.1)."""

from __future__ import annotations

import gzip
import tracemalloc

import pytest

from sitetriage.config import get, load_config
from sitetriage.fetch import robots, sitemap
from sitetriage.fetch.page import STUB_MAX_TEXT, build, internal_links, redirect_stub

# --------------------------------------------------------------------------- #
# robots.txt (§4.3)
# --------------------------------------------------------------------------- #
ROBOTS = """
# komentar
User-agent: AhrefsBot
Disallow: /

User-agent: *
Crawl-delay: 2
Disallow: /admin
Disallow: /*.pdf$
Allow: /admin/javno
Disallow:

Sitemap: https://d.rs/sitemap_index.xml
"""


def test_cita_samo_zvezdicu_i_globalne_sitemape():
    rules = robots.parse(ROBOTS)
    assert rules.disallow == ("/admin", "/*.pdf$")
    assert rules.allow == ("/admin/javno",)
    assert rules.crawl_delay == 2.0
    assert rules.sitemaps == ("https://d.rs/sitemap_index.xml",)


@pytest.mark.parametrize(
    "path, allowed",
    [
        ("/", True),
        ("/o-nama", True),
        ("/admin", False),
        ("/admin/tajno", False),
        ("/admin/javno", True),  # Allow sa dužim poklapanjem pobeđuje
        ("/admin/javno/x", True),
        ("/uputstvo.pdf", False),  # $ anker
        ("/uputstvo.pdf?v=2", True),  # ne završava se na .pdf
        ("https://d.rs/admin/tajno", False),  # pun URL, ne samo putanja
    ],
)
def test_poklapanje_prefiksa_sa_zvezdicom_i_dolarom(path, allowed):
    assert robots.allows(robots.parse(ROBOTS), path) is allowed


def test_prazan_robots_dozvoljava_sve():
    assert robots.allows(robots.parse(None), "/bilo/sta") is True
    assert robots.parse("").disallow == ()


def test_disallow_bez_vrednosti_ne_blokira_nista():
    rules = robots.parse("User-agent: *\nDisallow:\n")
    assert rules.disallow == ()
    assert robots.allows(rules, "/bilo/sta") is True


def test_pravila_drugog_bota_se_ne_primenjuju_na_nas():
    rules = robots.parse("User-agent: Googlebot\nDisallow: /tajno\n")
    assert robots.allows(rules, "/tajno") is True


def test_zajednicka_grupa_za_vise_agenata():
    rules = robots.parse("User-agent: Googlebot\nUser-agent: *\nDisallow: /tajno\n")
    assert robots.allows(rules, "/tajno") is False


# --------------------------------------------------------------------------- #
# sitemap (§4.4)
# --------------------------------------------------------------------------- #
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
INDEX = f'<sitemapindex {NS}><sitemap><loc>https://d.rs/s1.xml</loc></sitemap></sitemapindex>'.encode()
URLSET = f'<urlset {NS}><url><loc>https://d.rs/a</loc></url><url><loc>https://d.rs/b</loc></url></urlset>'.encode()


# Granica iz sitetriage.toml (`sitemap.max_kb`), ne iz koda.
MAX = get(load_config(), "sitemap.max_kb") * 1024


def parse(data: bytes | None, max_bytes: int = MAX):
    return sitemap.parse(data, max_bytes=max_bytes)


def test_prepoznaje_index_i_urlset():
    assert parse(INDEX) == ("index", ["https://d.rs/s1.xml"])
    assert parse(URLSET) == ("urlset", ["https://d.rs/a", "https://d.rs/b"])


def test_podrzava_gzip():
    assert parse(gzip.compress(URLSET))[1] == ["https://d.rs/a", "https://d.rs/b"]


def test_prazan_red_pre_xml_deklaracije_se_trpi():
    """WordPress dodatak koji ispiše prazan red pre `<?xml` ne briše mapu sajta (BUG-028)."""
    assert parse(b'\n<?xml version="1.0" encoding="UTF-8"?>' + INDEX)[0] == "index"


@pytest.mark.parametrize("data", [None, b"", b"<html>404</html>", b"{ nije xml }", b"\x1f\x8b pokvaren gzip"])
def test_smece_ne_ruši_parser(data):
    kind, urls = parse(data)
    assert kind == "unknown" and urls == []


def test_prevelik_sitemap_se_odbija():
    """Granica poverenja: sadržaj je sa tuđeg servera (§4.4). Prevelika mapa nije „nije mapa"."""
    huge = b"<urlset>" + b"<url><loc>https://d.rs/a</loc></url>" * 400_000 + b"</urlset>"
    assert len(huge) > MAX
    assert parse(huge) == ("too_large", [])


def _urlset_tacno(velicina: int) -> bytes:
    """Ispravan urlset od tačno `velicina` bajtova: razmaci pre zatvarajućeg taga."""
    pocetak, kraj = URLSET[: -len(b"</urlset>")], b"</urlset>"
    return pocetak + b" " * (velicina - len(pocetak) - len(kraj)) + kraj


@pytest.mark.parametrize("sazeto", [False, True], ids=["xml", "xml.gz"])
@pytest.mark.parametrize(
    "visak, kind",
    [
        pytest.param(0, "urlset", id="gv-tacno-granica"),
        pytest.param(1, "too_large", id="gv-granica-plus-1"),
    ],
)
def test_gv_granica_mape_vazi_i_posle_raspakivanja(sazeto, visak, kind):
    granica = 4096
    data = _urlset_tacno(granica + visak)
    assert len(data) == granica + visak
    assert parse(gzip.compress(data) if sazeto else data, max_bytes=granica)[0] == kind


def test_pg_gzip_bomba_u_mapi_ne_raspakuje_se_do_kraja():
    """`.xml.gz` od ~50 kB koji je raspakovan 50 MB: memorija prati granicu, ne raspakovanu veličinu."""
    bomba = gzip.compress(b"<urlset>" + b" " * 50 * 1024 * 1024, compresslevel=9)
    assert len(bomba) < 100 * 1024
    granica = 1024 * 1024
    tracemalloc.start()
    try:
        rezultat = parse(bomba, max_bytes=granica)
        _, vrh = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert rezultat == ("too_large", [])
    assert vrh < 4 * granica, f"vrh memorije {vrh} B za granicu od {granica} B"


def test_gzip_od_vise_delova_se_cita_ceo():
    """`cat a.gz b.gz` je ispravan gzip; `gzip.decompress` ga je čitao ceo, pa i dalje mora."""
    pola = len(URLSET) // 2
    data = gzip.compress(URLSET[:pola]) + gzip.compress(URLSET[pola:])
    assert parse(data)[1] == ["https://d.rs/a", "https://d.rs/b"]


def test_skracen_gzip_mape_nije_mapa():
    """Gzip prekinut na pola (tuđ server zatvorio vezu) daje ono što je raspakovano, a to nije XML."""
    assert parse(gzip.compress(URLSET * 50)[:40]) == ("unknown", [])


def test_uzorkovanje_je_deterministicko_i_grupisano():
    """§4.4: round-robin po grupama, da ne dobiješ osam blog postova."""
    urls = [
        *[f"https://d.rs/blog/{i}" for i in range(20)],
        "https://d.rs/usluge/a",
        "https://d.rs/usluge/b",
        "https://d.rs/o-nama",
    ]
    picked = sitemap.sample("https://d.rs/", urls, 4)
    assert picked == ["https://d.rs/", "https://d.rs/blog/0", "https://d.rs/usluge/a", "https://d.rs/o-nama"]
    # Isti ulaz u drugom redosledu daje isti uzorak — inače nijedan test nema smisla.
    assert sitemap.sample("https://d.rs/", list(reversed(urls)), 4) == picked


def test_uzorkovanje_ne_duplira_pocetnu():
    picked = sitemap.sample("https://d.rs/", ["https://d.rs/", "https://d.rs/a"], 8)
    assert picked == ["https://d.rs/", "https://d.rs/a"]


def test_uzorkovanje_preskace_tudje_domene():
    """Sitemap je tuđ sadržaj: strani host iz njega ne sme da troši budžet ovog domena."""
    urls = ["https://drugi.rs/a", "https://www.d.rs/usluge", "https://d.rs/o-nama"]
    picked = sitemap.sample("https://d.rs/", urls, 8)
    assert picked == ["https://d.rs/", "https://d.rs/o-nama", "https://www.d.rs/usluge"]


def test_uzorkovanje_postuje_velicinu():
    urls = [f"https://d.rs/g{i}/x" for i in range(50)]
    assert len(sitemap.sample("https://d.rs/", urls, 8)) == 8


# --------------------------------------------------------------------------- #
# HTML → PageSnapshot (§3.2)
# --------------------------------------------------------------------------- #
HTML = """<!doctype html><html lang="sr-Latn-RS">
<head><title>  Naslov   sajta </title>
<meta name="Description" content="Opis  sajta">
<meta property="og:title" content="OG naslov">
<meta name="og:image" content="https://d.rs/s.jpg">
<link rel="canonical" href="/usluge/?utm_source=fb">
<link rel="alternate" hreflang="en" href="/en/">
</head><body><h1>A</h1><h1>B</h1>
<script>var x = "nevidljivo";</script><style>.a{color:red}</style>
<p>Vidljiv tekst sa čćšžđ.</p>
<a href="/o-nama">o nama</a><a href="https://drugi.rs/x">van</a><a href="#vrh">vrh</a>
</body></html>"""


def test_gradi_snapshot_iz_html_a():
    page = build(
        "https://d.rs/",
        final_url="https://d.rs/",
        status=200,
        headers={"Content-Encoding": "gzip", "X-Nebitno": "1"},
        body=HTML.encode(),
        keep_raw_html=True,
    )
    assert page.title == "Naslov sajta"
    assert page.meta_description == "Opis sajta"
    assert page.og.title == "OG naslov"
    assert page.og.image == "https://d.rs/s.jpg"  # `name=` umesto `property=` se i dalje čita
    assert page.canonical == "/usluge/?utm_source=fb"
    assert page.canonical_normalized == "https://d.rs/usluge"  # normalizovan pre poređenja
    assert page.lang == "sr-Latn-RS"
    assert page.hreflang == ["en"]
    assert page.h1_count_raw == 2
    assert page.headers == {"content-encoding": "gzip"}  # samo relevantna zaglavlja


def test_tekst_izbacuje_script_i_style():
    page = build("https://d.rs/", final_url=None, status=200, body=HTML.encode())
    assert "nevidljivo" not in page.text_sample
    assert "color:red" not in page.text_sample
    assert "Vidljiv tekst sa čćšžđ." in page.text_sample


def test_sirovi_html_se_cuva_samo_kad_se_trazi():
    body = HTML.encode()
    assert build("https://d.rs/", final_url=None, status=200, body=body).raw_html is None
    assert build("https://d.rs/", final_url=None, status=200, body=body, keep_raw_html=True).raw_html


def test_prazno_telo_ne_ruši_parser():
    page = build("https://d.rs/", final_url=None, status=500, body=None)
    assert page.status == 500 and page.html_bytes == 0 and page.title is None


def test_dekodira_windows_1250_iz_meta_oznake():
    """Pogrešno dekodiranje pokvari brojanje dijakritika, a od njega zavisi §5.1."""
    body = '<html><head><meta charset="windows-1250"></head><body>čćšžđ</body></html>'.encode("windows-1250")
    assert "čćšžđ" in build("https://d.rs/", final_url=None, status=200, body=body).text_sample


def test_interni_linkovi_bez_fragmenata_i_stranih_hostova():
    assert internal_links(HTML, "https://d.rs/") == ["https://d.rs/o-nama"]


# --------------------------------------------------------------------------- #
# BUG-022: strana bez teksta koja samo preusmerava je skok, kao HTTP preusmerenje
# --------------------------------------------------------------------------- #
def _stub(telo: str, tekst: str = "") -> object:
    html = f"<html><head>{telo}</head><body>{tekst}</body></html>"
    body = html.encode()
    return build("https://d.rs/", final_url="https://d.rs/", status=200, body=body, keep_raw_html=True)


@pytest.mark.parametrize(
    "telo, ocekivano",
    [
        pytest.param(
            "<script>location.replace('/uskoro/')</script>", "https://d.rs/uskoro/", id="tab-js-replace"
        ),
        pytest.param('<script>window.location.href = "https://www.d.rs/novo"</script>', "https://www.d.rs/novo",
                     id="tab-js-href-www"),
        pytest.param(
            """<meta http-equiv="Refresh" content="0; URL='/sr/'">""",
            "https://d.rs/sr/",
            id="tab-meta-refresh",
        ),
        pytest.param("<script>location.href = 'https://drugi.rs/'</script>", None, id="tab-tudji-sajt"),
        pytest.param('<meta http-equiv="refresh" content="30">', None, id="tab-refresh-bez-adrese"),
        pytest.param("<script>location.href = '/'</script>", None, id="tab-ista-strana"),
        pytest.param("<script>if (location.href == '/x') go()</script>", None, id="tab-poredjenje-nije-skok"),
        pytest.param("<script>location.assign(adresa)</script>", None, id="tab-promenljiva"),
    ],
)
def test_strana_koja_samo_preusmerava(telo, ocekivano):
    assert redirect_stub(_stub(telo)) == ocekivano


@pytest.mark.parametrize(
    "znakova, ocekivano",
    [
        pytest.param(STUB_MAX_TEXT, "https://d.rs/uskoro/", id="gv-tekst-na-granici"),
        pytest.param(STUB_MAX_TEXT + 1, None, id="gv-tekst-preko-granice"),
    ],
)
def test_strana_sa_tekstom_nije_stub(znakova, ocekivano):
    """Ista naredba na pravoj strani je uslovna ili na klik."""
    page = _stub("<script>location.replace('/uskoro/')</script>", "x" * znakova)
    assert page.text_length == znakova
    assert redirect_stub(page) == ocekivano
