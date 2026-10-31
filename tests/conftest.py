"""Zajedničko za sve testove.

Alat bez identiteta operatera odbija da skenira. Testovi skeniraju lokalni server
(a `pytest -m live` i prave sajtove), pa im treba identitet; testovi koji proveravaju
baš to odbijanje brišu ga preko `monkeypatch.delenv`.
"""

import asyncio
import functools
import os

import pytest

os.environ.setdefault("SKENER_NAZIV", "skener testovi")
os.environ.setdefault("SKENER_KONTAKT", "test@example.invalid")


@pytest.fixture(scope="session", autouse=True)
def dozvoli_lokalne_servere():
    """Lokalni server je na 127.0.0.1, a skener privatne adrese ne otvara (ADR-006).

    Dozvoljena je tačno adresa svakog `FakeSite`-a koji radi, a ne sve privatne adrese.
    Server napravljen sa `dozvoljen=False` ostaje zabranjen, kao u produkciji. Važi za
    celu sesiju, jer fixture-i na nivou modula podižu servere pre testova.
    """
    from localserver import dozvoljene_adrese

    from sitetriage import addresses

    pravi = addresses.allowlist
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(addresses, "allowlist", lambda config: pravi(config) | dozvoljene_adrese())
        yield


@pytest.fixture(scope="session", autouse=True)
def veza_bez_interneta():
    """Pre nivoa 2 alat meri stvarnu vezu preuzimanjem sa interneta (Z-33), a testovi rade bez
    mreže. Veza je zato uvek „brza"; merenje samo testira se nad lokalnim serverom."""

    async def brza(config: dict) -> float:
        return 100.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sitetriage.fetch.browser.measure_link", brza)
        yield


@functools.cache
def chromium_se_pokrece() -> str | None:
    """Razlog da se testovi sa oznakom `browser` preskoče, ili `None` ako Chromium radi.

    Uvoz nije dovoljan: paket bez odgovarajućeg Chromium-a puca tek na `launch`.
    Tipično posle nadogradnje Playwright-a bez `playwright install` — to je stanje
    okruženja, ne greška u alatu, pa je preskakanje, a ne deset crvenih testova.
    Proba se jednom po sesiji, i to tek kad prvi takav test treba da se pokrene.
    """
    try:
        from playwright import async_api as playwright_api
    except ImportError:
        return "Playwright nije instaliran"

    from sitetriage.config import load_config
    from sitetriage.fetch.browser import _launch_options

    async def probaj() -> None:
        async with playwright_api.async_playwright() as pw:
            browser = await pw.chromium.launch(**_launch_options(load_config()))
            await browser.close()

    try:
        asyncio.run(probaj())
    except playwright_api.Error as exc:
        razlog = str(exc).splitlines()[0]
        return f"Chromium se ne pokreće ({razlog}); pokreni `playwright install chromium`"
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Važi za svaki test sa oznakom `browser`, ne samo za `test_fetch_browser.py`.

    `tryfirst`: preskače se pre fixture-a, jer i fixture (npr. `dva_prolaza`) pokreće browser.
    """
    if item.get_closest_marker("browser") and (razlog := chromium_se_pokrece()):
        pytest.skip(razlog)
