# Legacy references

Code comments, tests, `skener.toml` and the Serbian documents cite sources that are not in this
repository: sections of a specification (`§4.2`), numbered requirements of its second version
(`Z-26`), bug and observation ids from the test reports (`BUG-020`, `O-7`) and document or phase ids
(`IT-SKENER-003`, `F4`). This page says what each one means and where it is documented now, so the
references can be replaced with something a reader can follow.

The meanings come from the repository text: every place an id is used, the test reports, the
calibration log, `CHANGELOG.md` and the commit history up to commit `0c4116a`. Paths are given as
they are in that tree (package `skener/`; the rename to `sitetriage/` is ADR-012, in progress).

**How to use it when replacing a reference.** Where the "Documented in" column names an ADR or a
CHANGELOG entry, link to it. Where it says *inline only*, the meaning is not published anywhere else:
replace the reference with the short explanation from the "Meaning" column, or just drop it if the
surrounding comment already says it.

## Read this first

- **Two specifications.** The original (v1) specification is cited only by section number; its
  document id is not given in the repository. The v2 specification is `SP-SKENER-002`. Neither is
  published. Most `§` references in code and tests use the v1 section layout (§2 architecture, §4
  level 1, §7 level 2 and so on). A few later references use v2 numbering, where §7 is the exit
  criteria, §8 asks for an ADR on the JSON schema and §9 lists items moved out of v2. Where a number
  means different things, every meaning is listed. The repository does not say whether v2 kept the v1
  layout for the sections it did not change.
- **`§` also points into this repository's own documents.** The test reports and the test plan are
  numbered, and they cite each other (`IT-SKENER-002 §3.2`) and themselves (`§6.3`). Those uses are
  listed in a separate table.
- **`Z-nn` are v2 requirements.** The IT-SKENER-003 tables call them *zahtev* (requirement), and
  they are numbered by phase: Z-0x for F0, Z-1x for F1, Z-2x for F2, Z-3x for F3, Z-5x for F5 (this
  numbering by phase is inferred from usage; no Z-4x for F4 is ever cited). Many of them record an
  owner decision and an acceptance condition, which is why they were cited as decisions.
- **"Run B" is not "list B".** Runs A to H are runs over the same 100 domains (list A). List B is a
  different set of 100 domains, scanned on 2026-10-03, 05 and 06.
- "Basis" says how the meaning was established: **stated** means the text names the topic outright;
  **inferred** means it was reconstructed from what the citing code or text does.

## 1. Specification sections (`§`)

