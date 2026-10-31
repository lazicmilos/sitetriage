"""CLI i izveštaji od kraja do kraja (§10, §11)."""

from __future__ import annotations

import csv
import json

import pytest
from localserver import FakeSite, Response, html

from sitetriage import cli
from sitetriage.config import load_config
from sitetriage.inputs import InputError
from sitetriage.models import DomainReport, Finding
from sitetriage.report import csv_out, html_out
from sitetriage.score import rank


# --------------------------------------------------------------------------- #
# Ulazni CSV (§4.1): ovde samo ono što radi CLI — `--only`, log i poruka na izlazu.
# Čitanje same liste je u test_inputs.py.
# --------------------------------------------------------------------------- #
def test_only_filtrira(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("domain,industry\na.rs,hotel\nb.rs,hotel\n", encoding="utf-8")
    assert [r.domain for r in cli.read_domains(path, ["B.RS"])] == ["b.rs"]
    with pytest.raises(InputError, match="--only"):
        cli.read_domains(path, ["c.rs"])


def test_upozorenja_iz_liste_idu_u_log_sa_brojem_reda(tmp_path, caplog):
    path = tmp_path / "d.csv"
    path.write_text(
        "domain,industry\ninstitucija.example,institucija\nINSTITUCIJA.EXAMPLE,hotel\n", encoding="utf-8"
    )
    cli.read_domains(path)
    assert "red 3: domen se ponavlja" in caplog.text


def test_izuzeti_iz_konfiguracije_i_sa_komandne_linije(tmp_path):
    """Oba izvora važe; u izveštaju je samo broj izuzetih, bez imena."""
    with FakeSite() as prvi:
        host, port = prvi.address
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{prvi.base_url},ostalo\n", encoding="utf-8")
        iz_konfiguracije = tmp_path / "izuzeti.txt"
        iz_konfiguracije.write_text("# pisali 25.09.\nnekidrugi.rs\n", encoding="utf-8")
        sa_komandne_linije = tmp_path / "jos.txt"
        sa_komandne_linije.write_text(f"{host}\n", encoding="utf-8")
        config = tmp_path / "moj.toml"
        config.write_text(f'[operator]\nexclude_file = "{iz_konfiguracije.as_posix()}"\n', encoding="utf-8")
        out = tmp_path / "izlaz"
        argumenti = ["--config", str(config), "--exclude", str(sa_komandne_linije), "--level", "1"]
        assert cli.main(["scan", str(domains), "--out", str(out), *argumenti]) == 0
    assert prvi.requests == []
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["summary"]["excluded"] == 1
    stranica = (out / "index.html").read_text(encoding="utf-8")
    assert "Izuzeto na zahtev" in stranica and prvi.base_url not in stranica


def test_nepostojeci_fajl_sa_izuzetima_puca_razumljivo(tmp_path):
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institucija\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="fajl sa izuzetim domenima ne postoji"):
        cli.main(["scan", str(domains), "--out", str(tmp_path / "izlaz"), "--exclude", "nema.txt"])


