"""A whole run without the command line: the CLI and the web worker call the same code."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from localserver import FakeSite, Response, html

from sitetriage import pipeline
from sitetriage.config import load_config
from sitetriage.inputs import InputError
from sitetriage.models import DomainInput

FIXTURES = Path(__file__).parent / "fixtures"


def fast_config() -> dict:
    config = load_config()
    config["http"]["delay_ms"] = [0, 0]
    config["http"]["second_attempt_after_s"] = 0
    return config


# --------------------------------------------------------------------------- #
# Without a network
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("targets", "level", "error"),
    [
        pytest.param([], "auto", InputError, id="nv-empty-list"),
        pytest.param([DomainInput("primer.rs")], "3", ValueError, id="nv-unknown-level"),
    ],
)
def test_scan_refuses_invalid_input(targets, level, error):
    with pytest.raises(error):
        asyncio.run(pipeline.scan(targets, load_config(), level=level))


def test_recheck_without_snapshots_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="no snapshot found"):
        pipeline.recheck(tmp_path, load_config())


def test_result_carries_summary_and_time():
    result = pipeline.recheck(FIXTURES, load_config())
    statuses = ("scanned", "partial", "failed", "unreachable", "excluded")
    assert set(result.summary) == {*statuses, "partial_budget", "partial_unknown"}
    every = result.ranked + result.unreachable + result.not_scanned
    assert sum(result.summary[s] for s in statuses) == len(every), "recheck has no excluded domains"
    assert result.started_at.endswith("Z") and result.finished_at >= result.started_at
    assert result.duration_s["total"] >= 0


def test_error_in_on_event_does_not_bring_down_the_run(caplog):
    """A progress bar that crashes must not lose a domain whose snapshot is already on disk."""

    def crashes(_event):
        raise RuntimeError("progress bar")

    result = pipeline.recheck(FIXTURES, load_config(), on_event=crashes)
    assert len(result.ranked) == sum(1 for p in FIXTURES.iterdir() if p.is_dir())
    assert "on_event failed" in caplog.text


# --------------------------------------------------------------------------- #
# Real Chromium against the local server
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def two_runs():
    """Two runs, one after the other, in the same event loop, as in a long-lived worker."""
    config = fast_config()
    events: list[list] = [[], []]

    async def main(targets):
        return [
            await pipeline.scan(targets, config, level="2", on_event=events[i].append) for i in range(2)
        ]

    with FakeSite() as first, FakeSite() as second:
        targets = [DomainInput(first.base_url), DomainInput(second.base_url)]
        results = asyncio.run(main(targets))
    return targets, results, events


@pytest.mark.browser
def test_two_runs_in_the_same_loop(two_runs):
    targets, results, _ = two_runs
    for result in results:
        assert sorted(r.domain for r in result.ranked) == sorted(t.domain for t in targets)
        assert all(r.level2_ran for r in result.ranked)
        assert set(result.duration_s) == {"level1", "level2", "level2_light", "total"}
        assert result.environment["chromium"], "the Chromium version level 2 was measured with"


@pytest.mark.browser
def test_site_over_the_cap_gets_light_level_2():
    """BUG-020: a 4.8 MB page with fast, clean HTML had no reason for level 2, so the report showed
    it with "0 findings", and its weight was never measured."""
    config = fast_config()
    config["escalation"]["max_level2"] = 0
    with FakeSite() as site:
        result = asyncio.run(pipeline.scan([DomainInput(site.base_url)], config))
    report = result.ranked[0]
    unknowns = {u.check_id: u.reason.code for u in report.unknowns}
    not_applicable = {n.check_id: n.reason.code for n in report.not_applicable}
    assert report.level2_ran
    assert not_applicable.get("perf.load.time") == "requires.level2_full"
    assert not {"perf.load.time", "perf.page.weight", "seo.h1.missing"} & set(unknowns)
    assert set(result.duration_s) == {"level1", "level2", "level2_light", "total"}


@pytest.mark.browser
def test_event_for_every_finished_domain(two_runs):
    targets, _, events = two_runs
    for run_events in events:
        assert [e.phase for e in run_events] == ["level1"] * 4 + ["level2"] * 4, "level 1, then level 2"
        for phase in ("level1", "level2"):
            every = [e for e in run_events if e.phase == phase]
            assert every[0].kind == "phase_started" and every[-1].kind == "phase_finished"
            domains = [e for e in every if e.kind == "domain_finished"]
            assert sorted(e.domain for e in domains) == sorted(t.domain for t in targets)
            assert [e.done for e in domains] == [1, 2] and all(e.total == 2 for e in every)
            assert all(e.status for e in domains)


@pytest.mark.browser
def test_cancelled_run_closes_the_browser_and_keeps_finished_snapshots(tmp_path, monkeypatch):
    from playwright.async_api import BrowserType

    launched = []
    real_launch = BrowserType.launch

    async def launch(self, **kwargs):
        browser = await real_launch(self, **kwargs)
        launched.append(browser)
        return browser

    monkeypatch.setattr(BrowserType, "launch", launch)

    async def main(targets):
        run = asyncio.current_task()

        def cancel_when_first_finishes_level_2(event):
            if event.phase == "level2" and event.kind == "domain_finished":
                run.cancel()

        await pipeline.scan(
            targets,
            fast_config(),
            level="2",
            snapshot_dir=tmp_path,
            on_event=cancel_when_first_finishes_level_2,
        )

    # After loading, the slow site requests a resource whose body arrives only after 20 s, so its
    # measurement is still running when the fast one finishes and the run is cancelled.
    slow_page = html("Spora", body="<script>fetch('/kasno')</script>")
    with FakeSite() as fast, FakeSite(
        extra={"/": Response(slow_page), "/kasno": Response(b"x" * 1000, stall=20)}
    ) as slow:
        targets = [DomainInput(fast.base_url), DomainInput(slow.base_url)]
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(main(targets))

    assert launched and not any(b.is_connected() for b in launched), "the browser must be closed"
    assert len(list(tmp_path.glob("*/site.json"))) == 2, "level 1 finished for both domains"
    assert len(list(tmp_path.glob("*/browser.json"))) == 1, "level 2 finished only for the fast one"


# --------------------------------------------------------------------------- #
# Excluded domains (opt-out)
# --------------------------------------------------------------------------- #
def test_excluded_domain_gets_no_request(monkeypatch):
    """The local servers share the host 127.0.0.1, so the second domain in the list is a name without DNS
    records."""
    import socket

    from sitetriage.fetch import http

    async def no_records(host, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(http, "_resolve", no_records)
    with FakeSite() as excluded:
        targets = [DomainInput(excluded.base_url), DomainInput("drugi.test")]
        result = asyncio.run(
            pipeline.scan(targets, fast_config(), level="1", excluded=["127.0.0.1"])
        )
    assert excluded.requests == [], "an excluded domain must not get a single request"
    every = result.ranked + result.unreachable + result.not_scanned
    assert [r.domain for r in every] == ["drugi.test"], "the report does not name the excluded domain"
    assert result.summary["excluded"] == 1
