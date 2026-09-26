"""Zajedničko za sve testove.

Alat bez identiteta operatera odbija da skenira. Testovi skeniraju lokalni server
(a `pytest -m live` i prave sajtove), pa im treba identitet; testovi koji proveravaju
baš to odbijanje brišu ga preko `monkeypatch.delenv`.
"""

import os

import pytest

os.environ.setdefault("SKENER_NAZIV", "skener testovi")
os.environ.setdefault("SKENER_KONTAKT", "miloslazic458@gmail.com")


@pytest.fixture(scope="session", autouse=True)
def dozvoli_lokalne_servere():
    """Lokalni server je na 127.0.0.1, a skener privatne adrese ne otvara (ADR-006).

    Dozvoljena je tačno adresa svakog `FakeSite`-a koji radi, a ne sve privatne adrese.
    Server napravljen sa `dozvoljen=False` ostaje zabranjen, kao u produkciji. Važi za
    celu sesiju, jer fixture-i na nivou modula podižu servere pre testova.
    """
    from localserver import dozvoljene_adrese

    from skener import addresses

    pravi = addresses.allowlist
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(addresses, "allowlist", lambda config: pravi(config) | dozvoljene_adrese())
        yield
