"""CLI and reports end to end."""

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
# Input CSV: only what the CLI does here (`--only`, the log and the error message).
# Reading the list itself is in test_inputs.py.
# --------------------------------------------------------------------------- #
def test_only_filters(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("domain,industry\na.rs,hotel\nb.rs,hotel\n", encoding="utf-8")
    assert [r.domain for r in cli.read_domains(path, ["B.RS"])] == ["b.rs"]
    with pytest.raises(InputError, match="--only"):
        cli.read_domains(path, ["c.rs"])


def test_list_warnings_go_to_the_log_with_the_row_number(tmp_path, caplog):
    path = tmp_path / "d.csv"
    path.write_text(
        "domain,industry\ninstitucija.example,institution\nINSTITUCIJA.EXAMPLE,hotel\n", encoding="utf-8"
    )
    cli.read_domains(path)
    assert "row 3: same site as row 2 (institucija.example)" in caplog.text


def test_excluded_from_config_and_from_the_command_line(tmp_path):
    """Both sources apply; the report shows only the number of excluded domains, without names."""
    with FakeSite() as first:
        host, port = first.address
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{first.base_url},other\n", encoding="utf-8")
        from_config = tmp_path / "excluded.txt"
        from_config.write_text("# pisali 25.09.\nnekidrugi.rs\n", encoding="utf-8")
        from_command_line = tmp_path / "more.txt"
        from_command_line.write_text(f"{host}\n", encoding="utf-8")
        config = tmp_path / "mine.toml"
        config.write_text(f'[operator]\nexclude_file = "{from_config.as_posix()}"\n', encoding="utf-8")
        out = tmp_path / "out"
        arguments = ["--config", str(config), "--exclude", str(from_command_line), "--level", "1"]
        assert cli.main(["scan", str(domains), "--out", str(out), *arguments]) == 0
    assert first.requests == []
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["summary"]["excluded"] == 1
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "Excluded on request" in page and first.base_url not in page


def test_missing_exclusion_file_fails_clearly(tmp_path):
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institution\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="the file of excluded domains does not exist"):
        cli.main(["scan", str(domains), "--out", str(tmp_path / "out"), "--exclude", "nema.txt"])


