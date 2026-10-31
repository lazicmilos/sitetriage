"""Ispitni skup iz §12.4 — izvršni oblik tabele iz specifikacije.

Za svaki domen se traži da je **očekivani skup podskup pronađenog**, a za
`klinika.example` dodatno da je pronađeni skup mali.

Pošteno upozorenje: snapshoti u `tests/fixtures/` su **ručno napisani**, nad
izmišljenim domenima pod `.example` (vidi `tests/make_fixtures.py`). Ovi testovi
zato tvrde da lanac provera radi kako treba nad opisanim stanjem — ne da je ijedan
pravi sajt u tom stanju. Za ovo drugo služi `pytest -m live` (vidi `tests/test_live.py`).
"""

from __future__ import annotations

import datetime as dt
import warnings
from pathlib import Path

import pytest

from sitetriage import store
from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.messages import LANGS, render
from sitetriage.models import SEVERITY_ORDER
from sitetriage.score import analyze, escalation_reasons, rank

FIXTURES = Path(__file__).parent / "fixtures"
MAX_STAROST_DANA = 90

# (delatnost, obavezni check_id-evi) — prepisano iz tabele u §12.4.
OCEKIVANO = {
    "institucija.example": ("institution", {"seo.canonical.duplicate", "infra.soft404", "seo.h1.missing"}),
    "hotel-planina.example": (
        "hotel",
        {
            "seo.canonical.missing",
            "social.og.title.missing",
            "infra.sitemap.missing",
            "infra.robots.missing",
            "i18n.lang.invalid",
            "seo.h1.missing",
        },
    ),
    "restoran-centar.example": ("restaurant", {"seo.canonical.missing", "perf.page.weight"}),
    "restoran-ugao.example": (
        "restaurant",
        {
            "seo.canonical.missing",
            "seo.description.missing",
            "social.og.title.missing",
            "social.og.description.missing",
        },
    ),
    "prodavnica.example": (
        "ecommerce",
        {"seo.h1.missing", "perf.page.weight", "perf.request.count"},
    ),
    "ordinacija.example": ("healthcare", {"i18n.lang.mismatch", "a11y.img.alt.missing"}),
    "b2b-firma.example": ("b2b", set()),
    "klinika.example": ("healthcare", set()),
}


def spec_config() -> dict:
    """Pragovi težine iz specifikacije (§7.3), ne kalibrisani.

    Ovaj skup proverava da lanac snapshot → provere → bodovi → rangiranje radi nad
    stanjem koje §12.4 opisuje. Kalibracija pragova nad pravim sajtovima ima svoje
    testove graničnih vrednosti; da ovde važe kalibrisani pragovi, svaka kalibracija
    bi „pokvarila" specifikaciju.
    """
    config = load_config()
    config["thresholds"]["perf"]["page_weight_mb"] = {"medium": 1.5, "high": 3.0, "critical": 8.0}
    return config


@pytest.fixture(scope="module")
def izvestaji():
    registry.load_all()
    config = spec_config()
    reports = {}
    for site, browser in store.read_all(FIXTURES):
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        reasons = escalation_reasons(site, registry.run(1, site, ctx), config)
        reports[site.domain] = analyze(site, config, browser=browser, escalation=reasons)
    return reports


def ids(report) -> set[str]:
    return {f.check_id for f in report.findings}


def test_svi_domeni_iz_tabele_postoje(izvestaji):
    assert set(izvestaji) == set(OCEKIVANO), "fixture-i i tabela iz §12.4 se razilaze"


@pytest.mark.parametrize("domain", sorted(OCEKIVANO))
def test_ocekivani_nalazi_su_podskup_pronadjenih(domain, izvestaji):
    industry, expected = OCEKIVANO[domain]
    report = izvestaji[domain]
    assert report.industry == industry
    assert expected <= ids(report), f"fali: {sorted(expected - ids(report))}"


@pytest.mark.parametrize("domain", sorted(OCEKIVANO))
def test_svaki_nalaz_ima_dokaz_i_recenicu(domain, izvestaji):
    for finding in izvestaji[domain].findings:
        assert finding.evidence, f"{finding.check_id}: nalaz bez dokaza (§3.5)"
        assert finding.weight > 0, f"{finding.check_id}: nalaz bez bodova"
        for lang in LANGS:
            assert "{" not in render(finding, lang).client, "rečenica nije popunjena vrednostima"


# --------------------------------------------------------------------------- #
# Dodatni uslovi iz kolone „Dodatno"
# --------------------------------------------------------------------------- #
def test_institucija_ide_na_nivo_2_i_nema_ijedan_i18n_nalaz(izvestaji):
    """`lang=sr` je ispravan — alat koji tu nešto prijavi laže klijentu."""
    report = izvestaji["institucija.example"]
    assert report.level2_ran, "sadržaj institucije se crta iz JS-a, mora na nivo 2"
    assert report.escalation_reasons
    assert not any(c.startswith("i18n.") for c in ids(report))