def test_greska_u_listi_je_poruka_a_ne_traceback(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("sajt,industry\na.rs,hotel\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="red 1: nedostaje kolona `domain`"):
        cli.main(["scan", str(path), "--out", str(tmp_path / "izlaz")])


# --------------------------------------------------------------------------- #
# scan → recheck (§11.1)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def prolaz(tmp_path_factory):
    """Dva lokalna sajta: jedan uredan, jedan sa lažnim 404 i bez OG oznaka.

    Jedan prolaz za ceo modul: podizanje servera i pun scan traju, a svi testovi
    ispod gledaju isti rezultat.
    """
    tmp_path = tmp_path_factory.mktemp("prolaz")
    # `--config` se spaja preko sitetriage.toml; ovde gasimo pauze da testovi ne traju minut.
    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")

    with FakeSite() as cist, FakeSite(soft404=True, extra={"/": Response(html("Bez oznaka"))}) as los:
        domains = tmp_path / "domains.csv"
        domains.write_text(
            f"domain,industry,note\n{cist.base_url},hotel,\n{los.base_url},restoran,\n",
            encoding="utf-8",
        )
        out = tmp_path / "izvestaj"
        code = cli.main(
            ["scan", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )
        yield code, out, cist, los


def test_scan_pravi_sve_izlaze(prolaz):
    code, out, _cist, _los = prolaz
    assert code == 0
    assert (out / "index.html").is_file()
    assert (out / "findings.csv").is_file()
    assert (out / "summary.csv").is_file()
    assert list((out / "snapshots").glob("*/site.json")), "snapshoti se uvek pišu (§2.2)"


def test_scan_pise_json_po_semi(prolaz):
    import jsonschema
    from test_json import SEMA

    _code, out, _cist, _los = prolaz
    dokument = json.loads((out / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(dokument, SEMA)
    assert set(dokument["duration_s"]) == {"level1", "level2", "level2_light", "total"}
    assert dokument["environment"]["chromium"] is None, "nivo 2 nije radio (--level 1)"


def test_summary_ima_red_po_domenu(prolaz):
    _code, out, _cist, _los = prolaz
    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert set(rows[0]) == set(csv_out.SUMMARY_HEADER)
    assert {r["industry"] for r in rows} == {"hotel", "restoran"}
    assert [int(r["rank"]) for r in rows] == [1, 2]


def test_findings_ima_red_po_nalazu_sa_dokazom(prolaz):
    _code, out, _cist, _los = prolaz
    rows = list(csv.DictReader((out / "findings.csv").open(encoding="utf-8")))
    assert rows, "loš sajt mora da proizvede bar jedan nalaz"
    assert set(rows[0]) == set(csv_out.FINDINGS_HEADER)
    for row in rows:
        assert json.loads(row["evidence_json"]), "svaki nalaz nosi dokaz (§3.5)"
        assert row["message_client"] and "{" not in row["message_client"]


def test_recheck_daje_isti_rezultat_bez_ijednog_zahteva(prolaz, tmp_path):
    """Kalibracija bez ponovnog prolaza je cela poenta podele iz §2.1."""
    _code, out, cist, los = prolaz
    prvi = (out / "summary.csv").read_text(encoding="utf-8")
    pre = len(cist.requests) + len(los.requests)

    ponovo = tmp_path / "ponovo"
    assert cli.main(["recheck", str(out / "snapshots"), "--out", str(ponovo)]) == 0

    assert len(cist.requests) + len(los.requests) == pre, "recheck ne sme da dodirne mrežu"
    assert (ponovo / "summary.csv").read_text(encoding="utf-8") == prvi


def test_html_je_samostalan(prolaz):
    """Bez CDN-a: izveštaj se otvara i bez mreže (§10.2)."""
    _code, out, _cist, _los = prolaz
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<style>" in page and "<script>" in page
    assert "cdn" not in page.lower()
    assert 'src="http' not in page and "@import" not in page
    assert "0,6 MB/s" in page or "MB/s" in page, "pretpostavka za brzinu mora biti u fusnoti (§10.3)"


def test_record_snima_gzipovane_fixture_e(tmp_path):
    """§12.2: bez sirovog HTML-a ostalih strana, inače repo naraste."""
    from sitetriage import store

    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},hotel\n", encoding="utf-8")
        out = tmp_path / "fixtures"
        code = cli.main(
            ["record", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )

    assert code == 0
    assert list(out.glob("*/site.json.gz")), "fixture-i se pišu gzipovani"
    (snimljen, _browser) = next(iter(store.read_all(out)))
    assert snimljen.home.raw_html, "sirovi HTML početne ostaje (treba za eskalaciju)"
    assert all(p.raw_html is None for p in snimljen.pages[1:])


# --------------------------------------------------------------------------- #
# HTML izveštaj — sadržaj
# --------------------------------------------------------------------------- #
def _izvestaj(**kwargs) -> DomainReport:
    finding = Finding(
        domain="d.rs",
        check_id="seo.canonical.duplicate",
        level=1,
        category="seo",
        severity="critical",
        evidence={
            "stranica": 5, "ukupno": 7, "udeo": 0.7143, "canonical": "https://d.rs/", "grupa_putanja": 5,
            "uzorak": "sitemap",
        },
        evidence_urls=["https://d.rs/a"],
        weight=40.0,
    )
    base = {"domain": "d.rs", "industry": "hotel", "findings": [finding], "total_score": 40.0,
            "max_finding_weight": 40.0, "rank": 1}
    return DomainReport(**{**base, **kwargs})


def test_ozbiljnost_ima_oznaku_i_znak_a_ne_samo_boju():
    """Boje moraju biti razlučive i u sivim tonovima i za daltoniste (§10.2)."""
    page = html_out.render([_izvestaj()], load_config())
    assert "KRITIČNO" in page and "▲" in page


def test_nacrt_mejla_ima_tri_recenice():
    report = _izvestaj()
    nacrt = html_out.email_draft(report)
    assert report.domain in nacrt
    assert "1. 5 od 7 proverenih stranica sajta prijavljuje" in nacrt


def test_nacrt_mejla_za_cist_sajt_ne_izmislja_probleme():
    report = DomainReport(domain="cist.rs", industry="zdravstvo")
    assert "nisam našao" in html_out.email_draft(report)
    assert "did not find" in html_out.email_draft(report, "en")


def test_izvestaj_na_engleskom_nema_srpskih_oznaka():
    page = html_out.render([_izvestaj()], load_config(), lang="en")
    assert '<html lang="en">' in page and "▲ CRITICAL" in page and "Copy suggested text" in page
    assert "5 of the 7 checked pages on the site" in page
    assert "I reviewed the site d.rs" in page
    for srpski in ("KRITIČNO", "Kopiraj", "Rangirani", "Poštovani", "Prolaz od"):
        assert srpski not in page, srpski


@pytest.mark.parametrize(
    "lang, ocekivano",
    [pytest.param("sr", "· 1 nalaz</span>", id="sr"), pytest.param("en", "· 1 finding</span>", id="en")],
)
def test_broj_nalaza_u_izvestaju_se_slaze_sa_imenicom(lang, ocekivano):
    """Bilo je „1 nalaza"; na engleskom bi bilo „1 findings" (BUG-014, isto pravilo)."""
    assert ocekivano in html_out.render([_izvestaj()], load_config(), lang=lang)


def test_recheck_na_engleskom(tmp_path):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    assert cli.main(["recheck", str(fixtures), "--out", str(tmp_path), "--lang", "en"]) == 0
    redovi = list(csv.DictReader((tmp_path / "findings.csv").open(encoding="utf-8")))
    assert redovi and all(r["message_client"] for r in redovi)
    assert not [r for r in redovi if "strana" in r["message_client"] or "sajt" in r["message_client"]]
    assert '<html lang="en">' in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_html_bezi_od_html_a_iz_sadrzaja_sajta():
    """Naslovi i adrese dolaze sa tuđeg sajta — moraju da se eskejpuju."""
    report = _izvestaj()
    report.findings[0].evidence["canonical"] = '<script>alert("xss")</script>'
    page = html_out.render([report], load_config())
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_unknown_razlozi_se_prikazuju():
    from sitetriage.models import Reason, Unknown

    report = _izvestaj(
        unknowns=[Unknown("perf.page.weight", Reason("unmeasured_responses", {"nemereno": 9, "prag": 5}))]
    )
    page = html_out.render([report], load_config())
    assert "9 odgovora nije izmereno (prag 5)" in page
    assert "perf.page.weight" in page


def test_bom_se_pise_samo_kad_se_trazi(tmp_path):
    reports = rank([_izvestaj()])
    sa = csv_out.write_summary(tmp_path / "sa.csv", reports, bom=True)
    bez = csv_out.write_summary(tmp_path / "bez.csv", reports, bom=False)
    assert sa.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not bez.read_bytes().startswith(b"\xef\xbb\xbf")


# --------------------------------------------------------------------------- #
# explain (§11.1)
# --------------------------------------------------------------------------- #
def test_explain_ispisuje_prag_i_recenicu(capsys):
    assert cli.main(["explain", "seo.canonical.duplicate"]) == 0
    ispis = capsys.readouterr().out
    assert "critical" in ispis and "≥ 2 stranice" in ispis
    assert "rečenica za klijenta" in ispis


def test_explain_ispisuje_oba_jezika_i_varijante(capsys):
    assert cli.main(["explain", "perf.page.weight"]) == 0
    ispis = capsys.readouterr().out
    assert "rečenica za klijenta (sr)" in ispis and "rečenica za klijenta (en)" in ispis
    assert "varijanta video (sr)" in ispis and "varijanta video (en)" in ispis


def test_explain_all_bez_markdown_a(capsys):
    assert cli.main(["explain", "--all"]) == 0
    assert "perf.page.weight" in capsys.readouterr().out


def test_argumenti_komandne_linije_menjaju_konfiguraciju(tmp_path, monkeypatch):
    """`--concurrency` menja oba semafora, `--max-level2` limit, a `--format csv` piše samo CSV."""
    from sitetriage.models import ScanResult

    primljeno = {}

    async def scan(targets, config, **kwargs):
        primljeno.update(config=config, **kwargs)
        return ScanResult(duration_s={"total": 0.0})

    monkeypatch.setattr(cli.pipeline, "scan", scan)
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institucija\n", encoding="utf-8")
    izlaz = tmp_path / "izlaz"
    argumenti = ["--concurrency", "2", "--max-level2", "0", "--format", "csv", "--level", "1"]
    assert cli.main(["scan", str(domains), "--out", str(izlaz), *argumenti]) == 0

    config = primljeno["config"]
    assert config["http"]["concurrency"] == config["http"]["domain_concurrency"] == 2
    assert config["escalation"]["max_level2"] == 0 and primljeno["level"] == "1"
    assert (izlaz / "summary.csv").is_file() and not (izlaz / "index.html").exists()


def test_explain_ispisuje_opis_provere(capsys):
    # mutacija `description=None` u registru je preživela: opis se ispisivao, a niko ga nije proveravao
    assert cli.main(["explain", "seo.canonical.duplicate"]) == 0
    assert "upućuje canonical-om na istu drugu adresu" in capsys.readouterr().out


def test_explain_nepoznate_provere_predlaze_slicne():
    with pytest.raises(SystemExit, match="canonical"):
        cli.main(["explain", "canonical"])


def test_explain_all_markdown_pokriva_sve_provere(capsys):
    from sitetriage.checks import registry

    assert cli.main(["explain", "--all", "--markdown"]) == 0
    ispis = capsys.readouterr().out
    registry.load_all()
    for check_id in registry.REGISTRY:
        assert f"`{check_id}`" in ispis, f"{check_id} fali u tabeli za README"


def test_scan_bez_identiteta_odbija_pre_ijednog_zahteva(tmp_path, monkeypatch):
    """Bez imena i kontakta operatera nema skeniranja — ni jednog zahteva."""
    monkeypatch.delenv("SITETRIAGE_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("SITETRIAGE_OPERATOR_CONTACT", raising=False)
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},ostalo\n", encoding="utf-8")
        with pytest.raises(SystemExit, match=r"\[operator\] name"):
            cli.main(["scan", str(domains), "--out", str(tmp_path / "izlaz"), "--level", "1"])
        assert site.requests == [], f"zahtevi pre provere identiteta: {site.requests}"


def test_verzija_je_ista_u_paketu_cli_i_user_agentu(capsys, monkeypatch):
    """Administrator sajta vidi verziju u User-Agent-u, pa ona mora biti ona koja stvarno radi."""
    from importlib.metadata import version

    from sitetriage import __version__
    from sitetriage.config import user_agent

    assert version("sitetriage") == __version__, "pyproject.toml čita verziju iz sitetriage/__init__.py"
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"sitetriage {__version__}"
    monkeypatch.setenv("SITETRIAGE_OPERATOR_NAME", "Web studio Primer")
    monkeypatch.setenv("SITETRIAGE_OPERATOR_CONTACT", "kontakt@primer.rs")
    assert f"/{__version__} " in user_agent(load_config())


# --------------------------------------------------------------------------- #
# Pogađanje grešaka: nevažeći brojevi na komandnoj liniji
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "argumenti",
    [
        pytest.param(["--concurrency", "0"], id="gv-concurrency-0"),
        pytest.param(["--concurrency", "-1"], id="nv-concurrency-negativan"),
        pytest.param(["--concurrency", "osam"], id="nv-concurrency-tekst"),
        pytest.param(["--max-level2", "-1"], id="nv-max-level2-negativan"),
    ],
)
def test_nevazeci_brojevi_na_komandnoj_liniji_se_odbijaju(tmp_path, argumenti):
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institucija\n", encoding="utf-8")
    with pytest.raises(SystemExit) as izlaz:
        cli.main(["scan", str(domains), "--out", str(tmp_path / "izlaz"), *argumenti])
    assert izlaz.value.code == 2, "argparse odbija pre ijednog zahteva"


# --------------------------------------------------------------------------- #
# Tok nivoa 2 kroz CLI — pokrivenost je pokazala da ga nijedan test ne pokreće,
# a koristi ga svaki pravi prolaz.
# --------------------------------------------------------------------------- #
BEZ_H1 = (
    "<!doctype html><html lang='sr'><head><title>Bez naslova</title>"
    "<link rel='canonical' href='/'><meta name='description' content='Opis.'>"
    "<meta property='og:title' content='a'><meta property='og:description' content='b'>"
    "<meta property='og:image' content='/c.jpg'></head><body><p>"
    + "Sadržaj sa dijakriticima čćšžđ. " * 60
    + "</p></body></html>"
).encode()


# Početna sa dovoljno teksta: lažni sajt inače ima ~550 znakova, ispod praga od 800
# za „prazan HTML", pa je i on legitimno kandidat za nivo 2.
BOGATA_POCETNA = html(
    "Početna",
    head=(
        "<link rel='canonical' href='/'><meta name='description' content='Opis.'>"
        "<meta property='og:title' content='a'><meta property='og:description' content='b'>"
        "<meta property='og:image' content='/c.jpg'>"
    ),
    body="<p>" + "Dodatni tekst o uslugama i cenama. " * 30 + "</p>",
)


@pytest.mark.browser
def test_scan_auto_salje_na_pun_nivo_2_samo_kandidate(tmp_path):
    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite(extra={"/": Response(BOGATA_POCETNA)}) as cist, FakeSite(
        extra={"/": Response(BEZ_H1)}
    ) as bez_h1:
        domains = tmp_path / "d.csv"
        domains.write_text(
            f"domain,industry\n{cist.base_url},ostalo\n{bez_h1.base_url},ostalo\n", encoding="utf-8"
        )
        out = tmp_path / "izvestaj"
        assert cli.main(["scan", str(domains), "--out", str(out), "--config", str(config)]) == 0

    snimci = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "snapshots").glob("*/browser.json")]
    lagano = {s["domain"]: s["light"] for s in snimci}
    assert lagano[bez_h1.base_url] is False, "sirovi HTML bez h1 mora na pun nivo 2"
    # BUG-020: čist i brz HTML ne govori ništa o težini strane, pa i taj sajt meri težinu, ali bez profila.
    assert lagano[cist.base_url] is True, "čist i brz sajt dobija lagan nivo 2"
    nalazi = [r for r in csv.DictReader((out / "findings.csv").open(encoding="utf-8"))]
    assert any(r["domain"] == bez_h1.base_url and r["check_id"] == "seo.h1.missing" for r in nalazi)
    assert list((out / "snapshots").glob("*/browser.json")), "snapshot nivoa 2 mora na disk"


def test_bez_playwright_nivo_2_se_preskace_uz_poruku(tmp_path, monkeypatch, caplog):
    """`pip install sitetriage` bez `[browser]`: nivo 1 radi, a nivo 2 se preskače uz razlog.

    CLI je hvatao `ImportError` samo pri uvozu modula `fetch.browser`, a on se uvozi i
    bez Playwright-a. Playwright se uvozi tek u `capture_all`, pa je prolaz pucao.
    """
    import sys

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},ostalo\n", encoding="utf-8")
        out = tmp_path / "izvestaj"
        argumenti = ["scan", str(domains), "--out", str(out), "--level", "2", "--config", str(config)]
        assert cli.main(argumenti) == 0

    redovi = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert redovi[0]["level2_ran"] == "0"
    assert "Playwright nije instaliran" in caplog.text


@pytest.mark.browser
def test_record_nivo_2_snima_i_browser_snapshot(tmp_path):
    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},ostalo\n", encoding="utf-8")
        out = tmp_path / "fixtures"
        argumenti = ["record", str(domains), "--out", str(out), "--level", "2", "--config", str(config)]
        assert cli.main(argumenti) == 0
    assert list(out.glob("*/browser.json.gz")) and list(out.glob("*/site.json.gz"))


