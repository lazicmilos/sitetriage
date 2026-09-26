"""Provere nivoa 1 (§5). Po proveri tri testa: pozitivan, negativan, `unknown` (§12.3).

Negativan je najvažniji — to je test protiv lažnih pozitiva, a lažni pozitivi su
jedina stvar koja alat za rangiranje pretvara u generator šuma (§1.2, U4).
"""

from __future__ import annotations

import copy

import pytest
from factories import clean_site, findings, run_level, statuses

from skener.checks import registry
from skener.messages import LANGS, reason, render
from skener.models import Entry, Soft404, Soft404Probe, Tls

LEVEL1_IDS = sorted(s.check_id for s in registry.REGISTRY.values() if s.level == 1)


# --------------------------------------------------------------------------- #
# Negativan: čist sajt ćuti. Jedan test pokriva svih 20 provera.
# --------------------------------------------------------------------------- #
def test_cist_sajt_nema_nijedan_nalaz():
    results = run_level(1, clean_site())
    assert findings(results) == set()
    assert set(statuses(results).values()) == {"ok"}


def test_cist_sajt_pokriva_sve_registrovane_provere():
    """Ako dodaš proveru a ne pokriješ je, ovo pada."""
    assert sorted(run_level(1, clean_site())) == LEVEL1_IDS


# --------------------------------------------------------------------------- #
# Pozitivan: jedna pokvarena stvar → tačno ta provera
# --------------------------------------------------------------------------- #
def _sve_stranice(site, **attrs):
    for page in site.pages:
        for key, value in attrs.items():
            setattr(page, key, value)


POZITIVNI = {
    "seo.canonical.missing": lambda s: setattr(s.home, "canonical", None),
    "seo.canonical.duplicate": lambda s: _sve_stranice(s, canonical_normalized="https://cist.rs/"),
    "seo.title.missing": lambda s: setattr(s.home, "title", "   "),
    "seo.title.duplicate": lambda s: _sve_stranice(s, title="Dobrodošli"),
    "seo.description.missing": lambda s: setattr(s.home, "meta_description", None),
    "seo.description.duplicate": lambda s: _sve_stranice(s, meta_description="Isti opis svuda."),
    "social.og.title.missing": lambda s: setattr(s.home.og, "title", None),
    "social.og.description.missing": lambda s: setattr(s.home.og, "description", None),
    "social.og.image.missing": lambda s: setattr(s.home.og, "image", None),
    "i18n.lang.missing": lambda s: setattr(s.home, "lang", None),
    "i18n.lang.invalid": lambda s: setattr(s.home, "lang", "zxx"),
    "i18n.lang.mismatch": lambda s: setattr(s.home, "lang", "en-US"),
    "infra.sitemap.missing": lambda s: (setattr(s.sitemap, "status", 404), s.sitemap.urls.clear()),
    "infra.robots.missing": lambda s: setattr(s.robots, "status", 404),
    "infra.soft404": lambda s: setattr(
        s,
        "soft404",
        Soft404(
            probes=[
                Soft404Probe(url="https://cist.rs/abc", status=200, text_sample="Dobrodošli"),
                Soft404Probe(url="https://cist.rs/abc.html", status=200, text_sample="Dobrodošli"),
            ]
        ),
    ),
    "perf.compression.missing": lambda s: (
        setattr(s.home, "headers", {}),
        setattr(s.home, "html_bytes", 120_000),
    ),
    "perf.redirect.chain": lambda s: setattr(
        s.entry,
        "redirect_chain",
        ["http://cist.rs/", "https://cist.rs/", "https://www.cist.rs/", "https://www.cist.rs/home"],
    ),
    "perf.html.size": lambda s: setattr(s.home, "html_bytes", 600 * 1024),
    "infra.tls.invalid": lambda s: setattr(s.entry, "tls", Tls(valid=False, error="certificate has expired")),
    "infra.unreachable": lambda s: (
        setattr(s, "entry", Entry("https://cist.rs/", error_kind="dns_nxdomain", error_detail="NXDOMAIN")),
        setattr(s, "entry_attempts", ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]),
    ),
}


