# Changelog

This file lists the changes that someone who uses the tool or reads its output will notice. Versions
follow semver: a change that breaks compatibility (a domain status, a `check_id`, the shape of a
finding, the JSON) raises the major version.

## Unreleased

The project is open-sourced under the name SiteTriage, under the MIT license.

### Breaking changes (3.0)

The public interface is now English, with no aliases for the old names. The complete old → new
mapping is in [ADR-012](docs/adr/ADR-012-english-public-interface.md).

- The package, the distribution and the command are `sitetriage` instead of `skener`
  (`sitetriage scan`, `sitetriage recheck`, `pip install 'sitetriage[browser]'`). The Docker Compose
  service and image are `sitetriage`, and the logger names in JSON log lines are `sitetriage`,
  `sitetriage.fetch` and `sitetriage.browser`.
- The default config file is `sitetriage.toml` instead of `skener.toml`, with comments in English.
- The default config ships inside the package as `sitetriage/sitetriage.toml`, so a wheel installed
  from PyPI finds its defaults; before, they were found only in the working directory or at the
  repository root. There is no `sitetriage.toml` at the repository root any more: change defaults
  in `sitetriage/sitetriage.toml`, or keep your changes in a `--config` file that is merged over
  them. A complete `sitetriage.toml` in the working directory still replaces the defaults.
- `[identitet]` with `naziv`, `kontakt` and `izuzeti` is now `[operator]` with `name`, `contact` and
  `exclude_file`. A config that still has `[identitet]` fails and names the new keys. The
  `http.user_agent` placeholders are `{version}`, `{contact}` and `{name}`.
- Environment variables: `SKENER_NAZIV` → `SITETRIAGE_OPERATOR_NAME`, `SKENER_KONTAKT` →
  `SITETRIAGE_OPERATOR_CONTACT`, `SKENER_CHROMIUM` → `SITETRIAGE_CHROMIUM`, `SKENER_LIVE_CSV` →
  `SITETRIAGE_LIVE_CSV`, `SKENER_UID`/`SKENER_GID` → `SITETRIAGE_UID`/`SITETRIAGE_GID`.
- Industry values in the input CSV, in `[industry_multipliers.*]` and in the reports: `restoran` →
  `restaurant`, `zdravstvo` → `healthcare`, `institucija` → `institution`, `ostalo` → `other`
  (`hotel`, `ecommerce` and `b2b` are unchanged). An empty or unknown value still falls back to
  `other`. Multipliers for an unknown industry now fail instead of being ignored. Snapshots from
  before 3.0 are mapped to the new values when `recheck` reads them.
- `report.json` follows the new schema `sitetriage/schema/report-3.json` (`schema_version` `3.0`);
  `report-2.json` is removed. Every evidence key of findings and reasons is English (for example
  `stranica` → `page` or `page_count`, `uzorak` → `sample`, `prag` → `threshold`, `bajtova` →
  `bytes`), and so are the Serbian evidence codes: `source` is `raw_html` or `rendered` instead of
  `sirovi_html` or `nivo2`, the `infra.host.duplicate` variant is `same_canonical` instead of
  `isti_canonical`, and a TLS error without a message is `unknown` instead of `nepoznata`. The same
  keys appear in `evidence_json` in `findings.csv`. Field names, `check_id`s, reason codes and CSV
  columns are unchanged, and the Serbian and English sentences are word for word the same.
- `config_digest` changes, because the industry multiplier tables are renamed.
- The working folder for lists and results is `work/` instead of `rad/`; Docker Compose mounts it
  as `/work` instead of `/rad`.
- Operator-facing text is English: CLI help, log lines, errors, and the free-text details stored in
  snapshots and shown in reports (for example a budget that ran out or an address that is not
  public). Client-facing sentences are unchanged in both languages.
- The live test list (`SITETRIAGE_LIVE_CSV`) uses the column `expected` instead of `ocekivano`,
  and `clean` instead of `cist` for the control clean site.
- The scripts are `scripts/metrics.py`, `scripts/distribution.py` (`--with-domains` instead of
  `--sa-domenima`) and `scripts/mutation.py`.
