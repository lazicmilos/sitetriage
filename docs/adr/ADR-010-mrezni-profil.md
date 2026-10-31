# ADR-010: Level 2 measures under a fixed network profile, without site isolation

```
Status:  Accepted
Date:    2026-09-27
Author:  Milos Lazic
```

Originally written in Serbian; translated for v3.

## Context

Load time depends on the connection it is measured from. A home connection, a server in a data
centre and a customer's machine give different numbers for the same site, so the same site would
get a finding on one machine and not on another. The sentences about seconds already assume a
4.8 Mb/s connection, so the measurement should use the same one (v2 specification SP-SKENER-002;
the ids it uses are decoded in [legacy-references.md](legacy-references.md)).

Chromium accepts a network profile per target: `Network.emulateNetworkConditions` on the page
session. Full Chromium, like a system Chrome, loads an iframe from another site (YouTube, maps) in a
separate process (OOPIF), and that is a separate target which the page profile does not slow down. A
trial on 2026-09-27 confirmed this on Chromium 141: a page with a 600 kB iframe loaded in 274 ms,
and without OOPIF in 1397 ms. Playwright's headless shell keeps the iframe in the same process, so
the problem would stay hidden until `SITETRIAGE_CHROMIUM` was set.

The profile can also be set on each target separately (`Target.setAutoAttach`), but Playwright's
`CDPSession` does not send commands to child sessions. Setting the profile on an iframe only once it
appears comes too late for the iframe's first request.

## Decision

- `[network_profile]` in `sitetriage.toml` (`download_mbps`, `upload_mbps`, `latency_ms`) is the only
  source of speed: both the Chromium profile and the seconds in client sentences come from it.
  `thresholds.perf.mobile_speed_mbps` is removed.
- Before navigation, every level-2 context gets CDP `Network.emulateNetworkConditions`. Throughput
  is in bytes per second: 4.8 Mb/s = 600,000 B/s.
- Chromium is started with `--disable-site-isolation-trials`, so iframes stay in the page's process
  and the profile applies to them too. The test `test_profil_vazi_i_za_iframe_sa_drugog_porekla` uses
  full Chromium and fails without this flag.
- The profile is stored in `BrowserSnapshot.network_profile` and in `environment` of the JSON
  report. `perf.load.time` states it in its sentence ("on a simulated 4.8 Mb/s connection"). A
  snapshot without a profile was measured on the real connection, so load time is `unknown` for it.
- The CPU is not emulated.

## Consequences

- The same site gives the same time on every machine, up to differences in the processor. The
  README says so.
- Site isolation protects one site's data from another site's code in the same process. The scanner
  carries no logins or cookies worth protecting, and every domain gets a new context. If that
  changes (for example, level 2 with a user login in the web phase), this decision is revisited.
- The thresholds `load_ms`, `browser.timeout_s` and `browser.max_seconds_per_domain` were
  calibrated on the real connection. Under the profile, times will be longer, so these thresholds
  are set again from the distribution measured under the profile
  ([ADR-020](ADR-020-threshold-calibration.md)). Longer loading also makes level 2 longer (risk R-1
  of the v2 specification). That is handled by the loading-order decision
  ([ADR-018](ADR-018-load-time-validity.md)) and the run-duration decision
  ([ADR-019](ADR-019-run-duration-and-level2-coverage.md)).
