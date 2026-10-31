"""Which addresses the scanner may open (ADR-006). Pure functions: no network, so mutation
testing covers them too.
"""

from __future__ import annotations

import pytest

from sitetriage import addresses
from sitetriage.config import ConfigError, _validate, load_config


# --------------------------------------------------------------------------- #
# Address classification (pure function)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ip, public",
    [
        pytest.param("172.15.255.255", True, id="gv-172.16-minus"),
        pytest.param("172.16.0.0", False, id="gv-172.16"),
        pytest.param("172.31.255.255", False, id="gv-172.31-end"),
        pytest.param("172.32.0.0", True, id="gv-172.32"),
        pytest.param("100.63.255.255", True, id="gv-100.64-minus"),
        pytest.param("100.64.0.0", False, id="gv-100.64"),
        pytest.param("::ffff:127.0.0.1", False, id="gv-ipv4-in-ipv6"),
        pytest.param("::ffff:8.8.8.8", True, id="ke-public-ipv4-in-ipv6"),
        pytest.param("0.0.0.0", False, id="ke-0/8"),
        pytest.param("10.0.0.5", False, id="ke-10/8"),
        pytest.param("127.0.0.1", False, id="ke-127/8"),
        pytest.param("169.254.169.254", False, id="ke-cloud-metadata"),
        pytest.param("192.168.1.1", False, id="ke-192.168/16"),
        pytest.param("224.0.0.1", False, id="ke-multicast"),
        pytest.param("::1", False, id="ke-ipv6-loopback"),
        pytest.param("fc00::1", False, id="ke-fc00/7"),
        pytest.param("fe80::1%eth0", False, id="ke-fe80/10-with-zone"),
        pytest.param("8.8.8.8", True, id="ke-public-ipv4"),
        pytest.param("2a00:1450:4001:81d::200e", True, id="ke-public-ipv6"),
    ],
)
def test_only_a_global_unicast_address_is_public(ip, public):
    assert addresses.is_public(ip) is public


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("localhost", id="nv-no-port"),
        pytest.param("localhost:port", id="nv-port-not-a-number"),
        pytest.param("user@localhost:80", id="nv-user-name"),
        pytest.param("localhost:80/path", id="nv-path"),
    ],
)
def test_allowed_entry_must_be_host_and_port(entry):
    with pytest.raises(ValueError, match="host:port"):
        addresses.parse_allowed([entry])
    cfg = load_config()
    cfg["net"]["allowed_private"] = [entry]
    with pytest.raises(ConfigError, match="net.allowed_private"):
        _validate(cfg)


def test_allowed_private_is_not_a_list():
    cfg = load_config()
    cfg["net"]["allowed_private"] = "localhost:8123"
    with pytest.raises(ConfigError, match="lista"):
        _validate(cfg)


@pytest.mark.parametrize(
    "domain, problem",
    [
        pytest.param("institucija.example", None, id="ke-name"),
        pytest.param("https://institucija.example", None, id="ke-name-with-scheme"),
        pytest.param("8.8.8.8", "IP address", id="nv-ip-address"),
        pytest.param("http://[::1]/", "IP address", id="nv-ipv6-address"),
        pytest.param("institucija.example:8080", "with a port", id="nv-port"),
        pytest.param(
            "http://institucija.example:x/", "port in the domain is not a number", id="nv-port-not-a-number"
        ),
        pytest.param("admin@institucija.example", "with a user name", id="nv-user-name"),
        pytest.param("http://staging.rs:8123", None, id="ke-explicitly-allowed"),
    ],
)
def test_input_that_bypasses_the_name_is_refused(domain, problem):
    allowed = addresses.parse_allowed(["staging.rs:8123"])
    result = addresses.input_problem(domain, allowed)
    assert (result is None) if problem is None else (problem in result), result
