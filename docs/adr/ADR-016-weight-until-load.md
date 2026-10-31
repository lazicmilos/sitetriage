# ADR-016: Page weight and request count are transferred bytes up to the `load` event, without video

```
Status:  Accepted
Date:    2026-09-26 (decision), 2026-09-28 (acceptance condition met)
Author:  Milos Lazic
Covers:  Z-24 (with O-2, O-10, O-13, BUG-016)
```

Recorded on 2026-10-31 from `docs/sr/kalibracija.md` (entries of 2026-09-24, 2026-09-26, 2026-09-27
and 2026-09-28), `docs/sr/izvestaj-testiranja-100.md`, `docs/sr/izvestaj-testiranja-2.md`,
`CHANGELOG.md` (2.0.0) and `README.md`.

## Context

Level 2 reports how heavy the home page is and how many requests it makes, and these numbers go into
the sentence for the site owner. They have to be repeatable, and they have to mean what the sentence
says. Three problems surfaced on real sites:

- Decompressed bytes (BUG-016): the recorder summed decompressed response bodies. JavaScript and
  CSS travel compressed, so one site showed 25.3 MB while 3.8 MB was transferred; two others went
  from 49.4 to 7.4 MB and from 32.7 to 3.4 MB. The sentence says "transfers X MB".
- Video (O-2, corrected by O-13): a video downloads for as long as the measurement allows: one
  site transferred 77 MB of video in one run and 39 MB in another. The first example given for this
  in IT-SKENER-001 (8.5 MB once, 26.9 MB the other time) turned out to have no video bytes at all;
  that difference came from scripts and styles loaded after `load` and from decompressed bytes.
- What arrives after `load` (O-10): the same site made 179 requests in one run and 281 in the
  next (+57 %). The counter summed everything until network idle, scrolling and waiting for bodies,
  and after `load` come analytics, chat widgets and lazy images, as many as the measurement window
  happens to catch.

## Decision

- Weight is transferred bytes (`responseBodySize` from `request.sizes()`), not the decompressed
  body (BUG-016, 2026-09-24).
- Video does not count toward the weight threshold; the sentence states it separately (O-2).
- The threshold and the client sentence count only requests **started before `load`**. The body of
  such a request counts even when it arrives after `load` (Z-24, 2026-09-26). The total including
  what came after `load` appears only in the technical sentence and in JSON.
- When `load` is not reached, weight is `unknown`: a measure "up to load" without `load` is
  incomplete, so even a large number is not a claim.
- The level-2 snapshot has `requests_at_load`, `bytes_at_load`, `bytes_by_type_at_load` and
  `unmeasured_at_load`. For 1.x snapshots both checks are `unknown`.
- The thresholds (3 / 5 / 8 MB and 100 / 150 requests at the time) stay until they are recalibrated
  on the new distribution ([ADR-020](ADR-020-threshold-calibration.md), Z-50), even though they had
  been calibrated on totals.
- Acceptance condition: 10 sites from list A, two measurements each, weight and request count up to
  `load` differ by at most 10 % on at least 9 of 10.

## Consequences

- Acceptance took three measurements:
  - 2026-09-26, without a network profile, two pairs: 6 of 7 and 5 of 6 comparable sites within
    10 %; the rest timed out or failed on DNS. One site deviated 13 % and 17 % systematically: the
    first run of each pair came after a ten-minute pause, and the warmed-up server let one 540 kB
    image start before `load`. That is the site's behaviour near the `load` boundary, not noise a
    rule can remove.
  - 2026-09-27, under the network profile ([ADR-010](ADR-010-mrezni-profil.md)): 8 of 8 comparable
    sites within 10 % (largest difference 8.7 %); two were not comparable because they timed out on
    a slow link. The owner accepted Z-24 on 8 of 8 and asked for a re-check from a fast link.
  - 2026-09-28, fast link: 10 of 10 within 10 %, largest difference 5.7 %. The condition is met
    formally as well.
- This became a v2 exit criterion: "repeatability of weight and request count up to `load`: ≤ 10 %
  on ≥ 9 of 10 sites".
- Known limitation, not fixed: every level-2 request is intercepted (SSRF protection,
  [ADR-006](ADR-006-ssrf.md)), and Playwright then reports a request only when it reaches the network
  layer. A `fetch` or XHR that does not hold `load` and starts in the last milliseconds before it is
  sometimes seen after `load` (3 times in 15 locally under CPU load; it also failed once in CI). The
  error moves weight and request count down, so it cannot create false findings. It is the first
  suspect if deviations near `load` show up again.
- Under these rules the old thresholds no longer matched the distribution; they were recalibrated in
  Z-50.