@pytest.mark.parametrize("check_id", LEVEL1_IDS)
def test_pozitivan_nalaz(check_id):
    site = clean_site()
    POZITIVNI[check_id](site)
    result = run_level(1, site)[check_id]
    assert result.status == "finding", f"{check_id}: očekivan nalaz, dobijeno {result.status}"

    found = result.findings[0]
    assert found.evidence, "nalaz bez dokaza (§3.5)"
    assert any(isinstance(v, (int, float)) for v in found.evidence.values()), (
        f"{check_id}: dokaz mora da sadrži broj — „sajt je spor\" nije nalaz (§3.5)"
    )
    for lang in LANGS:
        poruka = render(found, lang)
        assert poruka.client and "{" not in poruka.client
        assert poruka.tech and "{" not in poruka.tech
    assert found.check_id == check_id and found.level == 1


@pytest.mark.parametrize("check_id", LEVEL1_IDS)
def test_pozitivan_ne_budi_ostale_provere(check_id):
    """Jedna pokvarena stvar sme da probudi svoju proveru, ne ceo registar."""
    site = clean_site()
    POZITIVNI[check_id](site)
    probudjene = findings(run_level(1, site))
    # `lang=zxx` legitimno pali i `invalid`; sve ostalo mora da pogodi tačno jednu.
    dozvoljeno = {check_id} | ({"i18n.lang.invalid"} if check_id == "i18n.lang.invalid" else set())
    assert probudjene <= dozvoljeno, f"{check_id} je probudio i: {probudjene - dozvoljeno}"


# --------------------------------------------------------------------------- #
# `unknown`: nedostaju podaci → razlog, ne pad i ne `ok` (§12.3, treći tip)
# --------------------------------------------------------------------------- #
UNKNOWN_SLUCAJEVI = {
    "home": (lambda s: s.pages.clear(), ["seo.canonical.missing", "seo.title.missing", "i18n.lang.missing"]),
    "pages": (
        lambda s: s.pages.__setitem__(slice(2, None), []),
        ["seo.canonical.duplicate", "seo.title.duplicate", "seo.description.duplicate"],
    ),
    "robots": (lambda s: setattr(s.robots, "status", None), ["infra.robots.missing"]),
    "sitemap": (lambda s: setattr(s.sitemap, "status", None), ["infra.sitemap.missing"]),
    "soft404": (lambda s: setattr(s, "soft404", Soft404(probes=[])), ["infra.soft404"]),
    "entry": (lambda s: setattr(s, "entry", None), ["infra.tls.invalid", "infra.unreachable"]),
}


@pytest.mark.parametrize("scenario", sorted(UNKNOWN_SLUCAJEVI))
def test_unknown_ima_razlog(scenario):
    mutate, expected_ids = UNKNOWN_SLUCAJEVI[scenario]
    site = clean_site()
    mutate(site)
    results = run_level(1, site)
    for check_id in expected_ids:
        result = results[check_id]
        assert result.status == "unknown", f"{check_id}: očekivan unknown, dobijeno {result.status}"
        assert result.reason, "unknown bez razloga je bug (§3.4)"


def test_prazan_domen_ne_ruši_nijednu_proveru():
    """Domen koji nije ni odgovorio mora da da 20 rezultata, ne izuzetak (§8.2)."""
    site = clean_site()
    site.pages.clear()
    site.entry = Entry(requested_url="https://cist.rs/", error_kind="dns_nxdomain", error_detail="NXDOMAIN")
    site.entry_attempts = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    site.robots.status = None
    site.sitemap.status = None
    site.soft404 = Soft404(probes=[])
    results = run_level(1, site)
    assert sorted(results) == LEVEL1_IDS
    assert results["infra.unreachable"].status == "finding"
    assert all(r.reason for r in results.values() if r.status == "unknown")


# --------------------------------------------------------------------------- #
# Granični slučajevi koje spec izričito imenuje
# --------------------------------------------------------------------------- #
def test_zxx_pada_u_invalid_a_ne_u_mismatch():
    """§12.4, hotel-planina.example: lang=zxx mora da padne u `invalid`."""
    site = clean_site()
    site.home.lang = "zxx"
    results = run_level(1, site)
    assert results["i18n.lang.invalid"].status == "finding"
    assert results["i18n.lang.mismatch"].status == "ok"


def test_mismatch_je_unknown_kad_je_teksta_premalo():
    """§5.1, tačka 1 — ujedno i signal za eskalaciju na nivo 2."""
    site = clean_site()
    site.home.lang = "en"
    site.home.text_sample = "Kratko."
    site.home.text_length = 7
    result = run_level(1, site)["i18n.lang.mismatch"]
    assert result.status == "unknown"
    assert "premalo teksta" in reason(result.reason)