| Ref | Meaning | Basis | Documented in |
|---|---|---|---|
| §1 | Only in `docs/sr/kvalitet.md` ("adresu u Srbiji (§1)"): section 1 of that same document (functional suitability), not the specification | stated | *inline only* (doc-local, see section 2) |
| §1.2 | v1: success criteria **U1** (200 domains in ≤ 15 min), **U2** (as many rows out as domains in; no domain crashes the run) and **U4** (a deliberately clean control site gets no findings: the guard against false positives, called the most important criterion). U3 is never cited | stated | U1: [ADR-019](ADR-019-run-duration-and-level2-coverage.md); U2, U4: *inline only* |
| §2.1 | v1: architecture split. Code that touches the network and code that draws conclusions are separate layers; checks receive a finished snapshot, so tests run offline and recalibration needs no new scan | inferred | README, architecture section ("Kako je podeljen"); CONTRIBUTING, "Architecture rules" |
| §2.2 | v1: snapshots are always written to disk (also the basis for `recheck` and diagnosis) | inferred | README, "Ulaz i izlaz" ("snapshots are always written"); *otherwise inline only* |
| §2.3 | v1: the rule that is never broken: the `checks` package does not import `httpx`, `playwright` or `fetch.*` (except `fetch.urls`) | stated | README architecture section; CONTRIBUTING "Architecture rules"; enforced by `tests/test_architecture.py` |
| §2.4 | v1: the check registry, including the `requires` preconditions that say why a check cannot run | stated | *inline only* (CONTRIBUTING "Adding a new check" covers usage) |
| §3 | v1: data schemas (`models.py`) | stated | *inline only* |
| §3.1 | v1: `SiteSnapshot`, the level-1 snapshot. Also IT-SKENER-003 §3.1 (automated tests), see section 2 | inferred | *inline only* |
| §3.2 | v1: `PageSnapshot`; raw HTML is kept only for the home page, otherwise snapshots grow. Also IT-SKENER-002 §3.2 and IT-SKENER-003 §3.2 (mutation testing), see section 2 | inferred | *inline only* |
| §3.3 | v1: `BrowserSnapshot`, the level-2 snapshot, with a worked example (the `restoran-centar.example` fixture numbers, an oversized-image waste of about 1840 kB). It requires telling "0 oversized images" apart from a failed measurement. Also IT-SKENER-002 §3.3 (review of client sentences) and IT-SKENER-003 §3.3 (message catalog), see section 2 | inferred | *inline only* |
| §3.4 | v1: check result. `unknown` without a reason is a bug, and `ok` may only be returned for something actually verified. Also IT-SKENER-003 §3.4 (calibration on list A) | stated | [ADR-015](ADR-015-not-applicable-and-partial-causes.md) (same rule for `not_applicable`); *otherwise inline only* |
| §3.5 | v1: finding. Evidence is mandatory and must contain the number the sentence uses ("the site is slow" is not a finding); the industry multiplier changes points, never severity; the sentence goes to the site owner, so it must be accurate. Also IT-SKENER-003 §3.5 (system test on list B) | stated | [ADR-022](ADR-022-client-sentence-claims.md); `docs/sr/kvalitet.md` §1 (multiplier changes weight, not severity) |
| §3.6 | v1: the remaining result types (domain report). Cited once, together with §3.4 and §3.5, above `Finding`, `Reason`, `CheckResult`, `Unknown` and `DomainReport` | inferred | *inline only* |
| §4 | v1: level 1 fetching. Also IT-SKENER-003 §4 (exit criteria), see section 2 | inferred | *inline only* |
| §4.1 | v1: the input list is a CSV with the header `domain,industry,note`, not a bare list; empty or unknown industry falls back to `ostalo` | stated | README, "Ulaz i izlaz" |
| §4.2 | v1: hard per-domain request budget: a number of requests and a number of seconds from `[http]` (now 19 requests and 40 s) | stated | README, politeness list in "Etika"; [ADR-014](ADR-014-host-canonicalization.md) (19 requests) |
| §4.3 | v1: `robots.txt` parsing and obeying: only the `User-agent: *` section; a `Sitemap:` from robots.txt wins over guessing; the tool must not fetch what robots.txt disallows even when the sitemap offers it | stated | README, "Etika" (Disallow is obeyed); *otherwise inline only* |
| §4.4 | v1: sitemap: recursion limits, `.xml.gz` support, untrusted-content limits, and deterministic sampling (8 = home + 7, round robin over groups by first path segment, so the sample is not eight blog posts); a sample taken from links is less reliable than one from the sitemap | stated | README, "Šta alat namerno ne radi"; *otherwise inline only* |
| §4.5 | v1: URL normalization and comparison (trailing slash, tracking parameters, default ports; titles and descriptions compared after trimming and collapsing whitespace). **Point 7:** `www` and non-`www` are different addresses for Google, so `www.` is deliberately not stripped | stated | *inline only* |
| §4.6 | v1: errors, retries and giving up: the error kind decides whether a request is retried; 5xx is retried exactly once; 4xx is an answer and is not retried; https first, then http; an invalid certificate is a finding, not a reason to drop the domain | stated | *inline only* (temporary DNS retry: [ADR-013](ADR-013-unreachable-after-second-attempt.md)) |
| §5 | v1: level-1 checks (SEO, infra, language, Open Graph); duplicate rules need ≥ 3 pages from different path groups; the 50 kB compression floor. Also IT-SKENER-002 §5 and IT-SKENER-003 §5 (defects), see section 2 | inferred | README, "Provere" (check table) |
| §5.1 | v1: language heuristic: Serbian recognised by Cyrillic share and diacritic ratio (Serbian Latin has 2–5 % diacritics, English 0 %). **Point 1:** too little text gives `unknown` and is also an escalation signal. **Point 3:** the detector returns `sr` or "undetermined", never `en`, because English and Serbian without diacritics cannot be told apart | stated | README, thresholds section ("Zašto su pragovi baš takvi") |
| §5.2 | v1: soft-404 probes: two deterministic probe paths (`sha1(domain)[:16]`); a finding only when both return a final 200; one 200 and one 404 is `ok`; a status outside {200, 404, 410} is `unknown`; text similarity ≥ 0.9 with the home page is hard evidence | stated | README check table (`infra.soft404`) |
| §6 | v1: escalation policy to level 2 and its hard cap. Six conditions joined by OR; empty raw HTML is a signal, not a finding; the slow-home-page condition is the only one that catches a site with clean SEO and a slow page; an empty `h1` after a timeout is not a finding. Also IT-SKENER-003 §6 (observations), and one unclear use in IT-SKENER-001, see section 2 | stated | README thresholds section; [ADR-019](ADR-019-run-duration-and-level2-coverage.md) |
| §6.1 | Only IT-SKENER-003 §6.1 (how the observations of IT-SKENER-001/002 were closed) | stated | doc-local, see section 2 |
| §6.3 | Only IT-SKENER-003 §6.3 (owner decisions of 2026-10-05, numbered 1–9) | stated | doc-local, see section 2 |
| §7 | **v1:** level 2 (Playwright, `BrowserSnapshot`). **v2 (SP-SKENER-002):** exit criteria, including `partial` by budget and `unknown` per check (cited with Z-22), the catalog review and the manual check on list B ("Kriterijumi iz §7", "spec §7"). Also IT-SKENER-002 §7 (conclusion), see section 2 | stated (both) | v1: [ADR-010](ADR-010-mrezni-profil.md), [ADR-018](ADR-018-load-time-validity.md); v2: `docs/sr/plan-testiranja.md` §4, [ADR-015](ADR-015-not-applicable-and-partial-causes.md), [ADR-021](ADR-021-manual-verification.md) |
| §7.1 | v1: browser session: one browser per run and a new context per domain; scrolling is needed or lazy images have `naturalWidth == 0`; measurements after a timeout are incomplete and checks must know it | inferred | *inline only* |
| §7.2 | v1: weight measurement from network events, not the Performance API (which reports 0 for cross-origin resources without `Timing-Allow-Origin`); `data:` and `blob:` are not counted; above `max_unmeasured_responses` the weight is `unknown` ("a measurement you do not trust is worse than none") | stated | [ADR-016](ADR-016-weight-until-load.md); README thresholds section |
| §7.3 | v1: level-2 performance and SEO checks with tiered thresholds: one finding per check, at the highest severity that applies; oversized images fire at ≥ 3 images or > 700 kB waste. The fixture test set still uses the spec's uncalibrated weight thresholds | stated | [ADR-020](ADR-020-threshold-calibration.md); README check table |
| §7.4 | v1: accessibility: `alt` has three states, not two (missing is an error, `alt=""` is a correct decorative image); a share above 0.8 with ≥ 15 images is `high`; healthcare and institutions have legal exposure | stated | README check table (`a11y.img.alt.missing`) |
| §7.5 | v1: formula for the oversized-image waste estimate; `image_ratio` 2.5, because 2 would flag every correct retina site | stated | README thresholds section |
| §8 | **v1:** politeness, concurrency and robustness. **v2:** asks for an ADR on the JSON schema and its stability (commit `fc46eed` only). Also test plan PT-SKENER-001 §8 (defect management), see section 2 | stated | v1: README "Etika"; v2: [ADR-011](ADR-011-json-sema.md) |
| §8.1 | v1: two semaphores: the global one limits you, the per-host one (always 1) protects them, "the line between a tool and an attack"; browser concurrency 3 because each context costs hundreds of MB | stated | README "Etika" |
| §8.2 | v1: failure isolation: an exception never leaves a domain; every check runs in its own `try`; a snapshot goes to disk as soon as its domain is done ("if the process dies on the 190th, you have 189"); one hanging domain must not stop the other 199 | stated | `docs/sr/kvalitet.md` §5 (reliability); [ADR-008](ADR-008-pipeline.md) (cancellation keeps snapshots) |
| §8.3 | v1: pause with jitter between requests to one host; `Crawl-delay` honoured up to `max_crawl_delay_s`; on 429 or 503 the domain is given up for this run, without retry | stated | README "Etika" |
| §9 | **v1:** scoring and ranking. **v2:** the list of items moved out of v2 ("prebačeno u §9 specifikacije": lazy-loaded images and inconclusive soft-404 probes stay `unknown`) | stated (v1), inferred (v2) | v1: README "Provere"; v2: README "Planirano, nije u v2" (closest public list) |
| §9.2 | v1: `weight = severity_points[severity] × industry_multipliers[industry][category]`; unknown industry falls back to `ostalo` | stated | `skener.toml` comment; README "Ulaz i izlaz" |
| §9.4 | v1: ranking key: the heaviest single finding first, the total only breaks ties ("a site with one disaster is a better lead than one with ten trifles"); the top 3 findings go into the suggested text; exact score pairs for the fixture sites | stated | README, end of "Zašto su pragovi baš takvi" |
| §10 | v1: reports | inferred | *inline only* |
| §10.1 | v1: CSV output, one row per finding, not per domain | stated | README "Ulaz i izlaz" |
| §10.2 | v1: HTML report: one self-contained file without a CDN; colours distinguishable in greyscale and for colour-blind readers | stated | README (top); `docs/sr/kvalitet.md` §3, §4 |
| §10.3 | v1: the mobile-speed assumption (4.8 Mb/s = 0.6 MB/s, plus `mobile_overhead_s`) used for seconds in sentences, which must be stated in a report footnote | stated | [ADR-010](ADR-010-mrezni-profil.md); README thresholds section |
| §11 | v1: command line | stated | *inline only* |
| §11.1 | v1: `recheck` (the main calibration tool) and `explain` (a report usable by someone other than you) | stated | README "Ostale komande" |
| §11.2 | v1: every threshold, multiplier and constant lives in TOML, not in code | stated | README ("Svi pragovi su u skener.toml") |
| §11.3 | v1: logging: JSON lines on stderr with a `domain` field in every record | stated | `docs/sr/kvalitet.md` §4; *otherwise inline only* |
| §12.1 | v1: test layers: offline tests of pure functions, and opt-in live calibration tests against real sites, kept out of CI because a site's expired certificate is not a tool bug | inferred | README "Testovi"; CONTRIBUTING "Running tests" |
| §12.2 | v1: fixtures recorded with `record`, without raw HTML of non-home pages (repo size); fixtures go stale | stated | `tests/fixtures/README.md`; *otherwise inline only* |
| §12.3 | v1: test design: per check a positive, a negative and an `unknown` test (the "third type"); table-driven tests (URL normalization) | stated | CONTRIBUTING "Test design conventions" |
| §12.4 | v1: the hand-written test set: eight typical sites and the `check_id`s each must produce, including the control clean site `klinika.example` | stated | `tests/fixtures/README.md`, `tests/test_ispitni_skup.py` |
| §13 | v1: implementation phases. **Phase 3** includes "injecting a deliberately broken domain must not bring down the run". Unrelated to the F0–F5 phases of v2 | inferred | *inline only* |
| §15 | v1: list of pitfalls (*zamke*). Cited items below | stated | *inline only* |

