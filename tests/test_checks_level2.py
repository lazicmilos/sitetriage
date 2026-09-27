"""Provere nivoa 2 (§7.3). Isti troje: pozitivan, negativan, `unknown` (§12.3)."""

from __future__ import annotations

import pytest
from factories import clean_browser, findings, run_level, statuses

from skener.checks import registry
from skener.config import load_config
from skener.fetch.browser import network_conditions, network_profile
from skener.messages import LANGS, reason, render
from skener.models import DomStats, NetworkStats, OversizedImage, TimingStats

LEVEL2_IDS = sorted(s.check_id for s in registry.REGISTRY.values() if s.level == 2)


def test_cista_stranica_nema_nijedan_nalaz():
    results = run_level(2, clean_browser())
    assert findings(results) == set()
    assert set(statuses(results).values()) == {"ok"}


def test_pokrivene_su_sve_registrovane_provere():
    assert sorted(run_level(2, clean_browser())) == LEVEL2_IDS


POZITIVNI = {
    "perf.page.weight": lambda b: (
        setattr(b.network, "bytes_at_load", 25_000_000),
        setattr(b.network, "total_bytes", 25_000_000),
    ),
    "perf.request.count": lambda b: (
        setattr(b.network, "requests_at_load", 175),
        setattr(b.network, "request_count", 175),
    ),
    "perf.load.time": lambda b: setattr(b.timing, "load_ms", 9_000),
    "seo.h1.missing": lambda b: setattr(b.dom, "h1_count", 0),
    "seo.h1.multiple": lambda b: setattr(b.dom, "h1_count", 5),
    "a11y.img.alt.missing": lambda b: setattr(
        b, "dom", DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=0)
    ),
    "perf.img.oversized": lambda b: setattr(
        b.dom,
        "oversized_images",
        [
            OversizedImage(
                src=f"https://cist.rs/s{i}.jpg",
                natural=[4000, 2667],
                client=[760, 507],
                ratio=5.26,
                est_waste_kb=600,
            )
            for i in range(3)
        ],
    ),
    "qa.console.errors": lambda b: setattr(b.console, "errors", 5),
}


@pytest.mark.parametrize("check_id", LEVEL2_IDS)
def test_pozitivan_nalaz(check_id):
    browser = clean_browser()
    POZITIVNI[check_id](browser)
    result = run_level(2, browser)[check_id]
    assert result.status == "finding", f"{check_id}: očekivan nalaz, dobijeno {result.status}"
    found = result.findings[0]
    assert any(isinstance(v, (int, float)) for v in found.evidence.values())
    for lang in LANGS:
        assert "{" not in render(found, lang).client and "{" not in render(found, lang).tech
    assert found.level == 2


# --------------------------------------------------------------------------- #
# Stepenasti pragovi: jedan nalaz po proveri, najviša ozbiljnost koja važi (§7.3)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "total_bytes, expected",
    [
        # Granične vrednosti (trotačkasto) za pragove kalibrisane nad 60 pravih sajtova:
        # medijana 2,8 MB, p75 5,2 MB, p90 8,1 MB prenetih bajtova bez videa
        # (docs/izvestaj-testiranja-2.md).
        pytest.param(1_000_000, None, id="ke-lagana"),
        pytest.param(2_999_999, None, id="gv-3MB-minus"),
        pytest.param(3_000_000, None, id="gv-3MB"),
        pytest.param(3_000_001, "medium", id="gv-3MB-plus"),
        pytest.param(4_999_999, "medium", id="gv-5MB-minus"),
        pytest.param(5_000_000, "medium", id="gv-5MB"),
        pytest.param(5_000_001, "high", id="gv-5MB-plus"),
        pytest.param(7_999_999, "high", id="gv-8MB-minus"),
        pytest.param(8_000_000, "high", id="gv-8MB"),
        pytest.param(8_000_001, "critical", id="gv-8MB-plus"),
        pytest.param(22_100_000, "critical", id="ke-najteza-izmerena"),
    ],
)
def test_tezina_stranice_stepenasto(total_bytes, expected):
    browser = clean_browser()
    browser.network.bytes_at_load = total_bytes
    result = run_level(2, browser)["perf.page.weight"]
    if expected is None:
        assert result.status == "ok"
    else:
        assert len(result.findings) == 1, "ne tri nalaza za istu stranicu (§7.3)"
        assert result.findings[0].severity == expected