def test_sadrzaj_bez_dijakritika_ne_pravi_mismatch():
    """Engleski od srpskog bez dijakritika ne razlikuješ — kad ne znaš, `ok` (§5.1)."""
    site = clean_site()
    site.home.lang = "en"
    site.home.text_sample = "Dobrodosli na sajt. Nudimo usluge i proizvode. " * 20
    site.home.text_length = len(site.home.text_sample)
    assert run_level(1, site)["i18n.lang.mismatch"].status == "ok"


def test_cirilica_pravi_mismatch():
    site = clean_site()
    site.home.lang = "de"
    site.home.text_sample = "Добродошли на сајт. Нудимо услуге и производе. " * 20
    site.home.text_length = len(site.home.text_sample)
    assert run_level(1, site)["i18n.lang.mismatch"].status == "finding"


def test_jedna_sonda_200_druga_404_nije_nalaz():
    """§5.2: jedna sonda može slučajno da pogodi postojeću adresu."""
    site = clean_site()
    site.soft404 = Soft404(
        probes=[
            Soft404Probe(url="https://cist.rs/abc", status=200),
            Soft404Probe(url="https://cist.rs/abc.html", status=404),
        ]
    )
    assert run_level(1, site)["infra.soft404"].status == "ok"


def test_soft404_belezi_slicnost_sa_pocetnom():
    """Sličnost ≥ 90 % je tvrd dokaz i mora da uđe u `evidence` (§5.2)."""
    site = clean_site()
    tekst = site.home.text_sample
    site.soft404 = Soft404(
        probes=[
            Soft404Probe(url="https://cist.rs/abc", status=200, text_sample=tekst),
            Soft404Probe(url="https://cist.rs/abc.html", status=200, text_sample=tekst),
        ]
    )
    evidence = run_level(1, site)["infra.soft404"].findings[0].evidence
    assert evidence["slicnost"] == 1.0
    assert evidence["tvrd_dokaz"] is True


def test_duplikat_trazi_razlicite_grupe_putanja():
    """Isti naslov na osam blog postova nije isto što i ceo sajt kao jedna strana (§5)."""
    site = clean_site()
    site.pages = [
        copy.deepcopy(site.home),
        *[
            p
            for p in (
                copy.deepcopy(site.pages[1]),
                copy.deepcopy(site.pages[1]),
                copy.deepcopy(site.pages[1]),
            )
        ],
    ]
    for index, page in enumerate(site.pages[1:], start=1):
        page.url = page.final_url = f"https://cist.rs/blog/{index}"
        page.title = "Isti naslov"
        page.canonical_normalized = f"https://cist.rs/blog/{index}"
    assert run_level(1, site)["seo.title.duplicate"].status == "ok"


