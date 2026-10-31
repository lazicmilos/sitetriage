"""Bodovanje, rangiranje i eskalacija (§6, §9).

Brojevi u §9.4 nisu ilustracija nego tvrdnja o celom lancu: ozbiljnost → bodovi →
množilac po delatnosti → zbir → ključ rangiranja. Ako se bilo koja karika pomeri,
ovi testovi padaju.
"""

from __future__ import annotations

import pytest
from factories import CONFIG, clean_site, run_level

from sitetriage.models import CheckResult, Finding, Reason
from sitetriage.score import (
    build_report,
    escalation_reasons,
    level1_score,
    rank,
    select_for_level2,
    weigh,
)


def nalaz(check_id: str, category: str, severity: str, level: int = 1) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="finding",
        findings=[
            Finding(
                domain="d.rs",
                check_id=check_id,
                level=level,
                category=category,
                severity=severity,
                evidence={"broj": 1},
            )
        ],
    )


# Nalazi iz ispitnog skupa (§12.4), prepisani u proverljiv oblik.
ISPITNI_SKUP = {
    "restoran-centar.example": (
        "restaurant",
        [
            nalaz("perf.page.weight", "perf", "critical", level=2),
            nalaz("seo.canonical.missing", "seo", "high"),
        ],
    ),
    "restoran-ugao.example": (
        "restaurant",
        [
            nalaz("seo.canonical.missing", "seo", "high"),
            nalaz("seo.description.missing", "seo", "medium"),
            nalaz("social.og.title.missing", "social", "high"),
            nalaz("social.og.description.missing", "social", "medium"),
        ],
    ),
    "institucija.example": (
        "institution",
        [
            nalaz("seo.canonical.duplicate", "seo", "critical"),
            nalaz("infra.soft404", "infra", "high"),
            nalaz("seo.h1.missing", "seo", "high", level=2),
        ],
    ),
    "hotel-planina.example": (
        "hotel",
        [
            nalaz("seo.canonical.missing", "seo", "high"),
            nalaz("social.og.title.missing", "social", "high"),
            nalaz("infra.sitemap.missing", "infra", "medium"),
            nalaz("infra.robots.missing", "infra", "low"),
            nalaz("i18n.lang.invalid", "i18n", "medium"),
            nalaz("seo.h1.missing", "seo", "high", level=2),
        ],
    ),
}


def izvestaj(domain: str):
    industry, results = ISPITNI_SKUP[domain]
    site = clean_site(domain=domain, industry=industry)
    return build_report(site, results, CONFIG)


# --------------------------------------------------------------------------- #
# Množioci po delatnosti (§9.2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "category, severity, industry, expected",
    [
        ("perf", "critical", "restaurant", 60.0),  # 40 × 1,5
        ("seo", "high", "restaurant", 24.0),  # 20 × 1,2
        ("social", "high", "restaurant", 30.0),  # 20 × 1,5
        ("social", "high", "b2b", 14.0),  # 20 × 0,7 — b2b se ne deli u porukama
        ("a11y", "high", "healthcare", 30.0),  # 20 × 1,5
        ("infra", "medium", "hotel", 8.0),  # infra je svuda 1,0
        ("i18n", "medium", "hotel", 10.4),  # 8 × 1,3
        ("qa", "low", "hotel", 2.1),  # 3 × 0,7 — slab prodajni signal
    ],
)
def test_mnozioci(category, severity, industry, expected):
    finding = nalaz("x", category, severity).findings[0]
    assert weigh(finding, industry, CONFIG) == expected


# --------------------------------------------------------------------------- #
# Tačni parovi iz §9.4
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "domain, max_weight, total",
    [
        ("restoran-centar.example", 60.0, 84.0),
        ("restoran-ugao.example", 30.0, 75.6),
        ("institucija.example", 40.0, 80.0),
        ("hotel-planina.example", 30.0, 99.4),
    ],
)
def test_rank_key_iz_specifikacije(domain, max_weight, total):
    report = izvestaj(domain)
    assert report.rank_key == pytest.approx((max_weight, total))


