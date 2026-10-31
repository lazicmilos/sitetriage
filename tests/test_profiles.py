"""ADR-023: profiles, and `i18n.lang.mismatch` off unless a profile turns content detection on.

Merge order: package defaults → profile → user `--config`. `--profile` wins over `profile` in the
user config. Without a profile `content_languages` is empty and the mismatch check is
`not_applicable`; with `rs` it behaves exactly as before (the boundary tests in
`test_boundaries.py` run with `rs` through `factories.CONFIG`).
"""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
from factories import NO_PROFILE, clean_site, run_level

from sitetriage import cli, pipeline
from sitetriage.checks import i18n
from sitetriage.config import ConfigError, available_profiles, digest, get, load_config, profile_path
from sitetriage.messages import LANGS, reason
from sitetriage.models import CONTENT_LANGUAGES, REPORT_LANGUAGES, Reason, to_jsonable
from sitetriage.report import html_out
from sitetriage.score import analyze, escalation_reasons, partial_shares

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(files("sitetriage").joinpath("schema/report-3.json").read_text(encoding="utf-8"))
MISMATCH = "i18n.lang.mismatch"


def _toml(tmp_path: Path, text: str, name: str = "my.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Profiles are package data, like the defaults
# --------------------------------------------------------------------------- #
def test_rs_profile_ships_inside_the_package(tmp_path, monkeypatch):
    """A wheel from PyPI has no repository around it: the profile must come from the package."""
    monkeypatch.chdir(tmp_path)
    packaged = files("sitetriage").joinpath("profiles").joinpath("rs.toml")
    assert packaged.is_file()
    assert profile_path("rs") == Path(str(packaged))
    assert get(load_config(profile="rs"), "thresholds.i18n.content_languages") == ["sr"]


@pytest.mark.skipif("MUTANT_UNDER_TEST" in os.environ, reason="mutmut copies only part of the repository")
def test_profiles_are_package_data():
    import tomllib

    root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "profiles/*.toml" in pyproject["tool"]["setuptools"]["package-data"]["sitetriage"]
    assert "sitetriage/profiles/" in pyproject["tool"]["mutmut"]["also_copy"]


def test_available_profiles():
    assert available_profiles() == ["rs"]


def test_without_a_profiles_folder_there_are_none(monkeypatch):
    monkeypatch.setattr("sitetriage.config.PROFILES_DIR", "nonexistent")
    assert available_profiles() == []
    with pytest.raises(ConfigError, match="available profiles: none"):
        load_config(profile="rs")


# --------------------------------------------------------------------------- #
# Merge order: defaults → profile → --config
# --------------------------------------------------------------------------- #
def test_defaults_have_no_profile_and_no_content_language():
    cfg = load_config()
    assert cfg["profile"] == ""
    assert get(cfg, "thresholds.i18n.content_languages") == []


def test_profile_is_merged_over_the_defaults_and_changes_only_what_it_sets():
    default, rs = load_config(), load_config(profile="rs")
    assert get(rs, "thresholds.i18n.content_languages") == ["sr"]
    assert rs["profile"] == "rs"
    assert (get(default, "report.lang"), get(rs, "report.lang")) == ("en", "sr")
    for cfg in (default, rs):
        del cfg["profile"]
        del cfg["thresholds"]["i18n"]["content_languages"]
        del cfg["report"]["lang"]
    assert default == rs


def test_config_file_is_merged_over_the_profile(tmp_path):
    override = _toml(tmp_path, "[thresholds.i18n]\ncontent_languages = []\ncyrillic_ratio = 0.5\n")
    cfg = load_config(override, profile="rs")
    assert cfg["profile"] == "rs"
    assert get(cfg, "thresholds.i18n.content_languages") == []
    assert get(cfg, "thresholds.i18n.cyrillic_ratio") == 0.5
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005


def test_config_file_keeps_what_the_profile_sets(tmp_path):
    override = _toml(tmp_path, "[thresholds.i18n]\ncyrillic_ratio = 0.5\n")
    assert get(load_config(override, profile="rs"), "thresholds.i18n.content_languages") == ["sr"]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("xx", id="nv-unknown"),
        pytest.param("RS", id="nv-case"),
        pytest.param("rs.toml", id="nv-with-extension"),
        pytest.param("../sitetriage", id="pg-path-outside-profiles"),
    ],
)
def test_unknown_profile_fails_and_lists_the_available_ones(name):
    with pytest.raises(ConfigError, match=r"unknown profile .*; available profiles: rs"):
        load_config(profile=name)


