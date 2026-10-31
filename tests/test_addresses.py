"""Koje adrese skener sme da otvori (ADR-006). Čiste funkcije: bez mreže, pa ih pokriva i
mutaciono testiranje.
"""

from __future__ import annotations

import pytest

from sitetriage import addresses
from sitetriage.config import ConfigError, _validate, load_config


# --------------------------------------------------------------------------- #
# Klasifikacija adresa (čista funkcija)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ip, javna",
    [
        pytest.param("172.15.255.255", True, id="gv-172.16-minus"),
        pytest.param("172.16.0.0", False, id="gv-172.16"),
        pytest.param("172.31.255.255", False, id="gv-172.31-kraj"),
        pytest.param("172.32.0.0", True, id="gv-172.32"),
        pytest.param("100.63.255.255", True, id="gv-100.64-minus"),
        pytest.param("100.64.0.0", False, id="gv-100.64"),
        pytest.param("::ffff:127.0.0.1", False, id="gv-ipv4-u-ipv6"),
        pytest.param("::ffff:8.8.8.8", True, id="ke-javna-ipv4-u-ipv6"),
        pytest.param("0.0.0.0", False, id="ke-0/8"),
        pytest.param("10.0.0.5", False, id="ke-10/8"),
        pytest.param("127.0.0.1", False, id="ke-127/8"),
        pytest.param("169.254.169.254", False, id="ke-metapodaci-oblaka"),
        pytest.param("192.168.1.1", False, id="ke-192.168/16"),
        pytest.param("224.0.0.1", False, id="ke-multicast"),
        pytest.param("::1", False, id="ke-ipv6-loopback"),
        pytest.param("fc00::1", False, id="ke-fc00/7"),
        pytest.param("fe80::1%eth0", False, id="ke-fe80/10-sa-zonom"),
        pytest.param("8.8.8.8", True, id="ke-javna-ipv4"),
        pytest.param("2a00:1450:4001:81d::200e", True, id="ke-javna-ipv6"),
    ],
)
def test_samo_globalna_unicast_adresa_je_javna(ip, javna):
    assert addresses.is_public(ip) is javna


@pytest.mark.parametrize(
    "unos",
    [
        pytest.param("localhost", id="nv-bez-porta"),
        pytest.param("localhost:port", id="nv-port-nije-broj"),
        pytest.param("korisnik@localhost:80", id="nv-korisnicko-ime"),
        pytest.param("localhost:80/putanja", id="nv-putanja"),
    ],
)
def test_dozvola_mora_biti_host_i_port(unos):
    with pytest.raises(ValueError, match="host:port"):
        addresses.parse_allowed([unos])
    cfg = load_config()
    cfg["net"]["allowed_private"] = [unos]
    with pytest.raises(ConfigError, match="net.allowed_private"):
        _validate(cfg)


def test_dozvola_nije_lista():
    cfg = load_config()
    cfg["net"]["allowed_private"] = "localhost:8123"
    with pytest.raises(ConfigError, match="lista"):
        _validate(cfg)


@pytest.mark.parametrize(
    "domen, problem",
    [
        pytest.param("institucija.example", None, id="ke-ime"),
        pytest.param("https://institucija.example", None, id="ke-ime-sa-semom"),
        pytest.param("8.8.8.8", "IP adresa", id="nv-ip-adresa"),
        pytest.param("http://[::1]/", "IP adresa", id="nv-ipv6-adresa"),
        pytest.param("institucija.example:8080", "portom", id="nv-port"),
        pytest.param("http://institucija.example:x/", "port u domenu nije broj", id="nv-port-nije-broj"),
        pytest.param("admin@institucija.example", "korisničkim imenom", id="nv-korisnicko-ime"),
        pytest.param("http://staging.rs:8123", None, id="ke-izricito-dozvoljen"),
    ],
)
def test_ulaz_koji_zaobilazi_ime_se_odbija(domen, problem):
    dozvoljeno = addresses.parse_allowed(["staging.rs:8123"])
    rezultat = addresses.input_problem(domen, dozvoljeno)
    assert (rezultat is None) if problem is None else (problem in rezultat), rezultat
