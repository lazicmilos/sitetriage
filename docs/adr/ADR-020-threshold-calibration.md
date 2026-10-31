# ADR-020: Thresholds come from percentiles of a calibration list, then are frozen and validated on a second list

```
Status:  Accepted
Date:    2026-09-28 (Z-50), 2026-10-03 to 2026-10-06 (Z-51)
Author:  Milos Lazic
Covers:  Z-50, Z-51 (with Z-23, O-1, O-9, O-14; test-plan risk R5)
```

Recorded on 2026-10-31 from `docs/sr/kalibracija.md`, `docs/sr/plan-testiranja.md` (§3, §4, §7),
`docs/sr/izvestaj-testiranja-2.md`, `docs/sr/izvestaj-testiranja-3.md` (§3.4, §3.5), `docs/sr/kvalitet.md`,
`skener.toml`, `README.md` and the commit history.

## Context

A threshold that fires on almost every site does not rank anything. The first 100-domain run showed
it: 55 of 60 measured sites were above the 1.5 MB weight threshold, and weight was the leading
finding for 15 of the first 20 (IT-SKENER-001, O-1). From then on thresholds were set from the
measured distribution: first 5 / 10 / 20 MB on decompressed bytes, then 3 / 5 / 8 MB on transferred
bytes (median 2.8, p75 5.2, p90 8.1 MB; 2026-09-24).

In v2 two measurement changes moved the distributions again. Since Z-24 only what starts before
`load` counts ([ADR-016](ADR-016-weight-until-load.md)), so weight and request count are lower.
Since Z-30 load time is measured on a slower simulated link ([ADR-010](ADR-010-mrezni-profil.md)), so
it is longer: under the profile `perf.load.time` fired on 42 of 60 sites.

Calibrating and validating on the same list would tune the thresholds to that list (test-plan risk
R5: "calibration on A spills over to B").

## Decision

### Two lists

List A is the same 100 domains used in IT-SKENER-001 and IT-SKENER-002; thresholds
are calibrated on it. List B is 100 new domains of the same type with no overlap with A; the exit
criteria are measured on it. After calibration on A the thresholds are frozen until the measurement
on B is complete, "because tuning towards B would make it a new A". A defect found on B goes through
the bug procedure, and after the fix the criteria are measured again on B (Z-51). The lists and
per-domain results stay out of the repository (`rad/`).

### Z-50: percentiles of list A (owner decision, 2026-09-28)

Input is run H (list A, fast link,
107 Mb/s), without a new scan. `scripts/distribution.py` prints the distribution from the snapshots.
60 sites were measured under the profile, 58 reached `load`, and 2 timeouts were counted as 25 s.

| | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|
| weight up to `load`, without video | 2.2 MB | 3.6 MB | 7.3 MB | 8.7 MB | 13.4 MB |
| requests up to `load` | 57 | 87 | 130 | 185 | 310 |
| time to `load` under the profile | 5.6 s | 9.3 s | 15.2 s | 22.1 s | ≥ 25 s |

Thresholds are the rounded p50, p75 and p90, the same procedure as in v1. For checks with only two
levels the same percentile gives the same severity as for weight: p50 is `medium`, p75 is `high`.

| Threshold | Before | After | Findings in run H, before → after |
|---|---|---|---|
| weight (medium / high / critical) | 3 / 5 / 8 MB | 2 / 4 / 7 MB | 20 → 32 |
| requests (medium / high) | 100 / 150 | 60 / 90 | 11 → 28 |
| time (medium / high) | 4 / 8 s | 6 / 9 s | 42 → 25 |

Other values decided in the same step:

- `browser.timeout_s` stays 25 s: p95 is 22.1 s, a reserve of about 3 s.
- `browser.max_seconds_per_domain` stays 60 s. The level-2 duration per domain was not in the
  snapshots, so it is now recorded (`elapsed_ms`); it was first measured on list A from GitHub
  Actions (p50 8.8 s, p95 26.6 s, max 31.4 s) and reached 31.9 s on list B.
- The network profile stays 4.8 / 1.5 Mb/s and 150 ms. 150 ms is the latency Lighthouse uses for
  mobile measurement. Page loads send mostly short requests, so upload speed is not calibrated.
- `seo.canonical.duplicate` (Z-23): a canonical that differs from the page only in `http`/`https` or
  a leading `www.` is not a foreign canonical. Without this, the sentence would show the owner their
  own home page as "another address". The share limits `canonical_share = { high = 0.4,
  critical = 0.6 }` stay at their initial values from the specification, because list A has only one
  real case (share 0.25, `medium`).

After a `recheck` with the new thresholds the first 10 were the same sites as in run H; one rose from
8th to 1st because its weight became `critical`.

### Z-51: validation on list B

The system test on B measures the exit criteria of the test plan.
It must run from an address in the country and on a fast link: a run of list A from GitHub Actions
put 6 working sites into "not working" because their hosting refuses data-centre addresses (O-14,
[ADR-013](ADR-013-unreachable-after-second-attempt.md)), and timing needs a real link of at least
15 Mb/s.

## Consequences

- Freezing is verifiable: the configuration digest (`config_digest` `d989300e88ef`) was the same in
  the `recheck` after Z-50 and in every report over list B.
- On B: `partial` because of budget 9.0 % (2026-10-03) and 9.1 % (2026-10-06); `unknown` per check at
  most 5.0 % and 5.1 %; no crash and no WARNING or ERROR in the log; no non-working site in the
  ranking. In the manual check of the first 10 no finding was wrong (0 of 89, then 0 of 96;
  [ADR-021](ADR-021-manual-verification.md)).
- BUG-019 changed the level-2 User-Agent after calibration. The Z-50 thresholds stay: they were
  calibrated with the old UA, and the new one gives the same or lower numbers, so a threshold can
  only produce fewer findings. A re-check on list A was planned for the next run over A; it has not
  been done (IT-SKENER-003 §1).
- Lists A and B are small businesses and associations from one country. For other industries and
  markets the distribution may differ, so calibration should be repeated on the operator's own lists
  (`docs/sr/kvalitet.md`). `skener recheck --config` over saved snapshots exists for this.
- Unclear from the record: why weight has a third (`critical`) level at p90 while requests and time
  have only two. The documents state only "the same procedure as in v1".