def test_unknown_profile_in_the_config_file_fails_too(tmp_path):
    with pytest.raises(ConfigError, match="unknown profile 'xx'"):
        load_config(_toml(tmp_path, 'profile = "xx"\n'))


@pytest.mark.parametrize("value", [pytest.param("1", id="nv-integer"), pytest.param('["rs"]', id="nv-list")])
def test_profile_key_must_be_a_string(tmp_path, value):
    with pytest.raises(ConfigError, match="profile must be"):
        load_config(_toml(tmp_path, f"profile = {value}\n"))


def test_a_profile_cannot_choose_another_profile(tmp_path, monkeypatch):
    chained = _toml(tmp_path, 'profile = "rs"\n', "chained.toml")
    monkeypatch.setattr("sitetriage.config.profile_path", lambda name: chained)
    with pytest.raises(ConfigError, match="cannot choose another profile"):
        load_config(profile="chained")


# --------------------------------------------------------------------------- #
# --profile against `profile` in --config: the flag wins
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "flag, key, expected",
    [
        pytest.param(None, None, "", id="tab-1-neither"),
        pytest.param(None, "rs", "rs", id="tab-2-key-only"),
        pytest.param("rs", None, "rs", id="tab-3-flag-only"),
        pytest.param("rs", "rs", "rs", id="tab-4-both"),
        pytest.param("", "rs", "", id="tab-5-empty-flag-turns-the-key-off"),
        pytest.param("rs", "xx", "rs", id="tab-6-flag-wins-over-an-unknown-key"),
    ],
)
def test_flag_wins_over_config_key(tmp_path, flag, key, expected):
    path = _toml(tmp_path, f'profile = "{key}"\n') if key is not None else None
    cfg = load_config(path, profile=flag)
    assert cfg["profile"] == expected
    assert get(cfg, "thresholds.i18n.content_languages") == (["sr"] if expected else [])


# --------------------------------------------------------------------------- #
# content_languages: validated as strictly as the rest
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, valid",
    [
        pytest.param("[]", True, id="ke-empty"),
        pytest.param('["sr"]', True, id="ke-sr"),
        pytest.param('["en"]', False, id="nv-no-detector"),
        pytest.param('["sr", "hr"]', False, id="nv-one-without-detector"),
        pytest.param('"sr"', False, id="nv-not-a-list"),
    ],
)
def test_content_languages_must_have_a_detector(tmp_path, value, valid):
    override = _toml(tmp_path, f"[thresholds.i18n]\ncontent_languages = {value}\n")
    if valid:
        assert get(load_config(override), "thresholds.i18n.content_languages") == json.loads(value)
    else:
        with pytest.raises(ConfigError, match="must be a list of languages with a detector"):
            load_config(override)


def test_every_content_language_has_a_detector():
    assert set(i18n.DETECTORS) == set(CONTENT_LANGUAGES)


# --------------------------------------------------------------------------- #
# Digest: what the profile changes is in it, its name is not
# --------------------------------------------------------------------------- #
def test_digest_changes_with_the_profile():
    assert digest(load_config()) != digest(load_config(profile="rs"))


def test_digest_depends_on_the_values_not_on_the_name_of_the_profile(tmp_path):
    same_values = _toml(tmp_path, '[thresholds.i18n]\ncontent_languages = ["sr"]\n')
    assert digest(load_config(same_values)) == digest(load_config(profile="rs"))


# --------------------------------------------------------------------------- #
# i18n.lang.mismatch without a profile: not applicable, whatever the page
# --------------------------------------------------------------------------- #
def _english_tag(site):
    site.home.lang = "en-US"


def _short_text(site):
    site.home.lang = "en"
    site.home.text_sample, site.home.text_length = "Kratko.", 7


def _truncated(site):
    site.home.lang = "en"
    site.home.truncated = True