### §15 pitfalls cited in code

Pitfalls 3 and 6 are never cited. Their topics are unknown.

| Pitfall | Meaning | Cited in |
|---|---|---|
| 1 | Reporting `alt=""` as an error flags a correctly built site (decorative image) as broken | `checks/a11y.py`, `tests/test_checks_level2.py` |
| 2 | Without scrolling, lazy images have `naturalWidth == 0` and the check silently finds nothing | `fetch/browser.py`, `tests/test_fetch_browser.py` |
| 4 | Without URL normalization `/usluge` and `/usluge/` are not duplicates, and the canonical check gives false positives | `fetch/urls.py` |
| 5 | Non-deterministic sampling makes one site give different findings in two runs, and no test means anything; hence no `random` | `fetch/sitemap.py` |
| 7 | A tool that reports "no robots.txt" while ignoring it when it exists cannot be trusted | `fetch/robots.py` |
| 8 | Without a cap on level 2 the two-level architecture has no purpose | `tests/test_score.py` |
| 9 | Console errors are a weak signal, so the check stays `low` and does not go into the suggested text | `checks/perf.py` |
| 10 | Without a new browser context (empty cache) per domain, a second site on the same CDN measures falsely lighter | `fetch/browser.py`, `tests/test_fetch_browser.py` |
| 11 | `request.sizes()` throws for cached and aborted responses | `fetch/browser.py` |

