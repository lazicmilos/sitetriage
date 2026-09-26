"""Z-22: uzrok `partial`-a. Budžet i `unknown` su dva izlazna kriterijuma (§7), pa se broje posebno.

Budžet se meri među domenima koji rade, a `unknown` po proveri, među domenima na kojima je provera
pokrenuta: bez `failed`, `unreachable` i `excluded`, a za nivo 2 samo gde je nivo 2 radio.
"""

from __future__ import annotations

import jsonschema
from factories import clean_browser, clean_site
from test_json import SEMA

from skener import pipeline, store
from skener.config import load_config
from skener.models import Entry, to_jsonable
from skener.report import html_out
from skener.score import analyze, partial_shares


def _sajt(domain: str, *, budzet: bool = False, unknown: bool = False):
    site = clean_site(domain=domain)
    site.budget.exhausted = budzet
    if unknown:
        site.robots.status = 403  # iz toga se ne vidi da li robots.txt postoji
    return site


def _sajtovi():
    return [
        _sajt("cist.rs"),
        _sajt("budzet.rs", budzet=True),
        _sajt("nepoznato.rs", unknown=True),
        _sajt("oba.rs", budzet=True, unknown=True),
    ]


def _izvestaji():
    config = load_config()
    return {s.domain: analyze(s, config) for s in _sajtovi()}


def test_partial_zbog_budzeta_i_zbog_unknown_se_broje_posebno(tmp_path):
    izvestaji = _izvestaji()
    uzroci = {domen: r.partial_causes for domen, r in izvestaji.items()}
    assert uzroci == {
        "cist.rs": [],
        "budzet.rs": ["budget"],
        "nepoznato.rs": ["unknown"],
        "oba.rs": ["budget", "unknown"],
    }
    budzet, po_proveri = partial_shares(list(izvestaji.values()))
    assert budzet == 0.5
    assert po_proveri["infra.robots.missing"] == 0.5 and po_proveri["seo.title.missing"] == 0.0

    for site in _sajtovi():
        store.write_site(tmp_path, site)
    rezultat = pipeline.recheck(tmp_path, load_config())
    assert rezultat.summary["partial_budget"] == 2 and rezultat.summary["partial_unknown"] == 2
    assert rezultat.budget_share == 0.5 and rezultat.unknown_share["infra.robots.missing"] == 0.5
    jsonschema.validate(to_jsonable(rezultat), SEMA)


def test_udeo_unknown_ne_broji_domene_koji_ne_rade():
    config = load_config()
    ne_radi = clean_site(domain="ugasen.rs", pages=[])
    ne_radi.entry = Entry("https://ugasen.rs/", error_kind="dns_nxdomain")
    ne_radi.entry_attempts = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    nije_skeniran = clean_site(domain="zatvoren.rs", pages=[])
    nije_skeniran.entry.status = 403
    izvestaji = [
        analyze(_sajt("nepoznato.rs", unknown=True), config),
        analyze(_sajt("cist.rs"), config, browser=clean_browser(domain="cist.rs")),
        analyze(ne_radi, config),
        analyze(nije_skeniran, config),
    ]
    assert [r.status for r in izvestaji[2:]] == ["unreachable", "failed"]
    budzet, po_proveri = partial_shares(izvestaji)
    assert budzet == 0.0
    assert po_proveri["infra.robots.missing"] == 0.5, "samo dva domena rade"
    # Nivo 2 je radio samo na jednom domenu: imenilac je 1, a ne 2.
    assert po_proveri["perf.page.weight"] == 0.0


def test_provera_nivoa_2_bez_ijednog_domena_na_nivou_2_nema_udeo():
    _, po_proveri = partial_shares([analyze(_sajt("cist.rs"), load_config())])
    assert "perf.page.weight" not in po_proveri and "seo.title.missing" in po_proveri


def test_prazan_prolaz_nema_deljenja_nulom():
    assert partial_shares([]) == (0.0, {})


def test_html_prikazuje_oba_udela_po_jeziku():
    izvestaji = list(_izvestaji().values())[:3]  # jedan od tri zbog budžeta, jedan od tri zbog unknown
    sr = html_out.render(izvestaji, load_config())
    en = html_out.render(izvestaji, load_config(), lang="en")
    assert "Potrošen budžet: 33,3 % domena koji rade" in sr
    assert "<td>infra.robots.missing</td><td class=\"num\">33,3 %</td>" in sr
    assert "Budget spent: 33.3 % of working domains" in en