# --------------------------------------------------------------------------- #
# Greške komandi i logovanje
# --------------------------------------------------------------------------- #
def test_recheck_bez_snapshota_puca_razumljivo(tmp_path):
    with pytest.raises(SystemExit, match="nijedan snapshot"):
        cli.main(["recheck", str(tmp_path), "--out", str(tmp_path / "izlaz")])


def test_explain_bez_argumenata_puca(capsys):
    with pytest.raises(SystemExit):
        cli.main(["explain"])
    assert "--all" in capsys.readouterr().err


def test_prekid_sa_tastature_vraca_130(monkeypatch, tmp_path):
    """Ctrl+C usred prolaza: uredan izlazni kod 130, ne traceback."""

    def prekini(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_recheck", prekini)  # parser se gradi pri svakom pozivu main()
    assert cli.main(["recheck", str(tmp_path)]) == 130


def test_greska_u_konfiguraciji_je_poruka_a_ne_traceback(tmp_path):
    pokvaren = tmp_path / "pokvaren.toml"
    pokvaren.write_text("[http\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="greška u konfiguraciji"):
        cli.main(["recheck", str(tmp_path), "--config", str(pokvaren)])


def test_debug_domain_propusta_samo_taj_domen():
    import io
    import logging

    cli.setup_logging("institucija.example")
    tok = io.StringIO()
    handler = logging.getLogger("sitetriage").handlers[0]
    handler.stream = tok
    log = logging.getLogger("sitetriage.test")
    log.debug("ovaj se vidi", extra={"domain": "institucija.example"})
    log.debug("ovaj ne", extra={"domain": "restoran-ugao.example"})
    redovi = [json.loads(red) for red in tok.getvalue().splitlines()]
    assert [r["message"] for r in redovi] == ["ovaj se vidi"]
    assert redovi[0]["domain"] == "institucija.example" and redovi[0]["level"] == "DEBUG"
    cli.setup_logging(None)


@pytest.mark.skipif(not hasattr(__import__("time"), "tzset"), reason="tzset postoji samo na Unix-u")
def test_vreme_u_logu_je_zaista_utc(monkeypatch):
    """Pogađanje grešaka (vremenska zona): „Z" na kraju tvrdi UTC, pa vreme mora biti UTC."""
    import logging
    import time

    monkeypatch.setenv("TZ", "Europe/Belgrade")
    time.tzset()
    try:
        zapis = logging.LogRecord("sitetriage", logging.INFO, __file__, 1, "poruka", None, None)
        zapis.created = 1_790_000_000  # 2026-09-21T14:13:20Z; u Beogradu je tada 16:13
        assert json.loads(cli.JsonLines().format(zapis))["ts"] == "2026-09-21T14:13:20Z"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