def test_jedan_critical_nadjacava_cetiri_srednja_nalaza():
    """§9.4, prvi red: restoran-centar iznad restoran-ugla iako ima manje nalaza."""
    restoran, ugao = izvestaj("restoran-centar.example"), izvestaj("restoran-ugao.example")
    assert len(restoran.findings) < len(ugao.findings)
    assert rank([ugao, restoran])[0].domain == "restoran-centar.example"


def test_najtezi_nalaz_nadjacava_veci_zbir():
    """§9.4, drugi red — ceo smisao pravila.

    Hotel ima veći zbir (99,4 prema 80), ali institucija ima skuplji pojedinačni
    problem. Ako implementacija ovo obrne, greška je u `rank_key`, ne u pragovima.
    """
    institucija, hotel = izvestaj("institucija.example"), izvestaj("hotel-planina.example")
    assert hotel.total_score > institucija.total_score
    poredak = [r.domain for r in rank([hotel, institucija])]
    assert poredak == ["institucija.example", "hotel-planina.example"]


def test_rangiranje_dodeljuje_redne_brojeve():
    """Hotel i restoran-ugao su izjednačeni na 30; zbir ih razrešava (99,4 > 75,6)."""
    poredak = rank([izvestaj(d) for d in ISPITNI_SKUP])
    assert [r.rank for r in poredak] == [1, 2, 3, 4]
    assert [r.domain for r in poredak] == [
        "restoran-centar.example",  # (60; 84)
        "institucija.example",  # (40; 80)
        "hotel-planina.example",  # (30; 99,4)
        "restoran-ugao.example",  # (30; 75,6)
    ]


def test_nalazi_su_sortirani_po_tezini_i_tri_staju_u_mejl():
    report = izvestaj("hotel-planina.example")
    tezine = [f.weight for f in report.findings]
    assert tezine == sorted(tezine, reverse=True)
    assert len(report.top_findings) == 3
    assert report.top_findings[0].weight == 30.0


def test_ozbiljnost_se_ne_menja_posle_mnozenja():
    """Množilac menja broj bodova, ne ozbiljnost (§3.5)."""
    report = izvestaj("restoran-centar.example")
    najtezi = report.findings[0]
    assert najtezi.severity == "critical" and najtezi.weight == 60.0


def test_prazan_izvestaj_ima_nulu_a_ne_pad():
    report = build_report(clean_site(), [], CONFIG)
    assert report.rank_key == (0.0, 0.0)
    assert report.findings == [] and report.status == "scanned"


def test_status_partial_kad_ima_unknown():
    site = clean_site()
    results = [CheckResult(check_id="x", status="unknown", reason=Reason("load_not_measured"))]
    assert build_report(site, results, CONFIG).status == "partial"


def test_status_failed_kad_pocetna_nije_dohvacena():
    site = clean_site()
    site.pages.clear()
    assert build_report(site, [], CONFIG).status == "failed"


# --------------------------------------------------------------------------- #
# Politika eskalacije (§6)
# --------------------------------------------------------------------------- #
def test_cist_i_brz_sajt_ne_ide_na_nivo_2():
    site = clean_site()
    assert escalation_reasons(site, run_level(1, site).values(), CONFIG) == []


def test_prazan_sirovi_html_salje_na_nivo_2():
    """Ovo je institucija: sadržaj se crta iz JS-a, nivo 1 ne vidi ništa (§6)."""
    site = clean_site()
    site.home.text_length = 120
    site.home.h1_count_raw = 0
    razlozi = escalation_reasons(site, run_level(1, site).values(), CONFIG)
    assert len(razlozi) >= 2
    assert any(r.code == "no_h1_raw" for r in razlozi)


