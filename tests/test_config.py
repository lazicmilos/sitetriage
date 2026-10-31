import os
from pathlib import Path

import pytest

from sitetriage import __version__
from sitetriage.config import ConfigError, _validate, digest, get, load_config, multiplier, user_agent


def test_loads_the_default_config():
    cfg = load_config()
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_user_config_is_merged_not_replaced(tmp_path):
    override = tmp_path / "mine.toml"
    override.write_text("[thresholds.i18n]\nmin_text_length = 100\n", encoding="utf-8")
    cfg = load_config(override)
    assert get(cfg, "thresholds.i18n.min_text_length") == 100
    # the other thresholds from the same section survive the merge
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_multipliers_and_fallback_to_other():
    cfg = load_config()
    assert multiplier(cfg, "hotel", "social") == 1.5
    assert multiplier(cfg, "restaurant", "perf") == 1.5
    assert multiplier(cfg, "healthcare", "a11y") == 1.5
    assert multiplier(cfg, "nonexistent-industry", "seo") == 1.0


def test_missing_key_fails_and_is_named():
    cfg = load_config()
    with pytest.raises(ConfigError, match="thresholds.perf.not_there"):
        get(cfg, "thresholds.perf.not_there")


def test_partial_multiplier_does_not_break_the_table(tmp_path):
    """Merging is what keeps the other categories when the user overrides one."""
    override = tmp_path / "mine.toml"
    override.write_text("[industry_multipliers.hotel]\nseo = 9.9\n", encoding="utf-8")
    cfg = load_config(override)
    assert multiplier(cfg, "hotel", "seo") == 9.9
    assert multiplier(cfg, "hotel", "social") == 1.5


def test_incomplete_multiplier_table_fails():
    """A real boundary: someone deletes a row in the default config itself during calibration."""
    broken = {
        "severity_points": {"critical": 40, "high": 20, "medium": 8, "low": 3},
        "industry_multipliers": {"hotel": {"seo": 1.2}},
    }
    with pytest.raises(ConfigError, match="industry_multipliers.hotel.social"):
        _validate(broken)


