"""Shared by all tests.

Without an operator identity the tool refuses to scan. The tests scan a local server (and
`pytest -m live` scans real sites), so they need an identity; the tests that check that very
refusal remove it with `monkeypatch.delenv`.
"""

import asyncio
import functools
import os

import pytest

os.environ.setdefault("SITETRIAGE_OPERATOR_NAME", "sitetriage tests")
os.environ.setdefault("SITETRIAGE_OPERATOR_CONTACT", "test@example.invalid")


@pytest.fixture(scope="session", autouse=True)
def allow_local_servers():
    """The local server is on 127.0.0.1, and the scanner does not open private addresses (ADR-006).

    Exactly the address of each running `FakeSite` is allowed, not every private address. A
    server created with `allowed=False` stays blocked, as in production. It applies to the
    whole session, because module-level fixtures start servers before the tests run.
    """
    from localserver import allowed_addresses

    from sitetriage import addresses

    real = addresses.allowlist
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(addresses, "allowlist", lambda config: real(config) | allowed_addresses())
        yield


@pytest.fixture(scope="session", autouse=True)
def link_without_internet():
    """Before level 2 the tool measures the real link by downloading from the internet
    (ADR-018), and the tests run without a network. The link is therefore always "fast"; the
    measurement itself is tested against the local server."""

    async def fast(config: dict) -> float:
        return 100.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sitetriage.fetch.browser.measure_link", fast)
        yield


@functools.cache
def chromium_starts() -> str | None:
    """The reason to skip tests marked `browser`, or `None` if Chromium works.

    An import is not enough: a package without the matching Chromium fails only at `launch`.
    Typically after a Playwright upgrade without `playwright install`. That is the state of the
    environment, not a bug in the tool, so the tests are skipped rather than ten of them red.
    It is tried once per session, and only when the first such test is about to run.
    """
    try:
        from playwright import async_api as playwright_api
    except ImportError:
        return "Playwright is not installed"

    from sitetriage.config import load_config
    from sitetriage.fetch.browser import _launch_options

    async def try_launch() -> None:
        async with playwright_api.async_playwright() as pw:
            browser = await pw.chromium.launch(**_launch_options(load_config()))
            await browser.close()

    try:
        asyncio.run(try_launch())
    except playwright_api.Error as exc:
        reason = str(exc).splitlines()[0]
        return f"Chromium does not start ({reason}); run `playwright install chromium`"
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Applies to every test marked `browser`, not only to `test_fetch_browser.py`.

    `tryfirst`: the test is skipped before its fixtures run, because some fixtures (e.g.
    `two_runs`) start the browser too.
    """
    if item.get_closest_marker("browser") and (reason := chromium_starts()):
        pytest.skip(reason)