## 2. `§` references into this repository's own documents

| Reference (as written) | Where | Meaning | Basis |
|---|---|---|---|
| `§1` | `docs/sr/kvalitet.md` | Section 1 of kvalitet.md (functional suitability: "not working" is valid only from an address in the country) | stated |
| "vidi §6" | `docs/sr/izvestaj-testiranja-100.md` §1 | Points to where the manual review of the top of the list is discussed. **Unclear:** IT-SKENER-001 §6 is observations and §7 recommends the manual check; it may also be a v1 spec section. Not decodable with certainty | unclear |
| "(§7)" | `docs/sr/izvestaj-testiranja-2.md` §1 | IT-SKENER-002 §7 (conclusion: the product owner reviews the top 5) | inferred |
| `IT-SKENER-002 §3.2` | `docs/sr/plan-testiranja.md`, `docs/sr/izvestaj-testiranja-3.md` | Mutation testing section of IT-SKENER-002: how surviving mutants are classified (import-time decorator mutants applied by hand, equivalent mutants) | stated |
| `IT-SKENER-002 §3.3` | `skener/messages/en.py` | Review of client sentences by three rules: the claim can be verified, every number comes from the evidence, number and noun agree | stated |
| `docs/sr/izvestaj-testiranja-2.md §5` | `docs/manual-check-form.md` | The defect section of IT-SKENER-002: the bug report format and procedure | stated |
| `§3.1`, `§3.2`, `§3.3`, `§4`, `§5`, `§6.1`, `§6.3` | `docs/sr/izvestaj-testiranja-3.md`, `scripts/mutation.py` | Sections of IT-SKENER-003: automated tests, mutation testing, message catalog, exit criteria, defects, closed observations, owner decisions of 2026-10-05 | stated |
| "§6.3, odluka 6" | `docs/sr/izvestaj-testiranja-3.md` | Owner decision 6 of 2026-10-05: run duration on the recommended machine is measured on the first VPS run | stated |
| "plan testiranja (§8)" | `docs/sr/izvestaj-testiranja-3.md` | PT-SKENER-001 §8, defect management: severities blocker / critical / major (false finding or false negative for the client) / minor / trivial | stated |
| "§7", "spec §7", "Kriterijumi iz §7" | `docs/sr/kalibracija.md`, `docs/manual-check-form.md`, `skener/models.py`, `skener/score.py`, `skener/report/html_out.py`, `tests/test_uzrok_partial.py` | v2 specification §7, exit criteria (see §7 above) | stated |
| "§9 specifikacije" | `docs/sr/izvestaj-testiranja-3.md` | v2 specification §9, items moved out of v2 | inferred |

`§` references that exist only in commit messages: "Spec §8 traži ADR za JSON šemu" (`fc46eed`, v2
§8), "Recenzija svih 131 stavke kataloga (§7)" (`ed2dbbf`, v2 §7), "izlazni kriterijumi iz §7"
(`d0f466f`, `2ea83e2`, v2 §7).

## 3. v2 requirements (`Z-`)

