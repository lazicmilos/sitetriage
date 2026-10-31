# ADR-018: Load time is reported only when the link cannot distort it: serial loading and a real-link probe

```
Status:  Accepted
Date:    2026-09-27 (Z-31 switch, Z-33), 2026-09-28 (serial loading kept)
Author:  Milos Lazic
Covers:  Z-31, Z-33 (with BUG-006)
```

Recorded on 2026-10-31 from `docs/sr/kalibracija.md` (2026-09-24, 2026-09-27, 2026-09-28,
2026-10-06), `docs/sr/izvestaj-testiranja-100.md` (BUG-006), `docs/sr/izvestaj-testiranja-3.md`,
`CHANGELOG.md` (2.0.0), `skener.toml` and the commit history. Builds on
[ADR-010](ADR-010-mrezni-profil.md) (network profile, Z-30).

## Context

### Shared link (BUG-006)

In the first 100-domain run three browser contexts loaded sites at the
same time and shared one real connection. Measured again one by one, the same sites loaded 1.1–4.6
times faster (median 1.8×); one site took 13.0 s in the run and 2.8 s alone, a `high` finding that
should not exist. The fix was to load each site up to `load` one at a time, while scrolling and the
rest of the measurement stay parallel. After the fix the ratio "in the run / alone" was 0.72–1.24.

### Network profile (Z-30, ADR-010)

Since 2026-09-27 every level-2 context runs under a simulated
4.8 / 1.5 Mb/s, 150 ms link. Each context then has its own simulated link, so serial loading might
no longer be needed (Z-31). But the profile can only slow a connection down, never speed it up.

### First Z-31 experiment (2026-09-27)

It used 10 sites from list A, four runs (parallel with three
contexts, alone, alone, parallel). The real link before each run, measured by downloading 25 MB, was
3.2, 3.3, 4.5 and 1.9 Mb/s, slower than the profile every time. The ratio "in the run / alone" was
0.44–3.68; 1 of 8 and 3 of 9 comparable sites fell in 0.8–1.25. Even the same site alone did not
repeat: one 1.7 MB site loaded once in 4.7 s and once in 20.4 s. The time had been measured at the
speed of a real link that changed minute by minute, so the sentence "on a simulated 4.8 Mb/s
connection" was false and the seconds were overestimated.

## Decision

### Z-31: a switch, default serial

`browser.serial_load` (default `true`) keeps loading one by one;
`false` loads in parallel. The default changes only if an experiment over 10 sites of list A gives a
ratio of 0.8–1.25 for all 10 in both repetitions.

### Z-33: measure the real link before level 2 (2026-09-27)

Once per run, before the first site,
the tool downloads a probe file (`network_profile.probe_url`, at most `probe_max_s` = 5 s, under one
timeout). The measured speed goes into `BrowserSnapshot.link_mbps` and into `environment.link_mbps`
of the JSON report. `perf.load.time` is `unknown`:

- with reason `link_slow` when the link is slower than `min_link_ratio` × profile
  (2 × 4.8 = 9.6 Mb/s);
- with reason `requires.link` when the link was not measured, with one warning in the log. A
  `probe_url` on a private address that `[net] allowed_private` does not list is not opened, and
  counts as not measured (ADR-006).

The ratio is 2 because while one site loads, two others are scrolling (`skener.toml`). Tests never go
to the network: `conftest.py` replaces the probe, and the probe itself is tested against the local
server.

### Serial loading kept (owner decision, 2026-09-28)

Z-31 was repeated from a fast link (real link
280–360 Mb/s): 19 of 20 ratios fell in 0.8–1.25, 15 of them between 0.97 and 1.03. The one outlier
(0.77) was a slower stand-alone measurement, i.e. on the site's side, since interference would push
the ratio above 1. Level 2 for the 10 sites took 41.5 s in parallel and 93–95 s one by one. Still:

- the Z-31 condition requires all 20, and the run-duration target (Z-32,
  [ADR-019](ADR-019-run-duration-and-level2-coverage.md)) was met without parallel loading;
- the link of the machine that runs the scanner is not known in advance. Serial loading gives a
  correct time on any link of 9.6 Mb/s or more (Z-33); parallel loading was verified only on about
  100 Mb/s and more;
- choosing automatically from the measured link would need measurements between 17 and 107 Mb/s,
  which do not exist. That is left for later.

So `browser.serial_load` stays `true`. If parallel loading is ever enabled, `min_link_ratio` must be
at least 3, because three sites would then load at once.

## Consequences

- On a slow connection the load time is `unknown` instead of overestimated. Weight and request count
  are still measured.
- The 9.6 Mb/s threshold held on 2026-10-06: the link before level 2 was 9.7 Mb/s, yet sites
  downloaded up to `load` at 3.8 Mb/s (median; p90 4.3), the same as on 18.6 Mb/s the day before,
  and the median ratio of load times for the same 56 sites was 1.03. The bottleneck was still the
  profile. The ratio stays 2.
- The script that repeated level 2 on list B also measured the link after the full level 2 and
  would have discarded the run if it had dropped below 9.6 Mb/s.
- Serial loading is the largest part of a run's duration: 60 sites loaded one by one at 4.8 Mb/s.
  No link speeds that up.
- `environment.link_mbps` and `requires.link` are part of the 2.0 schema
  ([ADR-011](ADR-011-json-sema.md)); a snapshot without a measured link gives `unknown` for load
  time.
- The exit criterion "time in the run / time alone: 0.8–1.25" applies only if parallel loading is
  enabled; in v2.0.0 it is marked "not applicable".