- The HTML report is titled `SiteTriage — izveštaj` / `SiteTriage — report`.
- A domain with no usable name is stored under `snapshots/unknown-domain/` instead of
  `snapshots/nepoznat-domen/`.
- The User-Agent starts with `SiteTriage/` instead of `MlazicSiteScanner/`, on level 1 and at the
  end of the browser UA on level 2. If you filter logs or make exceptions by the old name, change
  them.

### Changed

- In the report, the text that comes with each site is a "suggested text", not a "draft email": it
  can serve for a message, a call or a contact form. The text itself is the same.
- The documentation is in English. The Serbian test reports, calibration log, test plan and quality
  review are kept unchanged under `docs/sr/`; the real-site verification procedure and the manual
  check form are now `docs/real-site-verification.md` and `docs/manual-check-form.md`.

### Fixed

- When robots.txt also lists sitemaps of other domains (one robots.txt for a whole chain of sites),
  only this site's sitemaps are read. The others used up the limit of 4 files before this site's
  sub-sitemaps, so a site with a correct sitemap got the finding `infra.sitemap.missing`, and the
  scanner sent requests to domains that were not on the list. A foreign sitemap is still read when
  it is the only one listed (BUG-027).
- A sitemap with a blank line before `<?xml` (a common fault of WordPress plugins) is no longer
  rejected as invalid XML, so a site with such a sitemap does not get `infra.sitemap.missing`
  (BUG-028).
- Duplicate title, description and canonical count a page once even when two sampled addresses lead
  to it (for example, a language address that redirects to the home page). The page count in the
  sentence was higher than the real one (BUG-029).
- Oversized images count the same image once even when it repeats on the page (cloned slides in a
  slider), with the largest estimated waste. The image count and the waste in kB were too high, and
  the waste was sometimes larger than the whole page: on one site 7,011 kB instead of 2,923 kB. On a
  real run over 249 domains, 5 of 91 `perf.img.oversized` findings no longer cross the threshold
  (BUG-030).
- A response body is read only up to `http.max_body_kb` (10 MB) after decompression, a `.xml.gz`
  sitemap up to `sitemap.max_kb`, and a whole request takes at most `http.timeout_total_s`: a gzip
  bomb, an endless body or a slow body no longer eats memory or stalls the run. A truncated home
  page is `unknown` for the HTML checks.

## 2.0.0 — 2026-10-06

The v2 exit criteria from the [test plan](docs/sr/plan-testiranja.md) are met
([IT-SKENER-003](docs/sr/izvestaj-testiranja-3.md)). The commands `skener diff` and
`skener outcomes` are not in this release.

Package, module and setting names in this section are the 2.x names (`skener`, `[identitet]`); see
[ADR-012](docs/adr/ADR-012-english-public-interface.md) for the 3.0 names. Quoted log and report
texts are given in Serbian, as the tool printed them, with an English gloss.

### Breaking changes

Every such change is recorded here in the same commit in which it is made.

- The reason for `unknown` and the reason for escalation are no longer sentences but
  `Reason(code, evidence)`, in the model and in the JSON (`unknowns[].reason`,
  `escalation_reasons[]`). The sentence is built by `skener.messages.reason(razlog, lang)`, so
  reasons in an English report are now in English.
- `Finding` no longer has `message_client` or `message_tech`. The sentence is built by
  `skener.messages.render(finding, lang)` at display time, and the finding gets `variant`
  ([ADR-009](docs/adr/ADR-009-katalog-poruka.md)). The `message_client` column in `findings.csv`
  stays.
- Finding evidence is data only. The composite forms `uz_video`, `preuzimanja`, `greske_tekst`,
  `kopije`, `stranice`, `naslovi` and `od_slika` are gone. `uzorak` is a code (`sitemap`, `links`,
  `none`), a missing encoding is `null` instead of "nema" ("none"), and the redirect `lanac`
  (chain) is a list of URLs instead of text with arrows.
- Private and special addresses are no longer opened (SSRF, [ADR-006](docs/adr/ADR-006-ssrf.md)).
  A domain with an IP address, a port or a user name is `failed` without a single request, unless
  its `host:port` is listed in `[net] allowed_private`. Level 1 no longer reads `HTTP(S)_PROXY`.
