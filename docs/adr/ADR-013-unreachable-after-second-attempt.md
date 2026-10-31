# ADR-013: A site is "unreachable" only when that is certain, and only after a second attempt

```
Status:  Accepted
Date:    2026-09-27
Author:  Milos Lazic
Covers:  Z-20 (with O-5, O-8, O-14)
```

Recorded on 2026-10-31 from `docs/kalibracija.md`, `docs/izvestaj-testiranja-100.md`,
`docs/izvestaj-testiranja-2.md`, `docs/izvestaj-testiranja-3.md`, `CHANGELOG.md` (2.0.0),
`skener.toml` and `tests/test_unreachable.py`. The date is the date the requirement was accepted
(run D on list A). The repository does not record when the decision itself was taken.

## Context

In v1 the two ways a site can fail to open were reported differently. A domain with no DNS record
got `infra.dns.unresolved` with severity `critical`. A domain whose server did not answer was
`failed` with no finding at all. Both mean "the site does not open" (IT-SKENER-001, O-5).

Because the DNS finding was `critical`, dead domains ranked high. In the 100-domain run six domains
without DNS sat between places 8 and 13. A dead site can be a lead, but it can also be a business
that closed (IT-SKENER-002, O-8). Its suggested text also cannot be the same one used for a working
site with problems.

A single failed attempt does not prove that a site is down. Real runs also showed a third case that
looks like "down" but is not: a temporary DNS failure (EAI_AGAIN). Over a mobile hotspot it hit
24 of 100 domains in run F, all of which had worked in run E.

## Decision

- New domain status `unreachable` and new finding `infra.unreachable` (`critical`, category
  `infra`). `infra.dns.unresolved` is deleted.
- An `unreachable` domain is not ranked. It goes to a separate "not working" section of the report,
  with its own suggested text. `rank()` ranks only `scanned` and `partial`; every other domain has
  `rank` 0. The JSON report has separate `unreachable` and `not_scanned` lists.
- `unreachable` is assigned only when the state is certain:
  - the name does not exist in DNS (NXDOMAIN) or exists but has no address (NODATA), or
  - no TCP connection could be established on either https or http.
- The certain state must hold on two attempts. A site that looks down after the first attempt goes
  to the end of the level-1 queue and gets a second attempt with a fresh budget, no earlier than
  `http.second_attempt_after_s` (60 s) after the first. The rest of the list keeps running in the
  meantime.
- Everything else is `failed` with a reason and goes to the "not scanned" section: a temporary DNS
  failure, an interrupted TLS handshake, any HTTP response (for example 403 or 503), an address that
  is not public (SSRF protection, [ADR-006](ADR-006-ssrf.md)). The site may work; the tool just did
  not see it. A connection that drops after it was established is not "unreachable" either: the
  server is there.
- A temporary DNS failure is retried once, on level 1 and in the level-2 address check (owner
  decision, 2026-09-27).
- A domain excluded by the operator gets the separate status `excluded` and no request at all.

The decision table lives in `tests/test_unreachable.py` (`test_unreachable_only_when_certain`).

## Consequences

- Run D on list A (2026-09-27): 7 domains in "not working" (6 DNS, 1 no response). All 7 were
  confirmed outside the tool with a DNS query and `curl` on https and http. Three sites answering
  403 or 429 went to "not scanned", not to "not working"; for two of them `curl` got 200 and the
  tool got 403, i.e. bot protection. Every ranked domain had received an HTTP response. The
  requirement was declared met.
- The list depends on where the scan runs from (O-14). A run of list A from GitHub Actions
  (2026-09-28) put 13 domains in "not working" instead of 7. Six new ones refused connections on 443
  and 80 in both attempts; five of them were at the same hosting provider, and from a home address
  five of the six answered. The hosting drops connections from data centres outside the country,
  and to the tool that looks exactly like a dead server, so the suggested text would tell the owner
  that the site is down. Decision: the validation run on list B (Z-51) runs from an address in the
  country. For a hosted web version or a VPS outside the country this remains an open risk.
- These are breaking changes, listed in `CHANGELOG.md` 2.0.0: removed `infra.dns.unresolved`, new
  statuses `unreachable` and `excluded`, `rank` 0 for unranked domains, the DNS error kind split into
  `dns_nxdomain`, `dns_nodata`, `dns_temporary` and `dns`, and `no_connection` for a TCP connection
  that was never established.
- A run takes at least `second_attempt_after_s` longer when any domain needs a second attempt, but
  other domains are processed during the wait.