| Id | Phase | Meaning | Documented in |
|---|---|---|---|
| Z-01 | F0 | Line endings are LF in the repo and on disk, also on Windows (`.gitattributes`); without it `core.autocrlf` leaves CRLF and git in a Linux container sees 40 modified files | *inline only* (`.gitattributes`) |
| Z-12 | F1 | Client sentences move out of the checks into a per-language catalog (Serbian and English), with a language-aware number formatter; a golden file made before the move guards the Serbian sentences | [ADR-009](ADR-009-katalog-poruka.md) (the ADR does not cite Z-12; mapping inferred from tests and commits) |
| Z-13 | F1 | `report.json` is the serialized `ScanResult`, with a versioned JSON schema | [ADR-011](ADR-011-json-sema.md) |
| Z-20 | F2 | A site is `unreachable` only when certain (no DNS name or address, or no TCP connection on https and http) and only after a second attempt at least `http.second_attempt_after_s` (60 s) later; it goes to the "not working" list, not the ranking; everything else is `failed` with a reason | [ADR-013](ADR-013-unreachable-after-second-attempt.md); CHANGELOG 2.0.0 |
| Z-21 | F2 | Fourth result state `not_applicable` with a mandatory reason; duplicate checks do not apply only when the site really has < 3 pages; the sample is topped up with links from the home page (and the rendered DOM) | [ADR-015](ADR-015-not-applicable-and-partial-causes.md); CHANGELOG 2.0.0 |
| Z-22 | F2 | `partial` split by cause (`partial_causes`: `budget`, `unknown`); exit criteria budget < 10 % and `unknown` per check < 20 %; `budget_share`, `unknown_share` | [ADR-015](ADR-015-not-applicable-and-partial-causes.md); CHANGELOG 2.0.0 |
| Z-23 | F2 | `seo.canonical.duplicate` counts only pages whose canonical points elsewhere (`canonical_foreign_min = 2`, from two path groups); severity by share of the sample (`medium`, `high` from 0.4, `critical` from 0.6, initial values from the spec) | CHANGELOG 2.0.0 (Fixed); [ADR-020](ADR-020-threshold-calibration.md) (share limits); `docs/sr/kalibracija.md` 2026-09-26 |
| Z-24 | F2 | Weight and request count count only requests started before `load` (a body arriving later still counts); without `load` the weight is `unknown`; acceptance ≤ 10 % difference on ≥ 9 of 10 sites | [ADR-016](ADR-016-weight-until-load.md); CHANGELOG 2.0.0 |
| Z-25 | F2 | Language checks read the page after JavaScript, as a screen reader does, when level 2 ran; evidence names the source | [ADR-017](ADR-017-rendered-language-raw-seo-tags.md); CHANGELOG 2.0.0 |
| Z-26 | F2 | Host canonicalization: three variant requests (http/https × www/no www), checks `infra.https.redirect.missing` and `infra.host.duplicate`, budget 19 requests, politeness key without `www.`, variants stop before the home page; `optional` removed from the registry | [ADR-014](ADR-014-host-canonicalization.md); CHANGELOG 2.0.0 |
| Z-27 | F2 | Sentences must not claim frequency or human behaviour without a source; a test bans such words (`većina`, `uvek`, `svaki`, `most`, `always`, `every` …) in both languages | [ADR-022](ADR-022-client-sentence-claims.md); CHANGELOG 2.0.0 (Fixed) |
| Z-28 | F2 | Numbers in the HTML report (score, points, duration, speed) go through the language formatter ("99,4" in Serbian, "99.4" in English, one decimal); technical text, evidence, CSV and JSON keep machine notation | CHANGELOG 2.0.0 (Fixed, "HTML izveštaj na srpskom pisao je skor…") |
| Z-30 | F3 | Level 2 measures under a fixed network profile (4.8 / 1.5 Mb/s, 150 ms) via CDP; Chromium without site isolation so the profile also applies to cross-site iframes; `[network_profile]` is the single source of speed | [ADR-010](ADR-010-mrezni-profil.md); CHANGELOG 2.0.0 |
| Z-31 | F3 | Switch `browser.serial_load` and the experiment on whether parallel loading is accurate under the profile; serial loading kept | [ADR-018](ADR-018-load-time-validity.md) |
| Z-32 | F3 | A 200-domain run in ≤ 15 min: level 1 with 16 domains at once, light level 2 with contexts chosen per machine, target valid for the recommended machine (16 GB RAM, ≥ 50 Mb/s); not yet measured there | [ADR-019](ADR-019-run-duration-and-level2-coverage.md); CHANGELOG 2.0.0 |
| Z-33 | F3 | Real link measured with a probe file before level 2; load time `unknown` when the link is slower than `min_link_ratio` × profile (9.6 Mb/s) or unmeasured | [ADR-018](ADR-018-load-time-validity.md); CHANGELOG 2.0.0 |
| Z-50 | F5 | Calibrate weight, request and time thresholds on list A as rounded p50 / p75 / p90 under the profile; record level-2 duration (`elapsed_ms`); `scripts/distribution.py` | [ADR-020](ADR-020-threshold-calibration.md); CHANGELOG 2.0.0 (Changed); `docs/sr/kalibracija.md` 2026-09-28 |
| Z-51 | F5 | System test on list B with frozen thresholds; must run from an address in the country on a fast link; repeated after any defect fix | [ADR-020](ADR-020-threshold-calibration.md); IT-SKENER-003 §3.5 |
| Z-52 | F5 | Acceptance: owner's manual check of the top 10 and bottom 5 on list B, outside the tool (0 incorrect, ≥ 7 of 10 "would send", 0 missed) | [ADR-021](ADR-021-manual-verification.md); `docs/manual-check-form.md` |

Not decodable: "the 80 % rule of Z-52" (`docs/sr/kalibracija.md` 2026-10-06, IT-SKENER-003 O-21). The
rule is not written down anywhere in the repository.

## 4. Bugs (`BUG-`)

"Report" is where the bug is described in full. Ids 001–016 come from the v1 cycle
(`docs/sr/izvestaj-testiranja-100.md`, `docs/sr/izvestaj-testiranja-2.md` §5), 017–026 from the v2 cycle
(`docs/sr/izvestaj-testiranja-3.md` §5), 027–030 were found after v2.0.0.