def test_hotel_planina_pada_u_invalid_a_ne_u_mismatch(izvestaji):
    nalazi = ids(izvestaji["hotel-planina.example"])
    assert "i18n.lang.invalid" in nalazi
    assert "i18n.lang.mismatch" not in nalazi, "lang=zxx nije pogrešan jezik, nego nikakav"


def test_restoran_centar_meri_preko_14_mb_i_daje_critical(izvestaji):
    report = izvestaji["restoran-centar.example"]
    tezina = next(f for f in report.findings if f.check_id == "perf.page.weight")
    assert tezina.severity == "critical"
    assert tezina.evidence["bajtova"] > 14_000_000
    assert tezina.evidence["mb"] > 14
    # Merenje preko mrežnih događaja, ne Performance API-ja (§7.2).
    assert tezina.evidence["bajtova"] != 2048


def test_prodavnica_ima_oko_175_zahteva(izvestaji):
    report = izvestaji["prodavnica.example"]
    zahtevi = next(f for f in report.findings if f.check_id == "perf.request.count")
    assert zahtevi.evidence["zahteva"] >= 150 and zahtevi.severity == "high"
    tezina = next(f for f in report.findings if f.check_id == "perf.page.weight")
    assert SEVERITY_ORDER[tezina.severity] >= SEVERITY_ORDER["medium"]


def test_ordinacija_dokaz_razlikuje_stanja_alt_atributa(izvestaji):
    """§12.4: dokaz mora reći 28/30 i razlikovati „nema atribut" od `alt=""`."""
    report = izvestaji["ordinacija.example"]
    alt = next(f for f in report.findings if f.check_id == "a11y.img.alt.missing")
    assert alt.evidence["bez_alta"] == 28
    assert alt.evidence["ukupno"] == 30
    assert alt.evidence["prazan_alt"] == 1
    assert alt.severity == "high", "udeo > 0,8 uz ≥ 15 slika prelazi u high (§7.4)"


def test_b2b_firma_nema_nijedan_seo_nalaz_a_ipak_stize_na_nivo_2(izvestaji):
    """Najvredniji test posle klinike (§12.4).

    Sajt bez nalaza nivoa 1 mora da stigne na nivo 2 preko petog uslova
    eskalacije — inače bi ga alat proglasio čistim.
    """
    report = izvestaji["b2b-firma.example"]
    seo = {c for c in ids(report) if c.startswith("seo.")}
    assert seo == set(), f"lažni pozitivi u SEO grupi: {sorted(seo)}"
    assert any(c.startswith("perf.") for c in ids(report))
    assert report.level2_ran
    assert any(razlog.code == "slow_entry" for razlog in report.escalation_reasons), (
        f"na nivo 2 je morao da stigne zbog sporog odgovora, a stigao je zbog: "
        f"{report.escalation_reasons}"
    )


def test_klinika_je_cista(izvestaji):
    """U4 iz §1.2 — najvažniji kriterijum i najlakše ga je izgubiti iz vida."""
    report = izvestaji["klinika.example"]
    assert len(report.findings) <= 2, f"lažni pozitivi: {sorted(ids(report))}"
    previsoki = [f.check_id for f in report.findings if SEVERITY_ORDER[f.severity] > SEVERITY_ORDER["medium"]]
    assert previsoki == [], f"čist sajt ne sme da ima nalaz iznad medium: {previsoki}"


def test_klinika_je_na_dnu_rangiranja(izvestaji):
    poredak = rank(list(izvestaji.values()))
    assert poredak[-1].domain == "klinika.example"
    assert poredak[0].domain == "restoran-centar.example"


def test_recheck_kroz_pipeline_daje_isto_rangiranje(izvestaji):
    """`izvestaji` ide starim putem iz `cmd_recheck`. Pipeline ne sme ništa da promeni."""
    from sitetriage import pipeline
    from sitetriage.models import to_jsonable

    stari = rank(list(izvestaji.values()))
    novi = pipeline.recheck(FIXTURES, spec_config()).ranked
    assert [to_jsonable(r) for r in novi] == [to_jsonable(r) for r in stari]


# --------------------------------------------------------------------------- #
# Fixture-i zastarevaju (§12.2)
# --------------------------------------------------------------------------- #
def test_fixture_starost_upozorava_a_ne_pada():
    """Kad neki sajt popravi canonical, test i dalje prolazi nad starim snimkom."""
    danas = dt.datetime.now(dt.UTC)
    stari = []
    for site, _ in store.read_all(FIXTURES):
        snimljeno = dt.datetime.strptime(site.fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.UTC
        )
        if (danas - snimljeno).days > MAX_STAROST_DANA:
            stari.append(f"{site.domain} ({(danas - snimljeno).days} dana)")
    if stari:
        warnings.warn(
            "Fixture-i su stariji od 90 dana; osveži ih sa `sitetriage record` i pogledaj git diff: "
            + ", ".join(stari),
            stacklevel=1,
        )