def test_kompresija_se_ne_prijavljuje_za_mali_html():
    """Prag od 50 kB postoji da sitne strane ne prave šum (§5)."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 20_000
    assert run_level(1, site)["perf.compression.missing"].status == "ok"


# --------------------------------------------------------------------------- #
# BUG-003: status ≠ 200 nije isto što i „ne postoji". Samo 404 i 410 to tvrde;
# 401/403/429/5xx znače da je pristup odbijen, pa ne znamo. Klase ekvivalencije
# statusa: postoji / ne postoji / ne zna se.
# --------------------------------------------------------------------------- #
POSTOJI, NE_POSTOJI, NE_ZNA_SE = "ok", "finding", "unknown"

STATUSI_FAJLA = [
    pytest.param(200, POSTOJI, id="ke-postoji-200"),
    pytest.param(404, NE_POSTOJI, id="ke-ne-postoji-404"),
    pytest.param(410, NE_POSTOJI, id="ke-ne-postoji-410"),
    pytest.param(401, NE_ZNA_SE, id="ke-odbijeno-401"),
    pytest.param(403, NE_ZNA_SE, id="ke-odbijeno-403"),
    pytest.param(429, NE_ZNA_SE, id="ke-odbijeno-429"),
    pytest.param(500, NE_ZNA_SE, id="ke-greska-servera-500"),
    pytest.param(503, NE_ZNA_SE, id="ke-greska-servera-503"),
]


@pytest.mark.parametrize("status, ocekivano", STATUSI_FAJLA)
def test_robots_status_odredjuje_ishod(status, ocekivano):
    site = clean_site()
    site.robots.status = status
    rezultat = run_level(1, site)["infra.robots.missing"]
    assert rezultat.status == ocekivano
    if ocekivano == NE_ZNA_SE:
        assert str(status) in reason(rezultat.reason)


@pytest.mark.parametrize("status, ocekivano", STATUSI_FAJLA)
def test_sitemap_status_odredjuje_ishod(status, ocekivano):
    site = clean_site()
    site.sitemap.status = status
    if status != 200:
        site.sitemap.urls.clear()
    rezultat = run_level(1, site)["infra.sitemap.missing"]
    assert rezultat.status == ocekivano
    if ocekivano == NE_ZNA_SE:
        assert str(status) in reason(rezultat.reason)


def test_sitemap_200_bez_ijednog_url_a_je_nalaz():
    """Granična vrednost: fajl postoji, ali je prazan."""
    site = clean_site()
    site.sitemap.urls.clear()
    assert run_level(1, site)["infra.sitemap.missing"].status == NE_POSTOJI


def _sonde(domain: str, prva: int, druga: int) -> Soft404:
    return Soft404(
        probes=[
            Soft404Probe(url=f"https://{domain}/abc123", status=prva),
            Soft404Probe(url=f"https://{domain}/abc123.html", status=druga),
        ]
    )


@pytest.mark.parametrize(
    "prva, druga, ocekivano",
    [
        pytest.param(200, 200, NE_POSTOJI, id="tab-obe-200"),
        pytest.param(404, 404, POSTOJI, id="tab-obe-404"),
        pytest.param(410, 404, POSTOJI, id="tab-410-i-404"),
        pytest.param(200, 404, POSTOJI, id="tab-200-i-404"),
        pytest.param(403, 403, NE_ZNA_SE, id="tab-obe-odbijene"),
        pytest.param(200, 403, NE_ZNA_SE, id="tab-200-i-odbijena"),
        pytest.param(404, 503, NE_ZNA_SE, id="tab-404-i-greska"),
        pytest.param(429, 429, NE_ZNA_SE, id="tab-obe-429"),
    ],
)
def test_soft404_tabela_odlucivanja(prva, druga, ocekivano):
    """Tabela odlučivanja nad statusima dve sonde (§5.2); `NE_POSTOJI` ovde znači nalaz."""
    site = clean_site()
    site.soft404 = _sonde(site.domain, prva, druga)
    assert run_level(1, site)["infra.soft404"].status == ocekivano


def test_blokiran_sajt_ne_dobija_nalaze_iz_odbijenih_zahteva():
    """BUG-003, snimljeno: ceo sajt vraća 403 „Checking your browser before accessing"."""
    site = clean_site()
    site.robots.status = 403
    site.sitemap.status = 403
    site.sitemap.urls.clear()
    site.soft404 = _sonde(site.domain, 403, 403)
    rezultati = run_level(1, site)
    for check_id in ("infra.robots.missing", "infra.sitemap.missing", "infra.soft404"):
        assert rezultati[check_id].status == NE_ZNA_SE, check_id
        assert "403" in reason(rezultati[check_id].reason)


# --------------------------------------------------------------------------- #
# O-3: nalaz o jeziku sme da tvrdi samo ono što je tačno
# --------------------------------------------------------------------------- #
def test_mismatch_poruka_ne_tvrdi_nista_o_pretrazivacima():
    """Google jezik stranice određuje iz sadržaja, `lang` atribut ne koristi.

    Tvrdnja „pretraživači ga nude pogrešnom tržištu" bila bi netačna u mejlu
    klijentu. Tačan i proverljiv argument je čitač ekrana.
    """
    site = clean_site()
    site.home.lang = "en-US"
    nalaz = run_level(1, site)["i18n.lang.mismatch"].findings[0]
    assert "pretraživač" not in render(nalaz).client.lower()
    assert "čitač" in render(nalaz).client.lower()
    assert nalaz.severity == "medium"


# --------------------------------------------------------------------------- #
# BUG-004: sajt dohvaćen preko http-a posle neuspelog https-a — sertifikat
# nije proveren, pa „ok" ne sme da stoji
# --------------------------------------------------------------------------- #
def test_tls_je_unknown_kad_je_https_pao_a_sajt_dohvacen_preko_http():
    from skener.models import SnapshotError

    site = clean_site()
    site.entry.requested_url = "http://cist.rs/"
    site.errors.append(SnapshotError("entry", "tls_handshake", "UNEXPECTED_EOF_WHILE_READING"))
    rezultat = run_level(1, site)["infra.tls.invalid"]
    assert rezultat.status == "unknown"
    assert "UNEXPECTED_EOF_WHILE_READING" in reason(rezultat.reason)