def test_old_operator_section_fails_and_names_the_new_keys(tmp_path):
    """3.0 renamed `[identitet]` to `[operator]` (ADR-012); merged and ignored, it would only
    surface later as a missing identity, with no hint why."""
    override = tmp_path / "old.toml"
    override.write_text('[identitet]\nnaziv = "Web studio Primer"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[identitet\] was renamed to \[operator\].*naziv → name"):
        load_config(override)


def test_multipliers_for_an_old_industry_name_fail(tmp_path):
    """`[industry_multipliers.restoran]` from before 3.0 would be merged and never used."""
    override = tmp_path / "old.toml"
    override.write_text("[industry_multipliers.restoran]\nperf = 2.0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="industry_multipliers.restoran: unknown industry; known: hotel"):
        load_config(override)


# --------------------------------------------------------------------------- #
# Operator identity: the User-Agent represents whoever scans, not the author of the tool.
# Different operators run the tool, so otherwise everyone would scan with the author's email.
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_environment(monkeypatch):
    monkeypatch.delenv("SITETRIAGE_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("SITETRIAGE_OPERATOR_CONTACT", raising=False)


def test_default_config_has_no_identity(no_environment):
    with pytest.raises(ConfigError, match=r"\[operator\] name"):
        user_agent(load_config())


@pytest.mark.parametrize(
    "name, contact",
    [
        pytest.param("", "kontakt@primer.rs", id="nv-no-name"),
        pytest.param("Web studio Primer", "", id="nv-no-contact"),
        pytest.param("   ", "kontakt@primer.rs", id="nv-only-spaces"),
    ],
)
def test_incomplete_identity_fails(no_environment, name, contact):
    cfg = load_config()
    cfg["operator"] = {"name": name, "contact": contact}
    with pytest.raises(ConfigError, match=r"\[operator\] name"):
        user_agent(cfg)


def test_user_agent_carries_the_operator_not_the_author(no_environment):
    cfg = load_config()
    cfg["operator"] = {"name": "Web studio Primer", "contact": "kontakt@primer.rs"}
    # Exactly what the operator wrote, nothing more: neither the tool's author nor a default contact.
    assert user_agent(cfg) == f"SiteTriage/{__version__} (+kontakt@primer.rs; Web studio Primer)"


def test_identity_from_the_environment_takes_precedence(monkeypatch):
    """For Docker: compose.yaml passes `SITETRIAGE_OPERATOR_NAME` and `SITETRIAGE_OPERATOR_CONTACT`."""
    monkeypatch.setenv("SITETRIAGE_OPERATOR_NAME", "Iz okruženja")
    monkeypatch.setenv("SITETRIAGE_OPERATOR_CONTACT", "env@primer.rs")
    cfg = load_config()
    cfg["operator"] = {"name": "Iz fajla", "contact": "fajl@primer.rs"}
    ua = user_agent(cfg)
    assert "Iz okruzenja" in ua and "env@primer.rs" in ua  # ASCII: ž → z


# Error guessing: the operator writes the name however comes naturally, and an HTTP header may
# carry only ASCII. A name with "Š" or in Cyrillic would otherwise break every request.
@pytest.mark.parametrize(
    "name, expected",
    [
        pytest.param("Web studio Šumadija", "Web studio Sumadija", id="pg-latin-diacritics"),
        pytest.param("Đorđe Čačić", "Djordje Cacic", id="pg-dj-and-c"),
        pytest.param("Ђорђе Јовановић", "Djordje Jovanovic", id="pg-cyrillic"),
        pytest.param("Студио Љубљана", "Studio Ljubljana", id="pg-cyrillic-lj"),
        pytest.param("Studio — Primer", "Studio Primer", id="pg-dash-dropped"),
        pytest.param("Studio 😀 Primer", "Studio Primer", id="pg-emoji-dropped"),
    ],
)
def test_identity_is_transliterated_to_ascii(no_environment, name, expected):
    cfg = load_config()
    cfg["operator"] = {"name": name, "contact": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert ua.isascii(), ua
    assert expected in ua


def test_identity_cannot_inject_a_new_header(no_environment):
    """A newline in the name would start a new header in the HTTP request."""
    cfg = load_config()
    cfg["operator"] = {"name": "Studio\r\nX-Napad: 1", "contact": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert "\r" not in ua and "\n" not in ua


def test_identity_of_only_non_ascii_characters_fails(no_environment):
    cfg = load_config()
    cfg["operator"] = {"name": "😀😀", "contact": "kontakt@primer.rs"}
    with pytest.raises(ConfigError, match=r"\[operator\] name"):
        user_agent(cfg)


# --------------------------------------------------------------------------- #
# Boundary 0 in the config: a semaphore with zero slots lets no one through, and the run
# would stall forever without a single message.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key",
    ["http.concurrency", "http.domain_concurrency", "browser.concurrency", "http.max_requests_per_domain"],
)
@pytest.mark.parametrize(
    "value, valid",
    [
        pytest.param(-1, False, id="nv-negative"),
        pytest.param(0, False, id="gv-0"),
        pytest.param(1, True, id="gv-1"),
    ],
)
def test_concurrency_and_budget_must_be_positive(tmp_path, key, value, valid):
    section, field = key.split(".")
    override = tmp_path / "mine.toml"
    override.write_text(f"[{section}]\n{field} = {value}\n", encoding="utf-8")
    if valid:
        assert get(load_config(override), key) == value
    else:
        with pytest.raises(ConfigError, match=key):
            load_config(override)


@pytest.mark.parametrize(
    "value, valid",
    [
        pytest.param("-1", False, id="nv-negative"),
        pytest.param("true", False, id="nv-boolean"),
        pytest.param("0", True, id="gv-0-per-machine"),
        pytest.param("1", True, id="gv-1"),
    ],
)
def test_light_level2_context_count_is_an_integer_from_zero(tmp_path, value, valid):
    """0 means "chosen per machine" (ADR-019), so unlike the other concurrency settings zero is valid."""
    override = tmp_path / "mine.toml"
    override.write_text(f"[browser]\nlight_concurrency = {value}\n", encoding="utf-8")
    if valid:
        assert get(load_config(override), "browser.light_concurrency") == int(value)
    else:
        with pytest.raises(ConfigError, match="browser.light_concurrency"):
            load_config(override)


def test_invalid_toml_fails_and_names_the_file(tmp_path):
    override = tmp_path / "broken.toml"
    override.write_text("[http\nconcurrency = 8\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="broken.toml"):
        load_config(override)


def test_missing_config_file_fails(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    "value, valid",
    [
        pytest.param(0, False, id="gv-0"),
        pytest.param(-5, False, id="nv-negative"),
        pytest.param(0.5, True, id="gv-just-above-0"),
        pytest.param(40, True, id="ke-default"),
    ],
)
def test_time_budget_must_be_positive(tmp_path, value, valid):
    override = tmp_path / "mine.toml"
    override.write_text(f"[http]\nmax_seconds_per_domain = {value}\n", encoding="utf-8")
    if valid:
        assert get(load_config(override), "http.max_seconds_per_domain") == value
    else:
        with pytest.raises(ConfigError, match="max_seconds_per_domain"):
            load_config(override)


# --------------------------------------------------------------------------- #
# BUG-04: a `sitetriage.toml` in the working directory is an ordinary user file. It is never read
# implicitly, and passed with --config it is merged over the packaged defaults like any other file.
# --------------------------------------------------------------------------- #
OPERATOR_ONLY = '[operator]\nname = "Example Web Studio"\ncontact = "hello@studio.example"\n'


def _packaged_defaults() -> Path:
    from importlib.resources import files

    return Path(str(files("sitetriage").joinpath("sitetriage.toml")))


def _complete_copy_with_one_change() -> str:
    text = _packaged_defaults().read_text(encoding="utf-8")
    changed = text.replace("html_size_kb = 500", "html_size_kb = 1")
    assert changed != text
    return changed


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(OPERATOR_ONLY + "[thresholds.perf]\nhtml_size_kb = 1\n", id="partial"),
        pytest.param(None, id="complete-copy"),
    ],
)
@pytest.mark.parametrize(
    "passed",
    [pytest.param(False, id="ke-not-passed-is-not-read"), pytest.param(True, id="ke-passed-is-merged")],
)
def test_sitetriage_toml_in_the_working_directory_is_read_only_through_config(
    tmp_path, monkeypatch, content, passed
):
    from sitetriage.config import default_config_path

    baseline = digest(load_config())
    (tmp_path / "sitetriage.toml").write_text(content or _complete_copy_with_one_change(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert default_config_path() == _packaged_defaults()
    cfg = load_config("sitetriage.toml" if passed else None)
    # Merged over the defaults, so nothing the file leaves out goes missing.
    assert get(cfg, "severity_points.critical") == 40
    if passed:
        assert get(cfg, "thresholds.perf.html_size_kb") == 1
        assert digest(cfg) != baseline
    else:
        assert get(cfg, "thresholds.perf.html_size_kb") == 500
        assert digest(cfg) == baseline


def test_the_packaged_defaults_passed_as_config_change_nothing():
    from sitetriage.config import default_config_path

    assert digest(load_config(default_config_path())) == digest(load_config())


def test_without_a_default_config_it_fails_and_says_what_to_do(monkeypatch):
    monkeypatch.setattr("sitetriage.config.CONFIG_NAME", "nonexistent.toml")
    with pytest.raises(ConfigError, match="Reinstall SiteTriage"):
        load_config()


def test_default_config_ships_inside_the_package(tmp_path, monkeypatch):
    """A wheel from PyPI has no repository around it: the defaults must come from the package."""
    from importlib.resources import files

    from sitetriage.config import default_config_path

    monkeypatch.chdir(tmp_path)
    packaged = files("sitetriage").joinpath("sitetriage.toml")
    assert packaged.is_file()
    assert default_config_path() == Path(str(packaged))
    assert get(load_config(), "http.max_body_kb") == 10240


@pytest.mark.skipif("MUTANT_UNDER_TEST" in os.environ, reason="mutmut copies only part of the repository")
def test_default_config_is_package_data_and_has_no_second_copy():
    """Without package data the wheel would not contain the file; a second copy at the
    repository root would drift from the one that is installed."""
    import tomllib

    root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "sitetriage.toml" in pyproject["tool"]["setuptools"]["package-data"]["sitetriage"]
    assert "sitetriage/sitetriage.toml" in pyproject["tool"]["mutmut"]["also_copy"]
    assert not (root / "sitetriage.toml").exists(), "the default config lives in sitetriage/ only"


@pytest.mark.parametrize("section", ["severity_points", "industry_multipliers"])
def test_a_whole_section_is_missing(section):
    cfg = load_config()
    del cfg[section]
    with pytest.raises(ConfigError, match=section):
        _validate(cfg)


# --------------------------------------------------------------------------- #
# Config digest: `diff` uses it to tell whether a difference comes from the site or the thresholds
# --------------------------------------------------------------------------- #
def test_digest_does_not_depend_on_identity_and_concurrency():
    first, second = load_config(), load_config()
    second["operator"] = {"name": "Drugi studio", "contact": "drugi@primer.rs"}
    second["http"]["concurrency"] = second["http"]["domain_concurrency"] = 2
    second["browser"]["concurrency"] = 1
    second["browser"]["light_concurrency"] = 5
    second["browser"]["executable_path"] = "/usr/bin/chromium"
    assert digest(first) == digest(second)
    assert len(digest(first)) == 64


@pytest.mark.parametrize(
    "key, value",
    [
        pytest.param(("thresholds", "perf", "html_size_kb"), 501, id="threshold"),
        pytest.param(("severity_points", "critical"), 41, id="points"),
        pytest.param(("industry_multipliers", "hotel", "social"), 1.4, id="multiplier"),
        pytest.param(("escalation", "max_level2"), 59, id="level2-limit"),
    ],
)
def test_digest_changes_when_a_threshold_changes(key, value):
    cfg = load_config()
    before = digest(cfg)
    *path, last = key
    section = cfg
    for part in path:
        section = section[part]
    section[last] = value
    assert digest(cfg) != before


# --------------------------------------------------------------------------- #
# BUG-06: every value is checked against the type of its packaged default, and values that would
# crash a run or silently invert it are rejected with the key and the value.
# --------------------------------------------------------------------------- #
def _one_value(tmp_path: Path, section: str, line: str) -> tuple[Path, str]:
    """A config file that sets one key, and the dotted name of that key."""
    override = tmp_path / "mine.toml"
    override.write_text(f"[{section}]\n{line}\n", encoding="utf-8")
    return override, f"{section}.{line.split(' =')[0]}"


@pytest.mark.parametrize(
    "section, line, shown",
    [
        pytest.param("severity_points", 'high = "lots"', "'lots'", id="nv-points-text"),
        pytest.param("severity_points", "high = true", "True", id="nv-points-boolean"),
        pytest.param("severity_points", "high = -20", "-20", id="nv-points-negative"),
        pytest.param("severity_points", "high = 0", "0", id="gv-points-0"),
        pytest.param("http", "delay_ms = [500]", "[500]", id="nv-delay-one-number"),
        pytest.param("http", "delay_ms = [-1000, -500]", "[-1000, -500]", id="nv-delay-negative"),
        pytest.param("http", "delay_ms = [1000, 500]", "[1000, 500]", id="nv-delay-reversed"),
        pytest.param("http", 'delay_ms = ["a", "b"]', "'a'", id="nv-delay-text"),
        pytest.param("http", "delay_ms = 500", "500", id="nv-delay-not-a-list"),
        pytest.param("http", "delay_ms = { min = 0 }", "{'min': 0}", id="nv-delay-table"),
        pytest.param("http", "timeout_total_s = 0", "0", id="gv-total-timeout-0"),
        pytest.param("http", "timeout_connect_s = 0", "0", id="gv-connect-timeout-0"),
        pytest.param("http", "timeout_read_s = -1", "-1", id="nv-read-timeout-negative"),
        pytest.param("browser", "timeout_s = 0", "0", id="gv-browser-timeout-0"),
        pytest.param("browser", "drain_timeout_s = 0", "0", id="gv-drain-0"),
        pytest.param("browser", "max_seconds_per_domain = 0", "0", id="gv-level2-budget-0"),
        pytest.param("thresholds.perf", "image_ratio = -1", "-1", id="nv-ratio-negative"),
        pytest.param("thresholds.perf", "image_ratio = 0", "0", id="gv-ratio-0"),
        pytest.param("thresholds.perf", "image_ratio = nan", "nan", id="nv-nan"),
        pytest.param("thresholds.i18n", "cyrillic_ratio = 1.5", "1.5", id="nv-share-above-1"),
        pytest.param("sitemap", "sample_size = 0", "0", id="gv-sample-0"),
        pytest.param("sitemap", "sample_size = 1", "1", id="gv-sample-home-page-only"),
        pytest.param("sitemap", "sample_size = 2.5", "2.5", id="nv-sample-fraction"),
        pytest.param("industry_multipliers.hotel", "perf = -5", "-5", id="nv-multiplier-negative"),
        pytest.param("thresholds.qa", "console_errors = -1", "-1", id="nv-negative-count"),
        pytest.param(
            "thresholds.perf",
            "page_weight_mb = { medium = 5.0, high = 4.0, critical = 7.0 }",
            "'medium': 5.0",
            id="nv-tiers-out-of-order",
        ),
        pytest.param(
            "thresholds.perf", "load_ms = { medium = 6000, high = 6000 }", "'high': 6000", id="gv-tiers-equal"
        ),
        pytest.param("thresholds", "perf = 5", "5", id="nv-number-instead-of-a-table"),
        pytest.param("operator", "name = 5", "5", id="nv-number-instead-of-text"),
        pytest.param("browser", 'serial_load = "yes"', "'yes'", id="nv-text-instead-of-bool"),
    ],
)
def test_invalid_value_fails_and_names_the_key_and_the_value(tmp_path, section, line, shown):
    override, key = _one_value(tmp_path, section, line)
    with pytest.raises(ConfigError) as error:
        load_config(override)
    assert key in str(error.value) and shown in str(error.value), str(error.value)


@pytest.mark.parametrize(
    "section, line, expected",
    [
        pytest.param("http", "delay_ms = [0, 0]", [0, 0], id="gv-delay-0"),
        pytest.param("http", "delay_ms = [500, 500]", [500, 500], id="gv-delay-min-equals-max"),
        pytest.param("http", "delay_ms = [0.5, 1.5]", [0.5, 1.5], id="ke-delay-fractions"),
        pytest.param("http", "timeout_total_s = 2.5", 2.5, id="ke-fraction-of-a-second"),
        pytest.param("http", "max_crawl_delay_s = 0", 0, id="gv-crawl-delay-cap-0"),
        pytest.param("severity_points", "high = 1", 1, id="gv-points-1"),
        pytest.param("thresholds.perf", "image_ratio = 3", 3, id="ke-integer-for-float"),
        pytest.param("thresholds.i18n", "cyrillic_ratio = 1", 1, id="gv-share-1"),
        pytest.param("sitemap", "sample_size = 2", 2, id="gv-sample-home-page-and-one"),
        pytest.param("industry_multipliers.hotel", "perf = 0", 0, id="gv-multiplier-0"),
        pytest.param(
            "thresholds.perf",
            "page_weight_mb = { medium = 1, high = 2.5, critical = 3 }",
            {"medium": 1, "high": 2.5, "critical": 3},
            id="ke-tiers-in-order",
        ),
    ],
)
def test_valid_value_is_accepted(tmp_path, section, line, expected):
    override, key = _one_value(tmp_path, section, line)
    assert get(load_config(override), key) == expected


def test_packaged_defaults_and_profiles_pass_their_own_validation():
    from sitetriage.config import available_profiles

    for name in ["", *available_profiles()]:
        load_config(profile=name)