def _cyrillic(site):
    site.home.lang = "de"
    site.home.text_sample = "Добродошли на сајт. Нудимо услуге и производе. " * 20
    site.home.text_length = len(site.home.text_sample)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda s: None, id="ke-clean-serbian-site"),
        pytest.param(_english_tag, id="ke-serbian-content-english-tag"),
        pytest.param(_cyrillic, id="ke-cyrillic-content-german-tag"),
        pytest.param(_short_text, id="ke-too-little-text"),
        pytest.param(_truncated, id="pg-truncated-home"),
    ],
)
def test_mismatch_without_profile_is_not_applicable(change):
    site = clean_site()
    change(site)
    result = run_level(1, site, config=NO_PROFILE)[MISMATCH]
    assert result.status == "not_applicable"
    assert result.reason.code == "no_content_language" and result.reason.evidence == {}


@pytest.mark.parametrize(
    "change, status",
    [
        pytest.param(_english_tag, "finding", id="ke-serbian-content-english-tag"),
        pytest.param(_cyrillic, "finding", id="ke-cyrillic-content-german-tag"),
        pytest.param(_short_text, "unknown", id="ke-too-little-text"),
        pytest.param(_truncated, "unknown", id="pg-truncated-home"),
        pytest.param(lambda s: None, "ok", id="ke-clean-serbian-site"),
    ],
)
def test_mismatch_with_rs_profile_behaves_as_before(change, status):
    site = clean_site()
    change(site)
    assert run_level(1, site)[MISMATCH].status == status


def test_without_profile_missing_and_invalid_still_work():
    site = clean_site()
    site.home.lang = None
    assert run_level(1, site, config=NO_PROFILE)["i18n.lang.missing"].status == "finding"
    site.home.lang = "zxx"
    assert run_level(1, site, config=NO_PROFILE)["i18n.lang.invalid"].status == "finding"


def test_not_applicable_without_profile_does_not_make_partial():
    site = clean_site()
    site.home.lang = "en-US"
    report = analyze(site, NO_PROFILE)
    assert report.status == "scanned" and not report.findings and not report.unknowns
    assert [(n.check_id, n.reason.code) for n in report.not_applicable] == [(MISMATCH, "no_content_language")]


def test_too_little_text_without_profile_is_not_partial_with_rs_it_is():
    """Without detection the length of the text does not matter to the check."""
    site = clean_site()
    _short_text(site)
    assert analyze(site, NO_PROFILE).status == "scanned"
    assert analyze(site, load_config(profile="rs")).status == "partial"


def test_switched_off_check_is_left_out_of_the_unknown_share():
    """Like an unmet requirement, a check the config switched off did not run (ADR-015)."""
    site = clean_site()
    _short_text(site)
    _, without = partial_shares([analyze(site, NO_PROFILE)])
    _, with_rs = partial_shares([analyze(site, load_config(profile="rs"))])
    assert MISMATCH not in without
    assert with_rs[MISMATCH] == 1.0
    assert without["i18n.lang.missing"] == with_rs["i18n.lang.missing"] == 0.0


def test_escalation_follows_the_profile():
    """Escalation does not run the detector; it sees the mismatch finding only when the profile is on."""
    site = clean_site()
    site.home.lang = "en-US"
    rs = load_config(profile="rs")
    with_rs = escalation_reasons(site, list(run_level(1, site).values()), rs)
    without = escalation_reasons(site, list(run_level(1, site, config=NO_PROFILE).values()), NO_PROFILE)
    assert [r.code for r in with_rs] == ["medium_finding"]
    assert without == []


@pytest.mark.parametrize("lang", LANGS)
def test_reason_sentence_says_how_to_turn_detection_on(lang):
    sentence = reason(Reason("no_content_language"), lang)
    assert "--profile rs" in sentence
    assert ("jezika sadržaja" if lang == "sr" else "content language") in sentence


# --------------------------------------------------------------------------- #
# The run records its profile: report.json, HTML header, summary line
# --------------------------------------------------------------------------- #
def test_report_json_records_the_profile():
    for profile, expected in (("rs", "rs"), (None, None)):
        document = to_jsonable(pipeline.recheck(FIXTURES, load_config(profile=profile)))
        jsonschema.validate(document, SCHEMA)
        assert document["profile"] == expected
        assert list(document).index("profile") == list(document).index("config_digest") + 1


def test_schema_rejects_an_empty_profile_name():
    document = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    document["profile"] = ""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, SCHEMA)