def test_list_error_is_a_message_not_a_traceback(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("sajt,industry\na.rs,hotel\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="row 1: the header has no `domain` column"):
        cli.main(["scan", str(path), "--out", str(tmp_path / "out")])


# --------------------------------------------------------------------------- #
# scan → recheck
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def scan_run(tmp_path_factory):
    """Two local sites: one tidy, one with a soft 404 and without OG tags.

    One run for the whole module: starting the servers and a full scan take time, and every
    test below looks at the same result.
    """
    tmp_path = tmp_path_factory.mktemp("run")
    # `--config` is merged over the default config; here we turn off the pauses so the tests
    # do not take a minute.
    config = tmp_path / "fast.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")

    with FakeSite() as clean, FakeSite(soft404=True, extra={"/": Response(html("Bez oznaka"))}) as broken:
        domains = tmp_path / "domains.csv"
        domains.write_text(
            f"domain,industry,note\n{clean.base_url},hotel,\n{broken.base_url},restaurant,\n",
            encoding="utf-8",
        )
        out = tmp_path / "report"
        code = cli.main(
            ["scan", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )
        yield code, out, clean, broken


def test_scan_writes_every_output(scan_run):
    code, out, _clean, _broken = scan_run
    assert code == 0
    assert (out / "index.html").is_file()
    assert (out / "findings.csv").is_file()
    assert (out / "summary.csv").is_file()
    assert list((out / "snapshots").glob("*/site.json")), "snapshots are always written"


def test_scan_writes_json_that_matches_the_schema(scan_run):
    import jsonschema
    from test_json import SCHEMA

    _code, out, _clean, _broken = scan_run
    document = json.loads((out / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(document, SCHEMA)
    assert set(document["duration_s"]) == {"level1", "level2", "level2_light", "total"}
    assert document["environment"]["chromium"] is None, "level 2 did not run (--level 1)"


def test_summary_has_a_row_per_domain(scan_run):
    _code, out, _clean, _broken = scan_run
    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert set(rows[0]) == set(csv_out.SUMMARY_HEADER)
    assert {r["industry"] for r in rows} == {"hotel", "restaurant"}
    assert [int(r["rank"]) for r in rows] == [1, 2]


def test_findings_have_a_row_per_finding_with_evidence(scan_run):
    _code, out, _clean, _broken = scan_run
    rows = list(csv.DictReader((out / "findings.csv").open(encoding="utf-8")))
    assert rows, "the broken site must produce at least one finding"
    assert set(rows[0]) == set(csv_out.FINDINGS_HEADER)
    for row in rows:
        assert json.loads(row["evidence_json"]), "every finding carries evidence"
        assert row["message_client"] and "{" not in row["message_client"]


def test_recheck_gives_the_same_result_without_a_single_request(scan_run, tmp_path):
    """Calibration without a new run is the whole point of keeping fetching and checks apart."""
    _code, out, clean, broken = scan_run
    first = (out / "summary.csv").read_text(encoding="utf-8")
    before = len(clean.requests) + len(broken.requests)

    again = tmp_path / "again"
    assert cli.main(["recheck", str(out / "snapshots"), "--out", str(again)]) == 0

    assert len(clean.requests) + len(broken.requests) == before, "recheck must not touch the network"
    assert (again / "summary.csv").read_text(encoding="utf-8") == first


def test_html_is_self_contained(scan_run):
    """No CDN: the report opens without a network."""
    _code, out, _clean, _broken = scan_run
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<style>" in page and "<script>" in page
    assert "cdn" not in page.lower()
    assert 'src="http' not in page and "@import" not in page
    assert "0,6 MB/s" in page or "MB/s" in page, "the speed assumption must be in the footnote"


def test_record_writes_gzipped_fixtures(tmp_path):
    """Without the raw HTML of the other pages, otherwise the repository grows."""
    from sitetriage import store

    config = tmp_path / "fast.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},hotel\n", encoding="utf-8")
        out = tmp_path / "fixtures"
        code = cli.main(
            ["record", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )

    assert code == 0
    assert list(out.glob("*/site.json.gz")), "fixtures are written gzipped"
    (recorded, _browser) = next(iter(store.read_all(out)))
    assert recorded.home.raw_html, "the raw HTML of the home page stays (escalation needs it)"
    assert all(p.raw_html is None for p in recorded.pages[1:])


# --------------------------------------------------------------------------- #
# HTML report: content
# --------------------------------------------------------------------------- #
def _report(**kwargs) -> DomainReport:
    finding = Finding(
        domain="d.rs",
        check_id="seo.canonical.duplicate",
        level=1,
        category="seo",
        severity="critical",
        evidence={
            "page_count": 5, "total": 7, "share": 0.7143, "canonical": "https://d.rs/", "path_groups": 5,
            "sample": "sitemap",
        },
        evidence_urls=["https://d.rs/a"],
        weight=40.0,
    )
    base = {"domain": "d.rs", "industry": "hotel", "findings": [finding], "total_score": 40.0,
            "max_finding_weight": 40.0, "rank": 1}
    return DomainReport(**{**base, **kwargs})


def test_severity_has_a_label_and_a_glyph_not_only_a_colour():
    """Colours must be distinguishable in greyscale and for colour-blind readers."""
    page = html_out.render([_report()], load_config())
    assert "KRITIČNO" in page and "▲" in page


def test_email_draft_has_three_sentences():
    report = _report()
    draft = html_out.email_draft(report)
    assert report.domain in draft
    assert "1. 5 od 7 proverenih stranica sajta prijavljuje" in draft


def test_email_draft_for_a_clean_site_does_not_invent_problems():
    report = DomainReport(domain="cist.rs", industry="healthcare")
    assert "nisam našao" in html_out.email_draft(report)
    assert "did not find" in html_out.email_draft(report, "en")


def test_english_report_has_no_serbian_labels():
    page = html_out.render([_report()], load_config(), lang="en")
    assert '<html lang="en">' in page and "▲ CRITICAL" in page and "Copy suggested text" in page
    assert "5 of the 7 checked pages on the site" in page
    assert "I reviewed the site d.rs" in page
    for serbian in ("KRITIČNO", "Kopiraj", "Rangirani", "Poštovani", "Prolaz od"):
        assert serbian not in page, serbian


@pytest.mark.parametrize(
    "lang, expected",
    [pytest.param("sr", "· 1 nalaz</span>", id="sr"), pytest.param("en", "· 1 finding</span>", id="en")],
)
def test_finding_count_in_the_report_agrees_with_the_noun(lang, expected):
    """It used to say „1 nalaza"; in English it would be "1 findings" (BUG-014, same rule)."""
    assert expected in html_out.render([_report()], load_config(), lang=lang)


def test_recheck_in_english(tmp_path):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    assert cli.main(["recheck", str(fixtures), "--out", str(tmp_path), "--lang", "en"]) == 0
    rows = list(csv.DictReader((tmp_path / "findings.csv").open(encoding="utf-8")))
    assert rows and all(r["message_client"] for r in rows)
    assert not [r for r in rows if "strana" in r["message_client"] or "sajt" in r["message_client"]]
    assert '<html lang="en">' in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_html_escapes_html_from_site_content():
    """Titles and URLs come from someone else's site, so they must be escaped."""
    report = _report()
    report.findings[0].evidence["canonical"] = '<script>alert("xss")</script>'
    page = html_out.render([report], load_config())
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_unknown_reasons_are_shown():
    from sitetriage.models import Reason, Unknown

    reason = Reason("unmeasured_responses", {"unmeasured": 9, "threshold": 5})
    report = _report(unknowns=[Unknown("perf.page.weight", reason)])
    page = html_out.render([report], load_config())
    assert "9 odgovora nije izmereno (prag 5)" in page
    assert "perf.page.weight" in page


def test_bom_is_written_only_when_asked_for(tmp_path):
    reports = rank([_report()])
    with_bom = csv_out.write_summary(tmp_path / "with.csv", reports, bom=True)
    without_bom = csv_out.write_summary(tmp_path / "without.csv", reports, bom=False)
    assert with_bom.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not without_bom.read_bytes().startswith(b"\xef\xbb\xbf")


# --------------------------------------------------------------------------- #
# explain
# --------------------------------------------------------------------------- #
def test_explain_prints_the_threshold_and_the_sentence(capsys):
    assert cli.main(["explain", "seo.canonical.duplicate"]) == 0
    output = capsys.readouterr().out
    assert "critical" in output and "≥ 2 pages" in output
    assert "client sentence" in output


def test_explain_prints_both_languages_and_variants(capsys):
    assert cli.main(["explain", "perf.page.weight"]) == 0
    output = capsys.readouterr().out
    assert "client sentence (sr)" in output and "client sentence (en)" in output
    assert "variant video (sr)" in output and "variant video (en)" in output


def test_explain_all_without_markdown(capsys):
    assert cli.main(["explain", "--all"]) == 0
    assert "perf.page.weight" in capsys.readouterr().out


def test_command_line_arguments_change_the_config(tmp_path, monkeypatch):
    """`--concurrency` changes both semaphores, `--max-level2` the limit, and `--format csv`
    writes only CSV."""
    from sitetriage.models import ScanResult

    received = {}

    async def scan(targets, config, **kwargs):
        received.update(config=config, **kwargs)
        return ScanResult(duration_s={"total": 0.0})

    monkeypatch.setattr(cli.pipeline, "scan", scan)
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institution\n", encoding="utf-8")
    out = tmp_path / "out"
    arguments = ["--concurrency", "2", "--max-level2", "0", "--format", "csv", "--level", "1"]
    assert cli.main(["scan", str(domains), "--out", str(out), *arguments]) == 0

    config = received["config"]
    assert config["http"]["concurrency"] == config["http"]["domain_concurrency"] == 2
    assert config["escalation"]["max_level2"] == 0 and received["level"] == "1"
    assert (out / "summary.csv").is_file() and not (out / "index.html").exists()


def test_explain_prints_the_check_description(capsys):
    # the mutation `description=None` in the registry survived: the description was printed,
    # but nothing checked it
    assert cli.main(["explain", "seo.canonical.duplicate"]) == 0
    assert "point their canonical to the same other URL" in capsys.readouterr().out


def test_explain_of_an_unknown_check_suggests_similar_ones():
    with pytest.raises(SystemExit, match="canonical"):
        cli.main(["explain", "canonical"])


def test_explain_all_markdown_covers_every_check(capsys):
    from sitetriage.checks import registry

    assert cli.main(["explain", "--all", "--markdown"]) == 0
    output = capsys.readouterr().out
    registry.load_all()
    for check_id in registry.REGISTRY:
        assert f"`{check_id}`" in output, f"{check_id} is missing from the README table"


def test_scan_without_identity_refuses_before_a_single_request(tmp_path, monkeypatch):
    """Without the operator's name and contact there is no scanning, not even one request."""
    monkeypatch.delenv("SITETRIAGE_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("SITETRIAGE_OPERATOR_CONTACT", raising=False)
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},other\n", encoding="utf-8")
        with pytest.raises(SystemExit, match=r"\[operator\] name"):
            cli.main(["scan", str(domains), "--out", str(tmp_path / "out"), "--level", "1"])
        assert site.requests == [], f"requests before the identity check: {site.requests}"


def test_version_is_the_same_in_the_package_cli_and_user_agent(capsys, monkeypatch):
    """The site administrator sees the version in the User-Agent, so it must be the one that runs."""
    from importlib.metadata import version

    from sitetriage import __version__
    from sitetriage.config import user_agent

    assert version("sitetriage") == __version__, "pyproject.toml reads the version from __init__.py"
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"sitetriage {__version__}"
    monkeypatch.setenv("SITETRIAGE_OPERATOR_NAME", "Web studio Primer")
    monkeypatch.setenv("SITETRIAGE_OPERATOR_CONTACT", "kontakt@primer.rs")
    assert f"/{__version__} " in user_agent(load_config())


# --------------------------------------------------------------------------- #
# Error guessing: invalid numbers on the command line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["--concurrency", "0"], id="gv-concurrency-0"),
        pytest.param(["--concurrency", "-1"], id="nv-concurrency-negative"),
        pytest.param(["--concurrency", "osam"], id="nv-concurrency-text"),
        pytest.param(["--max-level2", "-1"], id="nv-max-level2-negative"),
    ],
)
def test_invalid_numbers_on_the_command_line_are_rejected(tmp_path, arguments):
    domains = tmp_path / "d.csv"
    domains.write_text("domain,industry\ninstitucija.example,institution\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["scan", str(domains), "--out", str(tmp_path / "out"), *arguments])
    assert exit_info.value.code == 2, "argparse rejects it before a single request"


# --------------------------------------------------------------------------- #
# Level 2 through the CLI: coverage showed that no test ran it, and every real run uses it.
# --------------------------------------------------------------------------- #
WITHOUT_H1 = (
    "<!doctype html><html lang='sr'><head><title>Bez naslova</title>"
    "<link rel='canonical' href='/'><meta name='description' content='Opis.'>"
    "<meta property='og:title' content='a'><meta property='og:description' content='b'>"
    "<meta property='og:image' content='/c.jpg'></head><body><p>"
    + "Sadržaj sa dijakriticima čćšžđ. " * 60
    + "</p></body></html>"
).encode()


# A home page with enough text: the fake site otherwise has ~550 characters, below the 800
# threshold for "empty HTML", so it would legitimately be a level 2 candidate too.
RICH_HOME = html(
    "Početna",
    head=(
        "<link rel='canonical' href='/'><meta name='description' content='Opis.'>"
        "<meta property='og:title' content='a'><meta property='og:description' content='b'>"
        "<meta property='og:image' content='/c.jpg'>"
    ),
    body="<p>" + "Dodatni tekst o uslugama i cenama. " * 30 + "</p>",
)


@pytest.mark.browser
def test_scan_auto_sends_only_candidates_to_full_level2(tmp_path):
    config = tmp_path / "fast.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite(extra={"/": Response(RICH_HOME)}) as clean, FakeSite(
        extra={"/": Response(WITHOUT_H1)}
    ) as without_h1:
        domains = tmp_path / "d.csv"
        domains.write_text(
            f"domain,industry\n{clean.base_url},other\n{without_h1.base_url},other\n", encoding="utf-8"
        )
        out = tmp_path / "report"
        assert cli.main(["scan", str(domains), "--out", str(out), "--config", str(config)]) == 0

    paths = (out / "snapshots").glob("*/browser.json")
    snapshots = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    light = {s["domain"]: s["light"] for s in snapshots}
    assert light[without_h1.base_url] is False, "raw HTML without h1 must go to full level 2"
    # BUG-020: clean and fast HTML says nothing about page weight, so that site measures weight
    # too, but without the profile.
    assert light[clean.base_url] is True, "a clean and fast site gets light level 2"
    findings = [r for r in csv.DictReader((out / "findings.csv").open(encoding="utf-8"))]
    assert any(r["domain"] == without_h1.base_url and r["check_id"] == "seo.h1.missing" for r in findings)
    assert list((out / "snapshots").glob("*/browser.json")), "the level 2 snapshot must reach the disk"


def test_without_playwright_level2_is_skipped_with_a_message(tmp_path, monkeypatch, caplog):
    """`pip install sitetriage` without `[browser]`: level 1 works, level 2 is skipped with a reason.

    The CLI caught `ImportError` only when importing the `fetch.browser` module, and that module
    imports without Playwright too. Playwright is imported only in `capture_all`, so the run crashed.
    """
    import sys

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    config = tmp_path / "fast.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},other\n", encoding="utf-8")
        out = tmp_path / "report"
        arguments = ["scan", str(domains), "--out", str(out), "--level", "2", "--config", str(config)]
        assert cli.main(arguments) == 0

    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert rows[0]["level2_ran"] == "0"
    assert "Playwright is not installed" in caplog.text


@pytest.mark.parametrize(
    "level",
    [pytest.param("2", id="pg-level2-chromium-missing"), pytest.param("auto", id="pg-auto-chromium-missing")],
)
def test_without_chromium_level2_is_skipped_with_a_message(tmp_path, monkeypatch, caplog, level):
    """Playwright is installed but Chromium is not (BUG-01): level 2 is skipped, the reports are written.

    The launch error escaped the pipeline, so a long level 1 ended in a traceback with only snapshots.
    """
    pytest.importorskip("playwright.async_api")
    monkeypatch.delenv("SITETRIAGE_CHROMIUM", raising=False)
    missing = tmp_path / "no-chromium" / "chrome"
    config = tmp_path / "fast.toml"
    config.write_text(
        f'[http]\ndelay_ms = [0, 0]\n[browser]\nexecutable_path = "{missing.as_posix()}"\n', encoding="utf-8"
    )
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},other\n", encoding="utf-8")
        out = tmp_path / "report"
        arguments = ["scan", str(domains), "--out", str(out), "--level", level, "--config", str(config)]
        assert cli.main(arguments) == 0

    assert (out / "index.html").exists() and (out / "report.json").exists()
    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert rows[0]["level2_ran"] == "0"
    assert not list((out / "snapshots").glob("*/browser.json"))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Chromium could not be started" in m and "playwright install chromium" in m for m in errors)
    assert sum("Chromium could not be started" in m for m in errors) == 1, "light level 2 must not retry"