| Id | Meaning | Report | Release / other docs |
|---|---|---|---|
| BUG-001 | A large sitemap used up the whole budget before the soft-404 probes; probes now go before the sample and `sitemap.max_files` dropped from 10 to 4 | IT-SKENER-001 §5; `docs/sr/kalibracija.md` 2026-09-24 | before 1.0.0 |
| BUG-002 | Level 2 hung forever on a response whose body never arrives (stream, video); fixed with `browser.drain_timeout_s` and a hard per-domain limit | IT-SKENER-001 §5; `docs/sr/kalibracija.md` 2026-09-24 | before 1.0.0 |
| BUG-003 | A site that blocks automated visits got "no robots.txt" and "no sitemap"; only 404 and 410 mean "does not exist", 401/403/429/5xx are `unknown` | IT-SKENER-001 §5, IT-SKENER-002 §5 | 1.0.0 |
| BUG-004 | An interrupted TLS handshake was reported as an invalid certificate and the domain failed; now `unknown` and the tool falls back to http | IT-SKENER-001 §5, IT-SKENER-002 §5 | 1.0.0 |
| BUG-005 | The level-2 cap always cut candidates without level-1 findings, for whom level 2 is the only chance; those now go first | IT-SKENER-001 §5, IT-SKENER-002 §5 | 1.0.0; [ADR-019](ADR-019-run-duration-and-level2-coverage.md) |
| BUG-006 | Load time was measured while three sites shared one connection (1.1–4.6× too long); sites now load one by one up to `load` | IT-SKENER-001 §5, IT-SKENER-002 §5 | 1.0.0; [ADR-018](ADR-018-load-time-validity.md); CHANGELOG 2.0.0 (`serial_load`) |
| BUG-007 | After the hard limit, asyncio logged a closed-context error; level 2 now restores the previous exception handler | IT-SKENER-002 §5 | 1.0.0; [ADR-008](ADR-008-pipeline.md) |
| BUG-008 | A CSV saved by Excel with `;` separators had no `domain` column | IT-SKENER-002 §5 | 1.0.0 |
| BUG-009 | A CSV in windows-1250 crashed the tool | IT-SKENER-002 §5 | 1.0.0 |
| BUG-010 | The same domain listed twice was scanned twice | IT-SKENER-002 §5 | 1.0.0 |
| BUG-011 | Concurrency 0 stopped the run forever without a message; zero and negative values are now rejected | IT-SKENER-002 §5 | 1.0.0 |
| BUG-012 | Log timestamps carried "Z" but were local time | IT-SKENER-002 §5 | 1.0.0 |
| BUG-013 | The compression sentence claimed a saving of "a second and a half"; the saving is now computed from the size | IT-SKENER-002 §5 | 1.0.0; [ADR-022](ADR-022-client-sentence-claims.md) |
| BUG-014 | Number and noun did not agree in Serbian ("4 JavaScript grešaka") | IT-SKENER-002 §5 | 1.0.0; [ADR-022](ADR-022-client-sentence-claims.md) |
| BUG-015 | Decimal point instead of a comma in a Serbian sentence ("14.9 MB") | IT-SKENER-002 §5 | 1.0.0; [ADR-022](ADR-022-client-sentence-claims.md) |
| BUG-016 | Page weight summed decompressed bytes (25.3 MB instead of 3.8 MB transferred); now `responseBodySize` | IT-SKENER-002 §5 (full report) | 1.0.0; [ADR-016](ADR-016-weight-until-load.md) |
| BUG-017 | The address count in the host-duplicate sentence did not match the list (four addresses listed next to "2 addresses") | IT-SKENER-003 §5 | CHANGELOG 2.0.0; [ADR-014](ADR-014-host-canonicalization.md) |
| BUG-018 | The console sentence called every console error a "JavaScript error" | IT-SKENER-003 §5 | CHANGELOG 2.0.0; [ADR-022](ADR-022-client-sentence-claims.md) |
| BUG-019 | Level 2 identified itself only with the operator identity, not as a browser, so ad networks and a font service sent heavier content; the browser now sends its own UA with the identity appended | IT-SKENER-003 §5; `docs/sr/kalibracija.md` 2026-10-04 | CHANGELOG 2.0.0; README "Etika" |
| BUG-020 | A heavy page with no escalation reason never went to the browser ("0 findings"); every working site now gets full or light level 2, and load time on light level 2 is `not_applicable` | IT-SKENER-003 §5; `docs/sr/kalibracija.md` 2026-10-04/05 | CHANGELOG 2.0.0; [ADR-019](ADR-019-run-duration-and-level2-coverage.md), [ADR-015](ADR-015-not-applicable-and-partial-causes.md) |
| BUG-021 | Level 2 did not check the HTTP status of the main document, so an error page was measured as the home page; status ≥ 400 is now a failed capture, and the UA drops "Headless" | IT-SKENER-003 §5 (full report) | CHANGELOG 2.0.0 |
| BUG-022 | Level 1 did not follow a same-site redirect done only by JavaScript or meta refresh, so a near-empty stub was scored as the home page | IT-SKENER-003 §5, §6.3 | CHANGELOG 2.0.0 |
| BUG-023 | Oversized images counted SVG and `data:` placeholders and fired without measured transfer ("about 0 kB") | IT-SKENER-003 §5 | CHANGELOG 2.0.0; [ADR-022](ADR-022-client-sentence-claims.md) |
| BUG-024 | An incomplete certificate chain was reported as a warning the visitor sees; now `unknown` (`tls_incomplete_chain`) | IT-SKENER-003 §5 | CHANGELOG 2.0.0 |
| BUG-025 | Text in another language written in Cyrillic or with č/ć/š/ž/đ, with a correct `lang`, was reported as Serbian | IT-SKENER-003 §5 | CHANGELOG 2.0.0 |
| BUG-026 | A dead first sitemap from robots.txt next to a working one gave "the site has no sitemap" | IT-SKENER-003 §5 | CHANGELOG 2.0.0 |
| BUG-027 | Sitemaps of other domains listed in a shared robots.txt used up the 4-file limit, so the site's own sitemap was never read; only same-site sitemaps are read now | commit `fd58103` | CHANGELOG, Unreleased |
| BUG-028 | A blank line before `<?xml` made the sitemap invalid XML and the site got `infra.sitemap.missing` | commit `39f0e8f` | CHANGELOG, Unreleased |
| BUG-029 | Duplicate title, description and canonical counted a page twice when two sampled addresses led to it | commit `f483105` | CHANGELOG, Unreleased |
| BUG-030 | Oversized images counted the same image once per repetition in the DOM (cloned slider slides) | commit `b8bc99f` | CHANGELOG, Unreleased |