- `CheckSpec` no longer has the templates `message_template` and `tech_template`, and `check()`
  does not accept `message` or `tech`. The module `skener.checks.srpski` moved to
  `skener.messages.sr`.
- `infra.dns.unresolved` is removed. A site that does not open even on the second attempt gets the
  finding `infra.unreachable` and the status `unreachable`, and goes to the "Not working" list
  instead of the ranking. An excluded domain has the new status `excluded`.
  `rank()` ranks only `scanned` and `partial`, and other domains have `rank` 0. The JSON has the
  lists `unreachable` and `not_scanned`, and the domain report has the field `reason` (why it is
  `failed`).
- A check has a fourth state, `not_applicable`, with a mandatory reason. The domain report has a
  `not_applicable` list in the same shape as `unknowns`, but it does not make the domain `partial`.
- The `dns` error kind in the snapshot is split into `dns_nxdomain`, `dns_nodata` (the name exists
  but has no address), `dns_temporary` and `dns` (other DNS errors). A TCP connection that was not
  established is `no_connection`.
- `CheckSpec` no longer has `optional`, `check()` does not accept it, and `Context` has no
  `host_canonicalization`. No check used them; host canonicalization is now an ordinary check.
- `thresholds.perf.mobile_speed_mbps` is removed. The speed is now
  `network_profile.download_mbps`, and the same value goes into the measurement and into the
  sentences. The old key in your own TOML is silently ignored.
- `perf.load.time` requires a snapshot taken with the network profile. A level-2 snapshot made
  before it was measured on the real connection, so its time is `unknown`
  (`requires.network_profile`). The same goes for a snapshot without a measured real link
  (`requires.link`, [ADR-018](docs/adr/ADR-018-load-time-validity.md)). The JSON `environment` has
  the required fields `network_profile` and `link_mbps` (`null` when level 2 did not run).

### Added

- Level 2 records the page's title, description and canonical after JavaScript (`dom.title`,
  `dom.meta_description`, `dom.canonical`). Level 1 reads them from raw HTML, and Google executes
  JavaScript, so on a site that sets them by script `seo.*.missing` would be false. The checks do not
  use them yet: first we measure how many such sites there are.
- A network profile for level 2. Every page is measured on the simulated connection from
  `[network_profile]` (4.8 Mb/s down, 1.5 Mb/s up, 150 ms latency), so the same site gives the same
  time on every machine. The profile is in the level-2 snapshot (`network_profile`) and in
  `environment` of the JSON report, and the `perf.load.time` sentence states it. Chromium runs
  without site isolation, so that the profile also applies to an iframe from another site
  ([ADR-010](docs/adr/ADR-010-mrezni-profil.md)).
- Real-link measurement before level 2. Once per run the tool downloads a probe file
  (`network_profile.probe_url`, for at most `probe_max_s` seconds), and the measured speed goes into
  the snapshot (`link_mbps`) and into `environment` of the JSON report. When the link is slower than
  `min_link_ratio` × the profile, `perf.load.time` is `unknown` (`link_slow`), because the profile can
  only slow things down and the time would be overstated. A snapshot without a measured link gives
  `unknown` (`requires.link`), with one warning in the log
  ([ADR-018](docs/adr/ADR-018-load-time-validity.md)).
- The level-2 snapshot records the duration of level 2 for the domain (`elapsed_ms`), without
  waiting in the load queue: the same time that `browser.max_seconds_per_domain` limits. The script
  `scripts/distribution.py` prints, from the snapshots, the distribution of weight, request count and
  time to `load`, the level-2 duration and the canonical findings, for threshold calibration
  ([ADR-020](docs/adr/ADR-020-threshold-calibration.md)).
- The switch `browser.serial_load` (default `true`). With `false`, sites on level 2 load in parallel
  instead of one by one. Under the network profile each context has its own simulated connection, so
  an experiment checks whether the serial loading from BUG-006 is still needed
  ([ADR-018](docs/adr/ADR-018-load-time-validity.md)).
