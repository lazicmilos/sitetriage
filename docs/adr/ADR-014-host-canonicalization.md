# ADR-014: Host canonicalization is two ordinary checks, paid for with a 19-request budget

```
Status:  Accepted
Date:    2026-09-26 (decision), 2026-09-27 (accepted after run E)
Author:  Milos Lazic
Covers:  Z-26 (with O-12; risk R-2 of the v2 specification)
```

Recorded on 2026-10-31 from `docs/sr/kalibracija.md` (entries of 2026-09-26 and 2026-09-27),
`docs/sr/izvestaj-testiranja-3.md` §6.1, `CHANGELOG.md` (2.0.0), `skener.toml` and the commit history.

## Context

The check registry had an `optional` flag and a `Context.host_canonicalization` field that no check
used (IT-SKENER-002, O-12). They were reserved for a host canonicalization check that was planned
for v1 and never built. A site that opens on several addresses without redirecting to one of them is
a common problem on small sites, and it is easy to verify.

Checking it costs requests. The level-1 budget at the time was 16 requests and 40 s per domain:
home 1 + robots 1 + soft-404 probes 2 + sitemaps 4 + sample 7 = 15, plus one spare.

## Decision

- After `robots.txt` and before the sitemap, level 1 fetches the remaining three addresses of the
  final origin (`http`/`https` × with and without `www`) and records them in
  `SiteSnapshot.host_variants`.
- Two new level-1 checks:
  - `infra.https.redirect.missing`: the site works on https with a valid certificate, and `http://`
    on the same host answers 200 without a redirect.
  - `infra.host.duplicate`: the site opens both with and without `www`, and neither address
    redirects to the other. Severity is `low` when the canonical on all of them points to the same
    origin.
- `infra.host.duplicate` looks only at hosts (`www` and no `www`). A site that works on both
  `http://` and `https://` of one host reports only `infra.https.redirect.missing`, so that one
  problem does not produce two findings (owner decision, 2026-09-26).
- A variant with a TLS error, or one for which no request was sent, gives `unknown`. A variant with
  a temporary DNS failure is also `unknown`, because it is not known whether that address serves the
  site. A DNS error or a connection that gets no answer is different: such an address serves nothing.
  An input with an IP address or a port has no variants.
- The budget becomes 19 requests instead of 16: home 1 + robots 1 + host variants 3 + probes 2 +
  sitemaps 4 + sample 7 = 18, budget 19. The time budget stays 40 s.
- `optional`, the matching `check()` argument and `Context.host_canonicalization` are deleted.
- The politeness key (one request at a time and a pause per site) becomes the host without a leading
  `www.`. Once the tool fetches both variants, `www.x.example` and `x.example` would otherwise get
  two requests at the same time.
- Acceptance condition: on list A the number of domains that exhaust their budget may grow by at
  most 2 compared with run C (6).

### Follow-up after run D (owner decision, 2026-09-27)

Run D failed the condition: 21 domains exhausted the budget (19 of them on the 40 s limit, after
7–17 of 19 requests), and some got 1 sampled page instead of 8. The cause: a variant followed its
redirect to the end, and on those domains 57 of 63 variants ended on the home page that had already
been fetched, so the home page was downloaded three more times, at 3–10 s each on slow hosting.

The owner chose to fix the cause, not the budget. A variant follows the redirect step by step and
stops before the home page; it takes the status and canonical from the home page. In run D all 207
variants that ended on the home page had the same status and canonical as the home page, so findings
do not change. The budget stays 19 requests and 40 s.

## Consequences

- Run E (2026-09-27): 9 domains exhausted the budget (8 allowed); budget share 8.9 % (criterion
  < 10 %). One site was returning 500 on its sitemap, probes and 4 of 7 pages; every 500 is retried
  once, so it used all 19 requests in 19 s. Four were slow sites at about 3 s per page, which already
  used 35–43 s of 40 in run C; the three variant requests with their politeness pauses pushed them
  over. This is the cost that risk R-2 of the v2 specification anticipated. Those sites still got
  3–7 pages. The owner declared Z-26 met and F2 closed. In run H 7 domains exhausted the budget.
- BUG-017: the address list in the `infra.host.duplicate` sentence must be hosts (`x.example`,
  `www.x.example`), the same unit as the count. `http` without a redirect stays the
  `infra.https.redirect.missing` finding.
- Snapshots taken before this change have `host_variants = None`, and both checks are `unknown` for
  them. The hand-written fixture generator had to start producing variants (all three redirect to
  the final address), otherwise every fixture domain was `partial`.
- Removing `optional` is a breaking change listed in `CHANGELOG.md` 2.0.0.