@pytest.mark.parametrize(
    "lang, profile, expected",
    [
        pytest.param("sr", "rs", "profil rs", id="ke-sr-rs"),
        pytest.param("sr", None, "bez profila", id="ke-sr-none"),
        pytest.param("en", "rs", "profile rs", id="ke-en-rs"),
        pytest.param("en", None, "no profile", id="ke-en-none"),
    ],
)
def test_html_header_names_the_profile(lang, profile, expected):
    config = load_config(profile=profile)
    page = html_out.render([analyze(clean_site(), config)], config, lang=lang)
    header = page.split('<p class="sub">', 1)[1].split("</p>", 1)[0]
    assert header.endswith(f" · {expected}")


def _findings(out: Path) -> set[tuple[str, str]]:
    document = json.loads((out / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(document, SCHEMA)
    return {(r["domain"], f["check_id"]) for r in document["ranked"] for f in r["findings"]}


def test_recheck_with_and_without_profile_differs_only_in_mismatch(tmp_path, capsys):
    with_rs, without = tmp_path / "rs", tmp_path / "none"
    assert cli.main(["recheck", str(FIXTURES), "--out", str(with_rs), "--profile", "rs"]) == 0
    assert "· profile rs ·" in capsys.readouterr().err
    assert cli.main(["recheck", str(FIXTURES), "--out", str(without)]) == 0
    assert "· no profile ·" in capsys.readouterr().err
    difference = _findings(with_rs) ^ _findings(without)
    assert difference == {("ordinacija.example", MISMATCH)}
    assert difference <= _findings(with_rs)


@pytest.mark.parametrize(
    "arguments, key, expected",
    [
        pytest.param([], 'profile = "rs"', "rs", id="tab-key"),
        pytest.param(["--profile", ""], 'profile = "rs"', None, id="tab-empty-flag-over-key"),
        pytest.param(["--profile", "rs"], "", "rs", id="tab-flag"),
    ],
)
def test_recheck_profile_from_flag_or_config_key(tmp_path, arguments, key, expected):
    config = _toml(tmp_path, key + "\n")
    out = tmp_path / "out"
    assert cli.main(["recheck", str(FIXTURES), "--out", str(out), "--config", str(config), *arguments]) == 0
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["profile"] == expected


# --------------------------------------------------------------------------- #
# Report language: English by default, Serbian with the rs profile, --lang wins
# --------------------------------------------------------------------------- #
def test_report_languages_are_the_message_catalogs():
    assert set(REPORT_LANGUAGES) == set(LANGS)


@pytest.mark.parametrize(
    "arguments, expected",
    [
        pytest.param([], "en", id="tab-default"),
        pytest.param(["--profile", "rs"], "sr", id="tab-profile"),
        pytest.param(["--profile", "rs", "--lang", "en"], "en", id="tab-flag-over-profile"),
        pytest.param(["--lang", "sr"], "sr", id="tab-flag"),
    ],
)
def test_report_language_from_default_profile_or_flag(tmp_path, arguments, expected):
    out = tmp_path / "out"
    assert cli.main(["recheck", str(FIXTURES), "--out", str(out), "--format", "html", *arguments]) == 0
    assert f'<html lang="{expected}">' in (out / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", ["de", "", None], ids=["nv-unknown", "nv-empty", "nv-not-a-string"])
def test_unknown_report_language_in_config_is_an_error(tmp_path, lang):
    value = "[]" if lang is None else f'"{lang}"'
    with pytest.raises(ConfigError, match="report.lang"):
        load_config(_toml(tmp_path, f"[report]\nlang = {value}\n"))


def test_report_language_does_not_change_the_digest(tmp_path):
    assert digest(load_config(_toml(tmp_path, '[report]\nlang = "sr"\n'))) == digest(load_config())


def test_unknown_profile_on_the_command_line_is_a_message_not_a_traceback(tmp_path):
    with pytest.raises(SystemExit, match="configuration error: unknown profile 'xx'; available profiles: rs"):
        cli.main(["recheck", str(FIXTURES), "--out", str(tmp_path), "--profile", "xx"])


@pytest.mark.parametrize("command", ["scan", "recheck", "record"])
def test_every_command_that_reads_the_config_takes_profile(command):
    args = cli.build_parser().parse_args([command, "input", "--out", "out", "--profile", "rs"])
    assert args.profile == "rs"


def test_explain_says_mismatch_needs_a_profile(capsys):
    assert cli.main(["explain", MISMATCH]) == 0
    printed = capsys.readouterr().out
    assert "--profile rs" in printed and "not applicable" in printed