@pytest.mark.parametrize("count, expected", [(50, None), (120, "medium"), (175, "high")])
def test_broj_zahteva_stepenasto(count, expected):
    browser = clean_browser()
    browser.network.requests_at_load = count
    result = run_level(2, browser)["perf.request.count"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


@pytest.mark.parametrize("load_ms, expected", [(2_000, None), (5_000, "medium"), (9_000, "high")])
def test_vreme_ucitavanja_stepenasto(load_ms, expected):
    browser = clean_browser()
    browser.timing.load_ms = load_ms
    result = run_level(2, browser)["perf.load.time"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


def test_jedan_izvor_brzine_za_recenicu_i_merenje():
    """Z-30: brzina iz `[network_profile]` ide i u Chromium i u rečenice; drugog ključa nema."""
    cfg = load_config()
    assert "mobile_speed_mbps" not in cfg["thresholds"]["perf"]
    cfg["network_profile"]["download_mbps"] = 9.6
    profil = network_profile(cfg)
    assert network_conditions(profil)["downloadThroughput"] == 1_200_000, "CDP prima bajtove u sekundi"
    browser = clean_browser(network_profile=profil)
    browser.network.bytes_at_load = 20_000_000
    browser.timing.load_ms = 9_000
    ctx = registry.Context(domain=browser.domain, industry="ostalo", config=cfg)
    nalazi = {r.check_id: r.findings[0] for r in registry.run(2, browser, ctx) if r.status == "finding"}
    assert nalazi["perf.page.weight"].evidence["brzina"] == nalazi["perf.load.time"].evidence["brzina"] == 9.6


@pytest.mark.parametrize("reached, load_ms", [("load", 9_000), ("timeout", None)])
def test_vreme_bez_mreznog_profila_je_unknown(reached, load_ms):
    """Snimak bez profila meren je na stvarnoj vezi: rečenica o simuliranoj vezi ne bi bila tačna."""
    browser = clean_browser(network_profile=None)
    browser.timing = TimingStats(load_ms=load_ms, reached=reached)
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "unknown" and "bez mrežnog profila" in reason(result.reason)


# --------------------------------------------------------------------------- #
# §7.4 — tri stanja alt atributa, ne dva
# --------------------------------------------------------------------------- #
def test_prazan_alt_nije_greska():
    """`alt=""` je ispravan način da se označi dekorativna slika (§15, zamka 1).

    Alat koji ga prijavljuje kaže klijentu da je pokvareno ono što je urađeno
    kako treba — i ti to pošalješ u mejlu.
    """
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_without_alt_attr=0, images_empty_alt=20)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


def test_evidence_razlikuje_nema_atributa_od_praznog():
    """§12.4, ordinacija.example: dokaz mora da kaže 28/30 i da razlikuje stanja."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=2)
    evidence = run_level(2, browser)["a11y.img.alt.missing"].findings[0].evidence
    assert evidence["bez_alta"] == 28
    assert evidence["ukupno"] == 30
    assert evidence["prazan_alt"] == 2


def test_malo_slika_ne_pravi_nalaz():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=4, images_without_alt_attr=4)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


@pytest.mark.parametrize(
    "industry, expected",
    [("ostalo", "low"), ("hotel", "low"), ("zdravstvo", "medium"), ("institucija", "medium")],
)
def test_ozbiljnost_alta_zavisi_od_delatnosti(industry, expected):
    """Zdravstvo i institucije imaju zakonsku izloženost po pristupačnosti (§7.4)."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=10, images_without_alt_attr=6)
    result = run_level(2, browser, industry=industry)["a11y.img.alt.missing"]
    assert result.findings[0].severity == expected


def test_visok_udeo_prelazi_u_high_bez_obzira_na_delatnost():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28)
    result = run_level(2, browser, industry="ostalo")["a11y.img.alt.missing"]
    assert result.findings[0].severity == "high"


# --------------------------------------------------------------------------- #
# `unknown` — merenje u koje nemaš poverenja gore je od merenja kojeg nema (§7.2)
# --------------------------------------------------------------------------- #
def test_bez_load_tezina_je_unknown():
    """Z-24: bez `load` mera „do load" je nepotpuna, pa ni težina od 20 MB nije tvrdnja."""
    browser = clean_browser()
    browser.timing.reached = "timeout"
    browser.network.total_bytes = browser.network.bytes_at_load = 20_000_000
    result = run_level(2, browser)["perf.page.weight"]
    assert result.status == "unknown" and result.reason.code == "load_incomplete"


def test_tezina_i_broj_zahteva_ne_broje_ono_sto_pocne_posle_load():
    """Posle `load` stižu analitika, chat i lenje slike: isti sajt je imao 179, pa 281 zahtev."""
    browser = clean_browser()
    browser.network.total_bytes = 20_000_000
    browser.network.request_count = 281
    rezultati = run_level(2, browser)
    assert rezultati["perf.page.weight"].status == "ok"
    assert rezultati["perf.request.count"].status == "ok"