def test_prazan_sirovi_html_nije_nalaz_nego_signal():
    """Ako ga prijaviš kao nalaz, rekao si klijentu da nema h1 iako ga ima (§6)."""
    site = clean_site()
    site.home.text_length = 120
    site.home.h1_count_raw = 0
    nalazi = {cid for cid, r in run_level(1, site).items() if r.status == "finding"}
    assert "seo.h1.missing" not in nalazi
    assert not any(cid.startswith("seo.h1") for cid in nalazi)


def test_nalaz_ozbiljnosti_medium_salje_na_nivo_2():
    site = clean_site()
    site.home.meta_description = None  # medium
    razlozi = escalation_reasons(site, run_level(1, site).values(), CONFIG)
    assert any(r.code == "medium_finding" for r in razlozi)


def test_spora_pocetna_salje_na_nivo_2():
    """§6, poslednji red — jedini netrivijalan slučaj politike.

    `b2b-firma.example` je „čist SEO, spora stranica": nema nalaza nivoa 1, ima sadržaj u
    sirovom HTML-u, HTML mu nije velik. Po prva četiri uslova nikad ne bi stigao
    na nivo 2 i alat bi ga proglasio čistim.
    """
    site = clean_site()
    results = run_level(1, site)
    assert not any(r.status == "finding" for r in results.values()), "sajt je čist na nivou 1"

    site.entry.elapsed_ms = 2400
    razlozi = escalation_reasons(site, results.values(), CONFIG)
    assert len(razlozi) == 1
    assert razlozi[0].code == "slow_entry" and razlozi[0].evidence["ms"] == 2400


def test_veliki_html_salje_na_nivo_2():
    site = clean_site()
    site.home.html_bytes = 400_000
    assert any(r.code == "html_large" for r in escalation_reasons(site, [], CONFIG))


def test_domen_bez_pocetne_ne_ide_na_nivo_2():
    site = clean_site()
    site.pages.clear()
    assert escalation_reasons(site, [], CONFIG) == []


def test_gornji_limit_bira_najvise_skorove():
    """Bez limita dvonivojska arhitektura nema svrhu (§15, zamka 8).

    Među kandidatima koji već imaju jak nalaz nivoa 1 prvi idu najviši skorovi.
    """
    kandidati = []
    for i in range(5):
        site = clean_site(domain=f"d{i}.rs", industry="restaurant")
        severity = "critical" if i == 4 else "medium"
        kandidati.append((site, [nalaz("perf.page.weight", "perf", severity)]))

    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 2}}
    izabrani = select_for_level2(kandidati, config)
    assert len(izabrani) == 2
    assert izabrani[0].domain == "d4.rs", "prvo ide domen sa najvišim skorom nivoa 1"


def test_skor_nivoa_1_ne_broji_nalaze_nivoa_2():
    site = clean_site(industry="restaurant")
    results = [nalaz("seo.canonical.missing", "seo", "high")]
    assert level1_score(site, results, CONFIG) == 24.0


def test_limit_ne_odseca_sajt_kome_je_nivo_2_jedina_sansa():
    """BUG-005: izbor po skoru nivoa 1 uvek je odsecao sajtove sa skorom 0.

    Takav sajt je kandidat samo zbog signala koji se vide tek u browseru (spora
    početna, nema h1 u sirovom HTML-u). Ako ne ode na nivo 2, u izveštaju stoji
    kao „0 nalaza", a zapravo nije ni meren. Sajtovi koji već imaju nalaz nivoa 1
    bar imaju razlog za mejl.
    """
    kandidati = [
        (clean_site(domain=f"nalaz{i}.rs"), [nalaz("seo.description.missing", "seo", "medium")])
        for i in range(3)
    ]
    spor = clean_site(domain="spor.rs")
    spor.entry.elapsed_ms = 2400
    kandidati.append((spor, []))

    config = {**CONFIG, "escalation": {**CONFIG["escalation"], "max_level2": 2}}
    izabrani = [site.domain for site in select_for_level2(kandidati, config)]
    assert "spor.rs" in izabrani, f"izabrani: {izabrani}"
    assert len(izabrani) == 2