Also cited without a number: "B1–B4" in `docs/real-site-verification.md`, the four bugs fixed
just before the first real-site check (budget, time measurement, probes, TLS evidence). They are not
mapped to BUG ids anywhere.

## 5. Observations (`O-`)

O-1 to O-6 are from IT-SKENER-001 §6, O-7 to O-13 from IT-SKENER-002 §6, O-14 to O-21 from
IT-SKENER-003 §6.2. How O-5 and O-7 to O-13 were closed is tabled in IT-SKENER-003 §6.1.

| Id | Meaning | Outcome | Documented in |
|---|---|---|---|
| O-1 | The page-weight threshold (1.5 MB) fired on 55 of 60 sites and did not separate them | Thresholds set from the distribution, finally Z-50 | [ADR-020](ADR-020-threshold-calibration.md); `docs/sr/kalibracija.md` 2026-09-24 |
| O-2 | Video dominates and varies the weight; keep it out of the threshold and state it separately (its example was wrong, see O-13) | Video excluded from the threshold | [ADR-016](ADR-016-weight-until-load.md) |
| O-3 | The `i18n.lang.mismatch` sentence claimed a search-engine effect that is not true; the real consequence is the screen reader | Sentence fixed, severity `high` → `medium` | [ADR-022](ADR-022-client-sentence-claims.md); README thresholds section |
| O-4 | 30 % `partial` came from the 25 s budget on slow shared hosting | Time budget 40 s, still 16 requests | `skener.toml` comment; README "Etika" |
| O-5 | A site that does not answer had no finding while a site without DNS had `critical` | `infra.unreachable` and the "not working" list (Z-20) | [ADR-013](ADR-013-unreachable-after-second-attempt.md) |
| O-6 | 6 domains without DNS records, confirmed outside the tool | Tool was correct; no change | *IT-SKENER-001 only* |
| O-7 | What the 14.4 % `partial` consisted of. **O-7a:** < 3 pages → "does not apply" (Z-21). **O-7b:** split the `partial` criterion (Z-22). Also text drawn by JavaScript (Z-25), lazy images and inconclusive probes (stay `unknown`, moved to v2 spec §9) | Closed via Z-21, Z-22, Z-25 | [ADR-015](ADR-015-not-applicable-and-partial-causes.md), [ADR-017](ADR-017-rendered-language-raw-seo-tags.md) |
| O-8 | Domains without DNS ranked near the top because their finding was `critical` | Moved out of the ranking (Z-20) | [ADR-013](ADR-013-unreachable-after-second-attempt.md) |
| O-9 | `seo.canonical.duplicate` also counted the home page pointing to itself, so 2 of 7 subpages gave `critical` and first place | Only foreign canonicals count, severity by share (Z-23, Z-50) | [ADR-020](ADR-020-threshold-calibration.md); CHANGELOG 2.0.0 |
| O-10 | The page keeps loading after `load` (179 vs 281 requests for one site) | Count up to `load` (Z-24) | [ADR-016](ADR-016-weight-until-load.md) |
| O-11 | The HTML report showed a decimal point while sentences used a comma | Language formatter in HTML (Z-28) | CHANGELOG 2.0.0 (Fixed) |
| O-12 | The registry's `optional` flag was used by no check; it was reserved for host canonicalization | Flag removed, two host checks (Z-26) | [ADR-014](ADR-014-host-canonicalization.md) |
| O-13 | Correction of IT-SKENER-001 O-2: the 8.5 / 26.9 MB example had no video; the difference came from post-`load` scripts and decompressed bytes | Report correction only | [ADR-016](ADR-016-weight-until-load.md) |
| O-14 | The "not working" list depends on the scanning address: a hosting provider refuses data-centre connections from abroad | Z-51 runs from an address in the country; open risk for a hosted version | [ADR-013](ADR-013-unreachable-after-second-attempt.md); `docs/sr/kvalitet.md` §1 |
| O-15 | A home page with almost no content is not a finding | Planned check after v2 | README "Planirano, nije u v2" |
| O-16 | "Under construction" pages and parked domains without a redirect are scored as normal sites | Observation; the script/meta-refresh variant fixed by BUG-022 | *IT-SKENER-003 only* |
| O-17 | The ranking does not know whether a site is a business (an association ranked in the top 10) | Choosing domains is the operator's job | [ADR-021](ADR-021-manual-verification.md) |
| O-18 | Run duration with light level 2: about 23 min for 200 domains with three contexts | Contexts chosen per machine; target tied to a recommended machine (Z-32) | [ADR-019](ADR-019-run-duration-and-level2-coverage.md) |
| O-19 | Title, description and canonical set by JavaScript would make `seo.*.missing` false | Level 2 records `dom.*`; checks stay on raw HTML (0 of 99 sites affected) | [ADR-017](ADR-017-rendered-language-raw-seo-tags.md); CHANGELOG 2.0.0 (Added) |
| O-20 | A home page without `<meta name="viewport">` renders as a shrunken desktop page; not checked | Candidate check after v2 | *IT-SKENER-003 and `docs/sr/kalibracija.md` 2026-10-06 only* |
| O-21 | The same site measured on light and full level 2 gave different weights (8.6 vs 6.8 MB near the 7 MB threshold) | Open, cause unknown; "covered by the 80 % rule" (undefined) | [ADR-019](ADR-019-run-duration-and-level2-coverage.md) |

## 6. Documents, phases and other ids