def test_ukupno_posle_load_je_samo_u_tehnickoj_recenici():
    browser = clean_browser()
    browser.network.bytes_at_load = 6_000_000
    browser.network.total_bytes = 9_000_000
    nalaz = run_level(2, browser)["perf.page.weight"].findings[0]
    assert nalaz.severity == "high", "6 MB do load, a ne 9 MB ukupno"
    assert "prenosi 6 MB" in render(nalaz, "sr").client
    assert "9000000" in render(nalaz, "sr").tech


def test_previse_neizmerenih_odgovora_je_unknown():
    browser = clean_browser()
    browser.network = NetworkStats(
        request_count=40, requests_at_load=40, bytes_at_load=500_000, unmeasured_at_load=9
    )
    result = run_level(2, browser)["perf.page.weight"]
    assert result.status == "unknown"
    assert "nije izmereno" in reason(result.reason)


def test_neuspeo_browser_daje_unknown_svuda():
    browser = clean_browser(status="failed")
    results = run_level(2, browser)
    assert sorted(results) == LEVEL2_IDS
    assert set(statuses(results).values()) == {"unknown"}
    assert all(r.reason for r in results.values())


def test_timeout_bez_prekoracenja_praga_je_unknown_a_ne_ok():
    """Merenja posle timeouta su nepotpuna i provere to moraju da znaju (§7.1)."""
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    results = run_level(2, browser)
    assert results["perf.page.weight"].status == "unknown"
    assert results["perf.request.count"].status == "unknown"


def test_slike_su_unknown_kad_stranica_nije_dovrsila_ucitavanje():
    """Nula slika posle prekida ne znači da ih sajt nema, pa ni da su sve opisane."""
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    browser.dom = DomStats(h1_count=1, images_total=0)
    result = run_level(2, browser)["a11y.img.alt.missing"]
    assert result.status == "unknown" and "slike nisu prebrojane" in reason(result.reason)


def test_timeout_je_sam_po_sebi_nalaz_za_vreme_ucitavanja():
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "finding"
    assert result.findings[0].severity == "high"


def test_h1_je_unknown_kad_stranica_nije_dovrsila_ucitavanje():
    """Prazan h1 posle timeouta nije nalaz — h1 može da stigne kasnije (§6)."""
    browser = clean_browser()
    browser.dom.h1_count = 0
    browser.timing = TimingStats(load_ms=None, reached="timeout")
    assert run_level(2, browser)["seo.h1.missing"].status == "unknown"


def test_nula_predimenzioniranih_uz_nemerene_slike_je_unknown():
    """Bez ovoga ne znaš da li je „0 predimenzioniranih" nalaz ili neuspelo merenje (§3.3)."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_unmeasured=15)
    result = run_level(2, browser)["perf.img.oversized"]
    assert result.status == "unknown"
    assert "nije izmereno" in reason(result.reason)


def test_veliki_visak_bajtova_pali_nalaz_i_ispod_tri_slike():
    """Prag je ≥ 3 slike **ili** višak > 700 kB (§7.3)."""
    browser = clean_browser()
    browser.dom.oversized_images = [
        OversizedImage(
            src="https://cist.rs/hero.jpg",
            natural=[4000, 2667],
            client=[760, 507],
            ratio=5.26,
            est_waste_kb=1840,
        )
    ]
    assert run_level(2, browser)["perf.img.oversized"].status == "finding"


# --------------------------------------------------------------------------- #
# O-2: video se ne računa u prag težine — skida se koliko vreme merenja dozvoli
# --------------------------------------------------------------------------- #
def test_video_se_ne_racuna_u_prag_tezine():
    """Isti sajt je u jednom prolazu preneo 77 MB videa, a u drugom 39 MB."""
    browser = clean_browser()
    browser.network.bytes_at_load = 24_500_000
    browser.network.bytes_by_type_at_load = {"media": 22_000_000, "image": 2_000_000, "script": 500_000}
    assert run_level(2, browser)["perf.page.weight"].status == "ok"


def test_nalaz_tezine_pominje_video_posebno():
    browser = clean_browser()
    browser.network.bytes_at_load = 30_000_000
    browser.network.bytes_by_type_at_load = {"media": 8_000_000, "image": 21_000_000, "script": 1_000_000}
    nalaz = run_level(2, browser)["perf.page.weight"].findings[0]
    assert nalaz.severity == "critical", "22 MB bez videa je iznad 8 MB"
    assert nalaz.evidence["mb"] == 22.0
    assert nalaz.evidence["video_mb"] == 8.0
    assert nalaz.variant == "video"
    assert "video" in render(nalaz, "sr").client and "video" in render(nalaz, "en").client