- Host canonicalization. After `robots.txt` the tool fetches the remaining three addresses of the
  final origin (`http`/`https` × with and without `www`) and records them in
  `SiteSnapshot.host_variants`. Two new checks: `infra.https.redirect.missing` (the site works on
  https, and `http://` on the same host answers 200 without a redirect) and `infra.host.duplicate`
  (the site opens both with and without `www`, and neither address redirects to the other; `low`
  when the canonical on all of them points to the same origin). The budget per domain is 19 requests
  instead of 16. An input with an IP address or a port has no variants.
- The cause of `partial`: the domain report has `partial_causes` (`budget`, `unknown`), the summary
  counts them separately, and the JSON and HTML give the budget share among working domains and the
  `unknown` share per check (`budget_share`, `unknown_share`).
- A JSON report `report.json` with a schema version (`skener/schema/report-2.json`), a configuration
  digest and the environment. `--format` writes it by default next to the HTML and CSV.
- The level-2 snapshot records the Chromium version it was measured with.
- Excluded domains: `[identitet] izuzeti` or `--exclude FILE`, one domain per line, with all
  subdomains. An excluded domain gets no request at all; the report shows only their number (status
  `excluded` in the summary).
- Reports in Serbian and English: `--lang sr|en` for `scan` and `recheck`. `skener explain` prints
  the sentences in both languages.
- The whole run lives in the module `skener.pipeline`, so the web application calls it the same way
  the command line does ([ADR-008](docs/adr/ADR-008-pipeline.md)).