| Id | Meaning | Documented in |
|---|---|---|
| v1 specification | The original specification, cited only by section number (§1–§15). Not in the repository; its id is not given | this page, section 1 |
| SP-SKENER-002 | The v2 specification: phases F0–F5, requirements Z-nn, risks R-1 and R-2, its own §7 (exit criteria), §8 (asks for the JSON-schema ADR), §9 (items moved out of v2). Not in the repository | this page; [ADR-010](ADR-010-mrezni-profil.md) cites it |
| PT-SKENER-001 | Test plan, `docs/sr/plan-testiranja.md` (v2.2, 2026-10-05) | that file |
| IT-SKENER-001 | Test report: first system test over 100 real domains, 2026-09-24 (`docs/sr/izvestaj-testiranja-100.md`) | that file |
| IT-SKENER-002 | Test report: v1 fix cycle (BUG-003 to BUG-016) and repeated runs B and C, 2026-09-24 (`docs/sr/izvestaj-testiranja-2.md`); basis of release 1.0.0 | that file; CHANGELOG 1.0.0 |
| IT-SKENER-003 | Test report for v2 (F0–F3, F5): calibration on A, validation on B, manual check, BUG-017 to BUG-026, 2026-10-05/06 (`docs/sr/izvestaj-testiranja-3.md`); basis of release 2.0.0 | that file; CHANGELOG 2.0.0 |
| F0 | v2 phase "preparation": line endings, version, quality thresholds (Z-01) | `docs/sr/plan-testiranja.md` §6 |
| F1 | v2 phase "core": pipeline, input list, message catalog, JSON, SSRF, excluded domains (Z-12, Z-13; ADR-006, 008, 009, 011) | `docs/sr/plan-testiranja.md` §6 |
| F2 | v2 phase "accuracy": closing O-5 and O-7 to O-12 (Z-20 to Z-28); closed 2026-09-27 after run E | `docs/sr/plan-testiranja.md` §6; ADR-013 to ADR-017 |
| F3 | v2 phase "measurement": fixed network profile, parallel loading, run duration (Z-30 to Z-33) | `docs/sr/plan-testiranja.md` §6; ADR-010, ADR-018, ADR-019 |
| F4 | v2 phase "business layer": `skener diff` and `skener outcomes`. Deferred by the owner on 2026-09-27 and not in 2.0.0; the "diff of the same report is empty" criterion moved to F4 on 2026-10-05 | `docs/sr/plan-testiranja.md` §6; README "Planirano, nije u v2" |
| F5 | v2 phase "validation": calibration on A, run on B, manual check, IT-SKENER-003 (Z-50 to Z-52); scheduled before F4 (test plan v2.1) | `docs/sr/plan-testiranja.md` §6; ADR-020, ADR-021 |
| U1, U2, U4 | Success criteria of v1 §1.2 (see §1.2 above); U3 is never cited | this page |
| R-1 | Risk in the v2 specification: longer loads under the network profile make level 2, and the run, longer | [ADR-010](ADR-010-mrezni-profil.md), [ADR-019](ADR-019-run-duration-and-level2-coverage.md) |
| R-2 | Risk in the v2 specification: the three host-variant requests, each with a politeness pause, push slow sites over the time budget | [ADR-014](ADR-014-host-canonicalization.md) |
| R1–R6 | Test-plan risks (no hyphen): R1 sites change between runs, R2 timing tests flaky on slow machines, R3 mutation testing too slow, R4 lead list leaking into the public repo, R5 calibration on A spilling over to B, R6 message refactor silently changing Serbian sentences | `docs/sr/plan-testiranja.md` §7 |
| "pravilo 7" (rule 7) | Cited in `docs/manual-check-form.md`: a filled-in form contains domains, so it stays in `rad/` and out of the repository. The list of rules it belongs to is not in the repository (presumably the specification's working rules) | *not decodable beyond this usage* |
| "faze 0–7" | `docs/sr/kvalitet.md`: v1 development phases "in the commit history". That history is not in this repository (it starts on 2026-09-26) | *not decodable* |
| "§13, faza 3" | v1 specification §13, phase 3 (see §13 above) | this page |
| "odluka 1–9" | The numbered owner decisions of 2026-10-05 in IT-SKENER-003 §6.3 | that section |
| Runs A, B, C | Runs over list A in IT-SKENER-001 (A, 2026-09-24) and IT-SKENER-002 (B after BUG-003..015, C after BUG-016) | IT-SKENER-002 §3.4 |
| Runs D–H | Runs over list A on 2026-09-27: D (F2 acceptance), E (after the host-variant fix), F (hotspot, first under the profile), G (hotspot), H (fast link on another computer; the input of Z-50). Plus one run from GitHub Actions on 2026-09-28, invalid for Z-51 | `docs/sr/kalibracija.md` |
| List A, list B | List A: the same 100 domains as IT-SKENER-001/002, for calibration. List B: 100 new domains of the same type, no overlap, for validation. Neither is in the repository | [ADR-020](ADR-020-threshold-calibration.md); `docs/sr/plan-testiranja.md` §3 |
| `rad/` | Working folder outside git (`.gitignore`) for lists, per-domain results and filled-in forms | `docs/sr/plan-testiranja.md` §3 |
| `gv-`, `ke-`, `tab-`, `nv-`, `st-`, `pg-` | Test-case id prefixes by technique: boundary value, equivalence class, decision table, invalid class, state transition, error guessing | `docs/sr/plan-testiranja.md` §3; CONTRIBUTING "Test design conventions" |
| ADR-001 to ADR-005, ADR-007 | Never published in this repository | [README](README.md) |
| ADR-012 | English public interface (being written) | [README](README.md) |
