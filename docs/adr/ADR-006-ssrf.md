# ADR-006: The scanner does not open private addresses (SSRF protection)

```
Status:  Accepted
Date:    2026-09-25
Author:  Milos Lazic
```

Originally written in Serbian; translated for v3.

## Context

The scanner opens addresses that a user supplies. On the command line that is the operator's own
list, but in a web application a user could enter `localhost`, `10.0.0.5` or `169.254.169.254` and
use the scanner to look inside the server (Server-Side Request Forgery). Checking the URL alone does
not help: a public name can resolve to a private address, it can switch to one between two DNS
queries (DNS rebinding), and a site can redirect to one.

## Decision

A connection is allowed only to a global unicast address (`ipaddress.is_global` and not multicast).
IPv4 wrapped in IPv6 (`::ffff:127.0.0.1`) is judged as IPv4. The only exceptions are `host:port`
pairs listed in `[net] allowed_private`. There is no global switch that turns the protection off.
Address classification is a pure function in `sitetriage/addresses.py`, which mutation testing also
covers.

**Input.** A domain with an IP address, a port or a user name gets no request at all, unless its
`host:port` is explicitly allowed. Such a domain is `failed` with a reason. A name whose last label is
a number (`0177.0.0.1`, `0x7f.1`, `127.1`, `2130706433`) counts as an IP address: a browser reads it
as IPv4 in octal, hex or shortened notation, while httpx refuses it, so its meaning depends on the
parser.

**Level 1.** `httpx` gets its own network backend (`_PublicAddresses` in `fetch/http.py`). It resolves
the name, checks every address and opens the TCP connection to exactly the address it checked. SNI
and `Host` still carry the domain name. The check sits where the connection is opened, so it covers
every redirect as well, and DNS rebinding does not get through. A blocked domain is `failed` with
the reason "address is not public", not "not working": the site may work, we just chose not to open
it.

`httpx` 0.28 has no public parameter for the network backend, so it is set through the internal
field `_pool._network_backend`. If a new version renames it, the tool refuses to run
(`RuntimeError`) instead of silently losing the protection. The client does not read
`HTTP(S)_PROXY` from the environment, because a proxy resolves the name itself and would bypass the
check. The link probe before level 2 (`network_profile.probe_url`, ADR-018) is a request too, so it
uses the same transport (`public_transport` in `fetch/http.py`), the same allowlist and no proxy. A
refused probe sends no request: the link is not measured and load time is `unknown`.

**Level 2.** `context.route("**/*")` resolves the name for every browser request and lets it through
only if all of its addresses are allowed, because Chromium picks which one to use on its own.
Schemes other than `http` and `https` are refused, and so is a name that cannot be resolved. The
context has `service_workers="block"`, because `route` does not see requests sent by a service
worker.

## Limits of level 2

Level 2 is the first line of defence. It cannot be the only one:

1. **Redirects.** `route` sees only the first address, not the target of a redirect. Verified on
   Playwright 1.56: an allowed page that answers 302 to a private port takes Chromium to that port.
   The test `test_browser_does_not_follow_redirect_to_private_address` is marked
   `xfail(strict=True)`; when Playwright starts seeing redirects, the test fails and this item is
   removed.
2. **Time between the check and the connection.** Chromium resolves the name itself, so there is a
   window between our check and its connection in which the DNS answer can change.
3. **WebSocket.** `route` does not intercept WebSocket connections.

Level 2 runs only on domains that passed level 1, so an attacker has to control a public site. A
web application in production must therefore also have an **egress filter at the network level**:
the worker process may open public addresses only.

**Owner decision (2026-09-25):** the limits of level 2 are handled by the egress filter in the web
phase, as a mandatory part of production. A local proxy for Chromium, which would check every
connection inside the tool itself, including redirects and WebSocket, is not built: it is serious
work and it changes the time measurement, while a network-level filter closes all three gaps at
once.

## Consequences

- Tests open a local server on `127.0.0.1`. `conftest.py` allows exactly the addresses of the
  servers that are running, and a server created with `allowed=False` stays forbidden, as in
  production.
- Staging with a port works only with explicit permission:
  `[net] allowed_private = ["staging.example:8123"]`.
- `route` disables the browser cache and adds per-request handling. The context is new for every
  domain anyway, so there was no cache to begin with, but load time may grow slightly. This is
  measured in the calibration on list A.
