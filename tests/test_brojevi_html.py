"""Z-28: brojevi u HTML izveštaju po pravilima jezika (O-11).

Skor, najteži nalaz, bodovi, trajanje, brzina i udeli idu kroz formatter jezika. Tehnička rečenica
i JSON dokaza ostaju mašinski zapis, kao CSV (Z-12), pa ih test ne gleda.
"""

from __future__ import annotations

import html
import re

import pytest

from skener.config import load_config
from skener.models import DomainReport, Finding, Reason, Unknown
from skener.report import html_out

# Decimalni broj, a ne verzija („2.0.0") ni IP adresa: bez tačke ili cifre sa strane.
DECIMALNI = re.compile(r"(?<![\d.])\d+\.\d+(?![\d.])")
NIJE_TEKST = re.compile(r'<(style|script|pre)\b.*?</\1>|<p class="tech">.*?</p>', re.DOTALL)


def tekst(stranica: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", NIJE_TEKST.sub(" ", stranica)))


def stranica(lang: str) -> str:
    nalaz = Finding(
        domain="d.rs",
        check_id="seo.title.missing",
        level=1,
        category="seo",
        severity="medium",
        evidence={"stranica": "https://d.rs/", "duzina_naslova": 0},
        weight=10.4,
    )
    izvestaji = [
        DomainReport(domain="d.rs", findings=[nalaz], total_score=99.4, max_finding_weight=10.4, rank=1),
        DomainReport(
            domain="e.rs",
            status="partial",
            partial_causes=["budget"],
            unknowns=[Unknown(check_id="infra.robots.missing", reason=Reason("requires.robots"))],
            rank=2,
        ),
        DomainReport(domain="f.rs", rank=3),
    ]
    return html_out.render(izvestaji, load_config(), duration_s=3.44, lang=lang)


@pytest.mark.parametrize("broj", ["99,4", "10,4", "3,4 s", "4,8 Mb/s", "0,6 MB/s", "33,3 %"])
def test_html_na_srpskom_nema_decimalnu_tacku_u_tekstu(broj):
    sadrzaj = tekst(stranica("sr"))
    assert not DECIMALNI.findall(sadrzaj)
    assert broj in sadrzaj


@pytest.mark.parametrize("broj", ["99.4", "10.4", "3.4 s", "4.8 Mb/s", "0.6 MB/s", "33.3 %"])
def test_html_na_engleskom_ima_decimalnu_tacku(broj):
    assert broj in tekst(stranica("en"))
