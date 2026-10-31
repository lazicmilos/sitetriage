# ADR-019: Run duration: who gets level 2, and concurrency chosen per machine

```
Status:  Accepted (duration on the recommended machine not yet measured)
Date:    2026-09-27, 2026-09-28, 2026-10-04, 2026-10-05
Author:  Milos Lazic
Covers:  Z-32 (with BUG-005, BUG-020, O-18; criterion U1 of the v1 specification; risk R-1 of
         the v2 specification)
```

Recorded on 2026-10-31 from `docs/kalibracija.md` (2026-09-24, 2026-09-27, 2026-09-28,
2026-10-04, 2026-10-05), `docs/izvestaj-testiranja-2.md`, `docs/izvestaj-testiranja-3.md`
(§3.5, O-18, owner decision 6 in §6.3), `docs/plan-testiranja.md` §4, `CHANGELOG.md` (2.0.0),
`README.md` and `skener.toml`.

## Context

The tool has had a duration target from the start: a list of 200 domains in at most 15 minutes
(criterion U1 of the v1 specification; Z-32 in v2). Two facts make it hard to keep:

- Level 2 is expensive. Each browser context costs hundreds of MB of RAM, sites load one by one up
  to `load` ([ADR-018](ADR-018-load-time-validity.md)), and since Z-30 they load under a 4.8 Mb/s
  profile ([ADR-010](ADR-010-mrezni-profil.md)). ADR-010 already noted that longer loads lengthen
  level 2 (risk R-1). Level 2 is therefore capped at `escalation.max_level2` = 60 domains; without
  a cap, nearly every site on a 200-domain list goes to level 2 and a run takes an hour.
- Level 1 is polite: one request at a time per site and a 0.5–1 s pause, so it mostly waits.

Which sites get level 2 is decided by an escalation policy (six conditions joined by OR: short raw
text, no `h1` in raw HTML, a finding of at least `medium`, large HTML, uncompressed HTML, slow home
page). Two defects showed that the cap hides problems:

- BUG-005 (IT-SKENER-001): candidates were cut by level-1 score, so sites with score 0 were
  dropped first, although for them level 2 is the only chance to find anything. 9 of 18 cut
  candidates had no level-1 finding and were reported with "0 findings".
- BUG-020 (list B, 2026-10-04): a site without an escalation reason, or beyond the cap, never
  went to the browser. Two of the last 5 ranked sites weighed 4.8 and 4.9 MB but had fast, clean
  HTML. On list B there were 91 candidates for 60 places, so a new escalation reason would not have
  helped.

## Decision

### Level-2 order (2026-09-24, BUG-005)

Within the cap, candidates without a strong level-1
finding go first. A site that already has a strong finding already has a reason to be contacted.

### Level-1 concurrency (owner decision, 2026-09-27)

Run F estimated 200 domains at about
20.5 min, with level 1 alone at about 10.7 min; lowering only `max_level2`, as Z-32 had anticipated,
would have left room for about 25 level-2 domains instead of 60. Instead, level 1 processes 16
domains at once instead of 8 (`http.domain_concurrency`, `http.concurrency`). Politeness towards
each site is unchanged: one request at a time and the same pause. This is a recorded deviation from
Z-32.

### Z-32 met on a fast link (owner decision, 2026-09-28)

Runs G and H on list A, same code:

| | G (mobile hotspot, 17.4 Mb/s) | H (fast link, 107 Mb/s) |
|---|---|---|
| level 1 | 192 s | 168 s |
| level 2 (60 domains) | 763 s | 500 s |
| estimate for 200 domains | 19.1 min | 13.9 min |
| share of domains that exhausted the budget | 20.5 % | 7.8 % |

16 domains at once stays (budget share on the fast link is under the 10 % criterion), and
`max_level2` stays 60.

### Light level 2 (owner decision, 2026-10-04, BUG-020)

Every site with a working home page that has
no place on the full level 2 gets a light level 2: after the full one, without the network profile
and without the load queue. It measures weight, requests, `h1`, `alt` and images. Load time is
`not_applicable` with reason `requires.level2_full` (changed from `unknown` on 2026-10-05, see
[ADR-015](ADR-015-not-applicable-and-partial-causes.md)). The snapshot carries `light`.

### Light-level-2 concurrency per machine (owner decision, 2026-10-05, O-18)

With three contexts
(the same `browser.concurrency` as the full level 2) the estimate for 200 domains became
200 / n × level 1 + full level 2 + (200 − full) × time per light site = 290 + 498 + 140 × 4.2 ≈
1376 s, about 23 min. The full level 2 loads one by one anyway, but the light one is limited exactly
by the number of contexts. The owner's rule: the tool must work on any machine and be faster on a
stronger one.

- The light level 2 picks its number of contexts per machine: one per free GB of memory, at most two
  per CPU core, at most 8 (`browser.light_concurrency = 0`; a value ≥ 1 fixes it). A machine with
  8 GB of RAM ends up with three contexts.
- The full level 2 stays on `browser.concurrency` (3).
- The 15-minute target applies to a recommended machine: 16 GB of RAM and a link of at least
  50 Mb/s. On a weaker machine a run takes longer.

## Consequences

- The duration target on the recommended machine has not been measured. Owner decision 6 of
  2026-10-05: it is measured on the first run from a VPS. Release v2.0.0 did not wait for it.
- Measured so far: light level 2 on list B took 168 s for 40 sites with three contexts
  (2026-10-05) and 139 s for 39 sites with two (2026-10-06, contexts chosen by free memory).
- The duration criterion has to name the machine and the link. The same tool gives 12.5 min or about
  23 min for 200 domains depending on the link, on how many sites go to the browser and on the
  number of contexts (lesson in IT-SKENER-003 §8).
- On a mobile hotspot 16 domains at once share a slow link and more of them exhaust their budget
  (run G, 20.5 %); the 2026-10-06 run over list B therefore used `--concurrency 4`. Temporary DNS
  failures are retried once ([ADR-013](ADR-013-unreachable-after-second-attempt.md)).
- After BUG-020 no ranked site is without level 2: on list B the number of ranked sites without
  level 2 went from 40 to 0, and sites with 0 findings from 8 to 3.
- Light and full level 2 can measure different weights for the same site (O-21: 3 sites changed mode
  between two days, one weighed 26 % more on the light level). The cause is not known; it stays an
  observation for the next cycle.