@pytest.mark.browser
def test_record_level2_also_records_the_browser_snapshot(tmp_path):
    config = tmp_path / "fast.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},other\n", encoding="utf-8")
        out = tmp_path / "fixtures"
        arguments = ["record", str(domains), "--out", str(out), "--level", "2", "--config", str(config)]
        assert cli.main(arguments) == 0
    assert list(out.glob("*/browser.json.gz")) and list(out.glob("*/site.json.gz"))


# --------------------------------------------------------------------------- #
# Command errors and logging
# --------------------------------------------------------------------------- #
def test_recheck_without_snapshots_fails_clearly(tmp_path):
    with pytest.raises(SystemExit, match="no snapshot found"):
        cli.main(["recheck", str(tmp_path), "--out", str(tmp_path / "out")])


def test_explain_without_arguments_fails(capsys):
    with pytest.raises(SystemExit):
        cli.main(["explain"])
    assert "--all" in capsys.readouterr().err


def test_keyboard_interrupt_returns_130(monkeypatch, tmp_path):
    """Ctrl+C in the middle of a run: a clean exit code 130, not a traceback."""

    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_recheck", interrupt)  # the parser is built on every main() call
    assert cli.main(["recheck", str(tmp_path)]) == 130


def test_config_error_is_a_message_not_a_traceback(tmp_path):
    broken = tmp_path / "broken.toml"
    broken.write_text("[http\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="configuration error"):
        cli.main(["recheck", str(tmp_path), "--config", str(broken)])


def test_debug_domain_lets_through_only_that_domain():
    import io
    import logging

    cli.setup_logging("institucija.example")
    stream = io.StringIO()
    handler = logging.getLogger("sitetriage").handlers[0]
    handler.stream = stream
    log = logging.getLogger("sitetriage.test")
    log.debug("this one shows", extra={"domain": "institucija.example"})
    log.debug("this one does not", extra={"domain": "restoran-ugao.example"})
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [r["message"] for r in lines] == ["this one shows"]
    assert lines[0]["domain"] == "institucija.example" and lines[0]["level"] == "DEBUG"
    cli.setup_logging(None)


@pytest.mark.skipif(not hasattr(__import__("time"), "tzset"), reason="tzset exists only on Unix")
def test_log_time_is_really_utc(monkeypatch):
    """Error guessing (time zone): the trailing "Z" claims UTC, so the time must be UTC."""
    import logging
    import time

    monkeypatch.setenv("TZ", "Europe/Belgrade")
    time.tzset()
    try:
        record = logging.LogRecord("sitetriage", logging.INFO, __file__, 1, "message", None, None)
        record.created = 1_790_000_000  # 2026-09-21T14:13:20Z; 16:13 in Belgrade at that moment
        assert json.loads(cli.JsonLines().format(record))["ts"] == "2026-09-21T14:13:20Z"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_partial_sitetriage_toml_in_the_working_directory_works_with_config(tmp_path, monkeypatch):
    """BUG-04: an `[operator]`-only `sitetriage.toml` failed with `severity_points.critical is
    missing`, because it replaced the defaults instead of being merged over them."""
    from pathlib import Path

    (tmp_path / "sitetriage.toml").write_text(
        '[operator]\nname = "Example Web Studio"\ncontact = "hello@studio.example"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    fixtures = Path(__file__).parent / "fixtures"
    out = tmp_path / "out"
    for arguments in ([], ["--config", "sitetriage.toml"]):
        assert cli.main(["recheck", str(fixtures), "--out", str(out), "--format", "json", *arguments]) == 0