- The log has a progress counter during the run ("nivo 1: 43/200 gotovo", that is "level 1: 43/200
  done").
- A site that looks down after the first attempt goes to the end of the level-1 queue and gets a
  second attempt, with a fresh budget, no earlier than `http.second_attempt_after_s` (60 s) after the
  first.
- The HTML report has the sections "Not working", with its own draft email, and "Not scanned", with
  the reason and the number of excluded domains.
- When the sitemap lists fewer addresses than the sample needs, the sample is topped up with links
  from the home page. The snapshot records the internal links of the home page, and level 2 also
  the links from the rendered DOM.
- An error or warning in the domain list names the row it is on, the way Excel shows it ("red 3:
  domen se ponavlja u listi", that is "row 3: the domain is repeated in the list").
- Light level 2 picks the number of contexts per machine: one per free GB of memory, at most two per
  core and at most 8. Full level 2 still runs with `browser.concurrency`, because it loads one by
  one. `browser.light_concurrency = 0` is the automatic choice, and a number ≥ 1 fixes it. On list B,
  light level 2 with three contexts took 168 s for 40 sites, and on 200 domains there are about 140
  of them ([ADR-019](docs/adr/ADR-019-run-duration-and-level2-coverage.md)).

### Changed

- The weight, request count and load time thresholds are calibrated on list A, under the network
  profile: weight up to `load` without video 2 / 4 / 7 MB (was 3 / 5 / 8), requests up to `load`
  60 / 90 (was 100 / 150), time to `load` 6 / 9 s (was 4 / 8). These are the rounded p50, p75 and
  p90; for checks with two levels, medium is p50 and high is p75
  ([ADR-020](docs/adr/ADR-020-threshold-calibration.md), [calibration log](docs/sr/kalibracija.md)).

### Fixed

- A home page without text that only redirects to the same site, by JavaScript (`location = …`,
  `location.replace(…)`) or by meta refresh, was judged as the home page: on list B a 95 B page
  leading to "coming soon" got findings for title, description and canonical that the real page has.
  Level 1 now follows such a jump like an HTTP redirect: the jump is in the chain, and the page it
  leads to is judged (on level 2 too). A stub is a page with at most 100 characters of visible
  text; a redirect to another site is not followed (BUG-022).
- `perf.img.oversized` counted SVG images and `data:` placeholders for lazy loading as well, and the
  finding fired on the image count even when the transfer was not measured, so the sentence said
  "about 0 kB of unnecessary transfer". On list B, 5 of 47 findings came only from such images, and
  for another 15 the image count was too high. Now only raster images with measured waste count;
  when at least 3 oversized images have no measured transfer, the check is `unknown`
  (`oversized_unmeasured`) (BUG-023).
- `infra.tls.invalid`: an incomplete certificate chain ("unable to get local issuer certificate") is
  rejected by Python, but a browser can complete it on its own, so it is now `unknown`
  (`tls_incomplete_chain`), not a finding that the visitor sees a warning (BUG-024).
- `i18n.lang.mismatch` read every text with Cyrillic or č/ć/š/ž/đ as Serbian, so a Russian site with
  `lang="ru"` would get "the site's content is in Serbian". Languages written with those letters
  (hr, bs, ru, mk, bg, sl, cs…) are no longer a finding, and a `lang` with spaces is compared without
  them (BUG-025).
- `infra.sitemap.missing` looked only at the status of the first `Sitemap:` in robots.txt: a dead
  first one next to a second one that works gave "the site has no sitemap". If the sitemap produced
  addresses, the check is `ok` (BUG-026).
- Review of the message catalog: sentences no longer claim anything the evidence does not cover.
  `h1`, `alt` and `lang` are measured only on the home page, so the sentence says so ("the home page
  has no main heading"). The soft 404 says the site "responds as if the page exists", not that it
  returns an ordinary page. Repeated title and description no longer claim how they look in Google
  results. A `lang` with a wrong format (`en_EN`) is not a "no language" tag. Unsourced claims were
  removed: "many visitors do not wait that long" (weight and time) and "Viber groups" (og:image);
  "many" and "often" joined the list of words that require a source. The report text no longer
  claims that the tool does not touch what `robots.txt` forbids: it always opens the home page and
  the two 404 probes. Also corrected were the reasons `requires.entry`, `requires.soft404` and
  `no_h1_raw`, the English `requires.robots`, `requires.sitemap` and the assumption in the report,
  as well as Serbian grammatical cases ("bodovi: 24", "od 22 slike", "301 znak").
- Level 2 did not look at the HTTP status of the home page, so an error page was measured as the
  home page. On list B one server refused a UA with "HeadlessChrome" with 403, and the tool measured
  a 358 B error page instead of the real one of about 2 MB. A status ≥ 400 is now a failed recording
  (`http_status`), so the level-2 checks are `unknown`. The browser presents itself as "Chrome/…",
  and the operator identity stays at the end (BUG-021).
- Level 2 presented itself only with the operator identity (`MlazicSiteScanner/…`), not as a
  browser. Services that a site loads choose content by User-Agent: ad networks ran extra auctions,
  and Google Fonts sent a larger font format. On a site with ads the tool measured 2.7 MB and 129
  requests, while a visitor in Chrome gets 1.3 MB and about 60. The browser now sends its own UA,
  with the operator identity appended at the end, as Googlebot does. Level 1 sends the same UA as
  before (BUG-019).
- A site without an escalation reason, or beyond `max_level2`, did not go to the browser, so it
  stood in the report with "0 findings", and its weight, requests and images were never measured. On
  list B two pages of 4.8 and 4.9 MB had fast, clean HTML. Such sites now get light level 2: after
  the full level 2, without the network profile and without the load queue. Load time for them "does
  not apply" (`not_applicable`, reason `requires.level2_full`): the site does not become `partial`
  because of it, and it does not enter the denominator of `unknown_share` for time. The snapshot
  carries `light`, `duration_s` carries `level2_light`, and the progress bar the phase
  `level2_light` (BUG-020).
- `qa.console.errors` called every console error a "JavaScript error", but the console also logs
  blocked "Mixed Content" and resources that return 404. On list B, for 3 of 6 findings not a single
  error came from a script. The sentence now says that Chrome reports errors and what they can be
  (BUG-018).
- `infra.host.duplicate` also put the http variants in the address list, so the sentence next to
  "2 addresses" listed four when http does not redirect to https. The list is now hosts (`x.rs`,
  `www.x.rs`), like the count; http without a redirect stays the finding
  `infra.https.redirect.missing` (BUG-017).
- `seo.canonical.duplicate` counted a page whose canonical points to its own `http` or `www` version
  as a page with a foreign canonical, so the sentence showed the owner their own home page as
  "another address". Such a canonical no longer counts
  ([ADR-020](docs/adr/ADR-020-threshold-calibration.md)).
- A temporary DNS error (EAI_AGAIN) is retried once, on level 1 and in the address check on level 2.
  Over a mobile hotspot it hit every fourth domain, so working sites dropped out as `failed`, and on
  level 2 one error blocked all requests to that host. A host variant with a temporary DNS error is
  `unknown`, because it is not known whether that address serves the site.
- Level 1 processes 16 domains at once instead of 8. It mostly waits for the pauses towards the same
  site, so a run over 200 domains had been estimated at about 20 minutes. Politeness towards each
  site is the same: one request at a time and the same pause
  ([ADR-019](docs/adr/ADR-019-run-duration-and-level2-coverage.md)).
- The politeness key was the exact host, so `www.x.rs` and `x.rs` could get two requests at the same
  time. Now the key is the host without a leading `www.`: both share a queue and a pause.
- A host variant that redirects to the home page downloaded the home page once more. On slow hosting
  that used up the domain's time budget before the page sample, so on list A 21 domains ran out of
  budget. A variant now stops before the home page and takes the status and canonical from it.
- The language checks (`i18n.lang.missing`, `invalid`, `mismatch`) looked only at raw HTML, so a
  site whose text is drawn by JavaScript got `unknown`, and a `lang` set by JavaScript was reported
  as missing. When level 2 ran, the checks now look at the page after JavaScript, as a screen reader
  reads it, and the evidence names the source (`sirovi_html` or `nivo2`). The level-2 snapshot
  records `lang` and the visible text after JavaScript.
- When the SSRF protection on level 2 refuses a request, Chromium reports only
  `ERR_BLOCKED_BY_CLIENT`, so a failed DNS lookup could not be told apart from a private address.
  Now the log (INFO, once per host) gives the reason: "DNS nije razrešio ime" ("DNS did not resolve
  the name") or "adresa nije javna: …" ("address is not public: …").
- Weight and request count also counted what arrives after the `load` event (analytics, chat, lazy
  images), so the same site had 179 requests once and 281 the next time. Now only requests started
  before `load` count; a body that arrives later for such a request still counts. The total is only
  in the technical sentence and in the JSON. When `load` does not arrive, the weight is `unknown`.
  The level-2 snapshot has `requests_at_load`, `bytes_at_load`, `bytes_by_type_at_load` and
  `unmeasured_at_load`, and for a 1.x snapshot both checks are `unknown`.
- `seo.canonical.duplicate` also counted a page that points to itself, so two subpages of seven,
  with a canonical to the home page, gave `critical`. Now only pages with a foreign canonical count
  (at least two, from two path groups), and the severity depends on their share of the sample:
  `medium`, `high` from 0.4, `critical` from 0.6. The sentence says how many of how many checked
  pages.
- A site with one or two pages was `partial`, because the duplicate checks had nothing to compare.
  They are now `not_applicable`, but only when the site really has no more pages. When the sample is
  small because of the budget or links from JavaScript, they stay `unknown`, with a reason.
- When the home page did not reach `load` within 25 s, the sentence claimed "it needs 25 s to load
  fully", but it needs more. Now it says it did not load fully even in 25 s.
- Unsourced sentences: `infra.tls.invalid` no longer claims that most visitors turn back at the
  warning, and `infra.robots.missing` does not claim that every search engine asks for that file
  first, but that Google reads it before crawling the site. A test now forbids words that claim
  frequency or human behaviour (`većina`, `uvek`, `svaki`, `most`, `always`, `every`…) in the
  sentences of both languages.
- The HTML report said "1 nalaza"; now number and noun agree ("1 nalaz", "3 nalaza").
- The Serbian HTML report wrote the score, points, duration and the speed from the assumption with a
  decimal point ("99.4"), and client sentences with a comma. Now every such number goes through the
  language's formatter ("99,4" in Serbian, "99.4" in English), with one decimal. The technical
  sentence, evidence, CSV and JSON keep machine notation, with a point and full precision.
- Without Playwright installed (`pip install skener` without `[browser]`) a run with level 2 crashed.
  Now level 2 is skipped with a message, and level 1 works.

## 1.0.0 — 2026-09-24

First release: 28 checks on two levels (raw HTTP and a real browser), scoring by industry, ranking,
HTML and CSV reports with client sentences in Serbian, `recheck` over saved snapshots, and the
operator identity in the User-Agent. Verified in three runs over 100 real domains
([IT-SKENER-002](docs/sr/izvestaj-testiranja-2.md)).
