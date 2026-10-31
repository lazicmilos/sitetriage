# SiteTriage

SiteTriage takes a list of domains, usually one or two hundred, scans each site politely and ranks
the ones that deserve a full manual audit. Every ranked site comes with a few sentences, in Serbian
or English, that you can paste into a message, use on a call or type into a contact form. It is
built for web studios and consultants who have a long list of prospects and want to know where to
spend their time. It reads the home page and a small sample of pages and tells you which sites have
problems their owners would care about. The audit itself is still your job, and the tool does not
look for vulnerabilities.

![Screenshot of an HTML report](docs/izvestaj.png)

> The report in the screenshot was produced from the hand-written test set. The full HTML is in
> [`docs/primer-izvestaja.html`](docs/primer-izvestaja.html), in Serbian (`--lang en` gives the same
> report in English). It is a single file with no CDN and opens without a network connection.

## What it deliberately does not do

- It does not scan ports, try to log in, look for vulnerabilities or fill in forms.
- It does not go deeper than the home page and a sample from `sitemap.xml`. When there is no
  sitemap, it takes internal links instead.
- It does not request any path that `robots.txt` disallows. The home page and two probes for a fake
  404 page are the exceptions: they are always opened.
- It does not guess what a business does. The industry is an input, not a conclusion.
- It does not fix anything. The tool reads; it never writes.

## Ethics and responsible use

```
User-Agent: SiteTriage/3.0.0 (+hello@studio.example; Example Web Studio)
```

Every request carries the tool's name, who is scanning and how to reach them. Without that you are
an anonymous bot visiting two hundred sites from one address, and an administrator who blocks you is
doing the right thing. So the User-Agent names the operator, the person running the tool, not the
author of the tool. The tool refuses to send a single request until the operator's name and contact
are set.

On level 2 the browser sends the User-Agent that Chromium reports by itself, with the same identity
appended (`Mozilla/5.0 … HeadlessChrome/141… Safari/537.36 SiteTriage/…`). Ad networks and Google
Fonts choose what to send by User-Agent, and the page should be measured the way a visitor gets it
(BUG-019).

- Never two requests to the same site at the same time, and `www.x.example` and `x.example` count as
  the same site. A global semaphore limits you; a per-site semaphore (always 1) protects them. That
  is the line between a tool and an attack.
- Between two requests to the same site there is a pause of 0.5 to 1 s, longer if `Crawl-delay`
  asks for it (up to 10 s).
- `Disallow` in `robots.txt` is respected.
- A hard budget per domain of 19 requests and 40 seconds: the home page, `robots.txt`, the three
  other host variants (`http`/`https` × with and without `www`), two probes for a fake 404, up to
  four sitemaps and seven sample pages. A 25 s budget was not enough for slow shared hosting, where
  a single page can take three seconds.
- On `429` or `503` the tool gives up on the domain for that run, without retrying.
- An administrator who writes "do not scan us" to the contact in the User-Agent is respected from
  the next run. Their domain goes into an exclusion file (one per line, `#` for comments), set with
  `[operator] exclude_file` or `--exclude`. Every subdomain is excluded too: an entry
  `business.example` also covers `www.business.example` and `blog.business.example`. An excluded
  domain gets no request at all, and the report shows only how many domains were excluded, not
  which.

**Responsible use.** The tool tells you which sites have problems. How you contact their owners is
your responsibility. Cold outreach by email is regulated in
many places (in the EU by the GDPR and the ePrivacy rules, and by national law), so check what
applies to you before you send anything. Also note that each run with level 2 downloads a probe file
from `speed.cloudflare.com` to measure your own connection (see
[load time](#why-the-thresholds-are-what-they-are)); set `[network_profile] probe_url` to use
another server.

### Private addresses are never opened

The tool opens public addresses only. `localhost`, `10.x`, `192.168.x`, `169.254.169.254` and the
other private and special addresses are never opened, not when a public name resolves to them and
not after a redirect. A domain given with an IP address, a port or a user name gets no request at
all. Without this, a web application built on the scanner would let its users look inside the
server (SSRF).

Staging with a port works only when you allow it explicitly:

```toml
[net]
allowed_private = ["staging.example:8123"]
```

In the browser (level 2) the protection cannot see the target of a redirect or a WebSocket, so a web
application in production also needs an egress filter at the network level
([ADR-006](docs/adr/ADR-006-ssrf.md)). Level 1 does not read `HTTP(S)_PROXY` from the environment,
because a proxy would bypass the check.

## Quick start

### Docker (recommended)

The image contains exactly the Chromium that the Playwright version in `pyproject.toml` expects, so
browser measurements behave the same on every machine.

```bash
git clone https://github.com/lazicmilos/sitetriage.git
cd sitetriage
mkdir rad
docker compose build
docker compose run --rm sitetriage pytest -q        # every test must pass
```

`work/` is mounted into the container as `/work`: put your input there, and the reports land there
too. On Linux, set `SITETRIAGE_UID=$(id -u)` and `SITETRIAGE_GID=$(id -g)` first, so the files in
`work/` belong to you. Docker Desktop on Windows and macOS handles that by itself.

### pip

You need Python 3.11 or newer.

```bash
pip install -e '.[browser]'
playwright install chromium
```

Without the `browser` extra, level 1 works and level 2 is skipped with a message.

### Tell it who you are

Before the first scan, set who is scanning. Every site's administrator sees the User-Agent in their
server log, and it has to tell them who is visiting and how to reach them. Create `work/my.toml`:

```toml
[operator]
name = "Example Web Studio"
contact = "hello@studio.example"
```

The environment variables `SITETRIAGE_OPERATOR_NAME` and `SITETRIAGE_OPERATOR_CONTACT` do the same,
and `compose.yaml` passes them into the container. The name may be written in Cyrillic or with
letters like "š" and "đ"; the tool transliterates it to plain Latin for the header, because an HTTP
header accepts only ASCII.

The defaults ship with the tool; your own TOML passed with `--config` overrides only what it sets.
All defaults, with comments, are in [`sitetriage/sitetriage.toml`](sitetriage/sitetriage.toml).

### First scan

```bash
docker compose run --rm sitetriage sitetriage scan /work/leads.csv --config /work/my.toml --out /work/report
```

or, without Docker:

```bash
sitetriage scan leads.csv --config my.toml --out report/
```

The recommended machine has 16 GB of RAM and a connection of at least 50 Mb/s. On it, the target
for a list of 200 domains is 15 minutes or less ([ADR-019](docs/adr/ADR-019-run-duration-and-level2-coverage.md);
not yet measured on such a machine). The tool also works on a weaker machine, just more slowly: the
light level 2 starts as many browsers as the machine can take, one per free GB of memory, at most
two per CPU core and at most 8. You can fix the number with `[browser] light_concurrency`.

## Input and output

The input is a CSV with a header, not a bare list of domains:

```csv
domain,industry,note
hotel-planina.example,hotel,mountain
restoran-centar.example,restaurant,
klinika.example,healthcare,clean control site
```

`industry` is one of `hotel`, `restaurant`, `healthcare`, `ecommerce`, `b2b`, `institution` and
`other`. An empty or unknown value falls back to `other`. The industry changes how much each finding
is worth: a link-preview image matters a lot to a hotel and hardly at all to a b2b site.

The list usually comes out of Excel, so the tool also accepts what Excel writes on a Serbian Windows
system: columns separated by `;` and a file saved in windows-1250 instead of UTF-8. A domain that
appears twice is scanned once, and the first occurrence wins. Errors and warnings name the row, the
way Excel numbers it.

The output folder holds:

| File | What it is |
|---|---|
| `index.html` | the report, for people |
| `findings.csv` | one row per finding, with the client sentence (`message_client`) and the evidence (`evidence_json`) |
| `summary.csv` | one row per domain |
| `report.json` | the whole run, for programs |
| `snapshots/` | the raw data collected for each domain |

`--format` chooses which of the first four are written (`html`, `csv`, `json`, default all three
formats); snapshots are always written. `--lang sr|en` chooses the language of the sentences and of
the report (default `sr`), and `--csv-bom` writes the CSV files as UTF-8 with a BOM, for Excel.

Only working sites are ranked. A site that does not open on the second attempt either, at least 60 s
after the first (`http.second_attempt_after_s`), goes to the "Not working" section, with its own
suggested text. That happens only when the state is certain: the name does not exist in DNS or has
no address, or the server accepts no connection on either https or http
([ADR-013](docs/adr/ADR-013-unreachable-after-second-attempt.md)). A domain without a home page for
any other reason (DNS temporarily unavailable, an interrupted TLS handshake, any HTTP response, an
address that is not public) goes to "Not scanned", with the reason, because the site may work and the
tool just did not see it. That section also shows the number of excluded domains.

### The JSON report

`report.json` is the contract for a web application, `sitetriage diff` (planned), a CRM, or whoever
builds on the code. Its shape is described by the schema
[`sitetriage/schema/report-3.json`](sitetriage/schema/report-3.json), and the schema version is the
first field of the document (`schema_version`, now `3.0`). Next to it are the tool version, the run
time in UTC, the duration of each level, a configuration digest (`config_digest`: the sha256 of the
thresholds, multipliers and points, without the operator identity and concurrency), the environment
(OS, Python, Chromium, network profile, measured link speed) and totals by status. Domains are in
three lists: `ranked`, `unreachable` ("Not working") and `not_scanned` (`failed`, with the cause in
`reason`).

A domain is `partial` for one of two reasons, and `partial_causes` says which: the budget ran out
(`budget`), or a check could not run (`unknown`). The totals count them separately, and
`budget_share` and `unknown_share` give the share of working domains that ran out of budget and the
share of `unknown` for each check. The denominator is the working domains on which the check ran: for
a level-2 check only those that went through level 2, and for load time only those measured under the
network profile ([ADR-015](docs/adr/ADR-015-not-applicable-and-partial-causes.md)). The HTML report
shows both shares under the totals.

A finding in the JSON has no sentence. It has a `check_id`, the evidence and a `variant`, and the
sentence is built from the evidence, in the reader's language.

Rules for changing the schema ([ADR-011](docs/adr/ADR-011-json-sema.md),
[ADR-012](docs/adr/ADR-012-english-public-interface.md)):

- an added field raises the minor version (`3.0` → `3.1`), because an older reader can skip it;
- a removed field, a changed type or meaning of a field, and a renamed `check_id` raise the major
  version (`3.x` → `4.0`).

The schema does not allow unknown fields, so a new field has to go into the schema first. A test
fails if the output does not validate against the schema.

## Other commands

```bash
sitetriage recheck report/snapshots/ --out new/                       # score saved snapshots again, no network
sitetriage recheck report/snapshots/ --config trial-thresholds.toml --out new/
sitetriage recheck report/snapshots/ --lang en --out english/         # the same run, report in English
sitetriage record my-domains.csv --out recordings/                    # record snapshots as fixtures
sitetriage explain seo.canonical.duplicate                            # what a check does, its threshold and sentences
sitetriage explain --all --markdown                                   # the table of checks below
sitetriage scan domains.csv --level 1 --concurrency 4 --only institucija.example --debug-domain institucija.example
```

`recheck` is the main calibration tool. Change a threshold, run it over saved snapshots and see the
difference in a second, without downloading two hundred sites again. Try thresholds in a separate
file that holds only what you change: `--config` overrides only what it sets.

`scan` also takes `--level 1|2|auto`, `--max-level2 N` (the cap for level 2, default 60),
`--snapshots DIR`, `--exclude FILE` and `--debug-domain DOMAIN` (DEBUG log for that domain only).
Run `sitetriage <command> --help` for the full list.

## How it works

The split into level 1 and level 2 matters less than another decision: code that touches the
network and code that draws conclusions live in two separate layers. A check never opens a
connection. It receives data that was already collected and returns results.

```
domains.csv → Fetcher L1 (httpx, async) → SiteSnapshot to disk → L1 checks → findings
                                                                      ↓
                                                              escalation policy
                                                                      ↓
                                     Fetcher L2 (Playwright) → BrowserSnapshot → L2 checks
                                                                      ↓
                                               scoring → ranking → CSV + HTML + JSON
```

Level 1 reads raw HTTP: the home page, `robots.txt`, host variants, sitemaps and a sample of pages.
Level 2 opens the home page in a real Chromium, under a fixed simulated network profile, and
measures weight, requests, load time, headings, images and console errors. Sites with a reason to
look closer get the full level 2, up to a cap of 60; every other working site gets a lighter level
2 without the network profile ([ADR-019](docs/adr/ADR-019-run-duration-and-level2-coverage.md)).

Because the layers are separate, the tests run without a network and always give the same result,
calibration needs no new scan, and when a domain gives an odd result, the exact input that produced
it is saved on disk.

| Module | Responsibility | Network | Disk |
|---|---|---|---|
| `cli` | arguments, logging, reports | no | reads |
| `inputs` | the domain list and other CSV files from Excel; errors and warnings with row numbers | no | no |
| `pipeline` | the order of phases: level 1 → escalation → level 2 → light level 2 → scoring → ranking | through `fetch.*` | through `store` |
| `config` | thresholds from TOML, operator identity | no | reads |
| `models` | data schemas, serialization | no | no |
| `addresses` | which addresses may be opened (SSRF protection) | no | no |
| `fetch.urls`, `fetch.page`, `fetch.robots`, `fetch.sitemap` | normalization and parsing | partly | no |
| `fetch.http` | level 1 | yes | no |
| `fetch.browser` | level 2 | yes | no |
| `checks.*` | the rules: input is a snapshot, output is results | no | no |
| `messages` | client and operator sentences, report labels, suggested text; Serbian and English | no | no |
| `score` | scoring, ranking, escalation | no | no |
| `store`, `report.*` | snapshots and reports | no | writes |

Two architecture rules are enforced by `tests/test_architecture.py`:

- `checks.*` does not import `httpx`, `playwright` or `fetch.*` (except `fetch.urls`), nor
  `pipeline`, `messages` or `report`. If a check needs something from the network, the snapshot is
  missing a field, so the field gets added.
- `cli` does not import `fetch.http`, `fetch.browser` or `score`. The order of phases exists only in
  `pipeline`, so a web application calls it instead of copying it
  ([ADR-008](docs/adr/ADR-008-pipeline.md)).

## Checks

The table is generated from the check registry with `sitetriage explain --all --markdown`. When a
threshold changes, the table is generated again; CI checks that every check in the registry appears
in it.

| `check_id` | Level | Category | Severity | Threshold |
|---|---|---|---|---|
| `i18n.lang.invalid` | 1 | i18n | medium | lang ∈ {zxx, und, empty} or does not parse as BCP-47 |
| `i18n.lang.mismatch` | 1 | i18n | medium | content detected as sr (Cyrillic > 30 % or diacritics > 0.5 %) with the lang of a language not written in Cyrillic or with č/ć/š/ž/đ (not sr, hr, bs, ru, mk, bg…) |
| `i18n.lang.missing` | 1 | i18n | medium | the lang attribute does not exist |
| `infra.host.duplicate` | 1 | infra | medium | the variants return 200 on both hosts (www and without www); low if the canonical on all of them points to the same origin; an unchecked variant of a host that was not seen → unknown |
| `infra.https.redirect.missing` | 1 | infra | medium | https on the final host returns 200 with a valid certificate, and http:// of the same host returns 200 without a redirect to https; TLS error or request not sent → unknown; https not working → not applicable |
| `infra.robots.missing` | 1 | infra | low | status 404 or 410; other statuses except 200 → unknown |
| `infra.sitemap.missing` | 1 | infra | medium | status 404 or 410, or 200 with 0 URLs; other statuses and a sitemap larger than the limit → unknown; has URLs → ok |
| `infra.soft404` | 1 | infra | high | both probes return a final status 200; a status outside {200, 404, 410} → unknown |
| `infra.tls.invalid` | 1 | infra | high | TLS verification rejected the certificate; incomplete chain (no intermediate certificate) → unknown |
| `infra.unreachable` | 1 | infra | critical | both attempts, at least http.second_attempt_after_s (60 s) apart: EAI_NONAME or EAI_NODATA, or the TCP connection refused or timed out on both https and http; any HTTP response → ok |
| `perf.compression.missing` | 1 | perf | low | content-encoding ∉ {gzip, br, zstd, deflate} and HTML > 50 kB |
| `perf.html.size` | 1 | perf | low | html_bytes > thresholds.perf.html_size_kb (500 kB) |
| `perf.redirect.chain` | 1 | perf | low | number of hops ≥ thresholds.perf.redirect_hops (3) |
| `seo.canonical.duplicate` | 1 | seo | critical | ≥ 2 pages with a foreign canonical to the same URL, from ≥ 2 path groups; share of the sample ≥ 0.4 high · ≥ 0.6 critical · otherwise medium |
| `seo.canonical.missing` | 1 | seo | high | no tag on the home page |
| `seo.description.duplicate` | 1 | seo | medium | ≥ 3 pages from ≥ 3 different path groups with the same description |
| `seo.description.missing` | 1 | seo | medium | empty or missing meta description |
| `seo.title.duplicate` | 1 | seo | high | ≥ 3 pages from ≥ 3 different path groups with the same title |
| `seo.title.missing` | 1 | seo | high | empty or missing <title> |
| `social.og.description.missing` | 1 | social | medium | <meta property=og:description> is missing |
| `social.og.image.missing` | 1 | social | medium | <meta property=og:image> is missing |
| `social.og.title.missing` | 1 | social | high | <meta property=og:title> is missing |
| `a11y.img.alt.missing` | 2 | a11y | low | ≥ 5 images and share without an alt attribute > 0.5; > 0.8 with ≥ 15 images → high; healthcare/institution → at least medium |
| `perf.img.oversized` | 2 | perf | medium | ≥ 3 images with a ratio > 2.5 and measured waste, or estimated waste > 700 kB; SVG and data: images do not count |
| `perf.load.time` | 2 | perf | high | > 6 s medium · > 9 s high · cut off after the hard limit = high |
| `perf.page.weight` | 2 | perf | critical | transferred until load, without video: > 2 MB medium · > 4 MB high · > 7 MB critical |
| `perf.request.count` | 2 | perf | high | requests until load: > 60 medium · > 90 high |
| `qa.console.errors` | 2 | qa | low | > thresholds.qa.console_errors (3) |
| `seo.h1.missing` | 2 | seo | high | h1_count == 0 after loading in the browser |
| `seo.h1.multiple` | 2 | seo | low | h1_count > thresholds.seo.h1_multiple (3) |

### Four states

Every check returns one of four states, and the last two always come with a reason:

- `ok`: checked, no problem.
- `finding`: checked, a problem, with evidence.
- `unknown`: the check could not give an answer. Without this state you cannot tell "clean" from
  "not checked", and that difference is exactly what would cost you trust in your own report a month
  later. For example, when a site answers every request with 403 because it blocks bots, the tool
  does not claim that `robots.txt` is missing. It says it does not know.
- `not_applicable`: there is nothing to check. The duplicate checks give it when a site really has
  fewer than three pages. A small sample is not enough to say so, because the sample is also small
  when the budget runs out or when links are drawn by JavaScript. So the tool counts addresses from
  the sitemap, from links on the home page and from links the browser sees, and at least one source
  must see content drawn by JavaScript. When any of these conditions does not hold, the check is
  `unknown`. Unlike `unknown`, `not_applicable` does not make a domain partially scanned. When the
  sitemap lists fewer addresses than the sample needs, the sample is topped up with links from the
  home page ([ADR-015](docs/adr/ADR-015-not-applicable-and-partial-causes.md)).

### Sentences for the site owner

Client sentences claim only what can be verified, and every number in them comes from measured
evidence ([ADR-022](docs/adr/ADR-022-client-sentence-claims.md)). Tests in `tests/test_messages.py`
guard both rules, along with number and noun agreement ("4 glavna naslova", "5 glavnih naslova",
"4 main headings").

A finding carries only evidence: numbers, URLs and technical codes. The catalog in
`sitetriage/messages/` turns it into a sentence at display time, in the language chosen with
`--lang sr|en` ([ADR-009](docs/adr/ADR-009-katalog-poruka.md)). That is why the same run can be shown
in either language. The English sentence claims exactly what the Serbian one claims, no more and no
less, and `sitetriage explain` prints both. The same goes for the reasons why something was not
checked and why a domain was sent to level 2.

## Why the thresholds are what they are

"List A" and "list B" below are two private calibration lists of 100 real Serbian websites each,
mostly small businesses. Thresholds were set from the distribution on list A, then frozen and
validated on list B, which does not overlap with A ([ADR-020](docs/adr/ADR-020-threshold-calibration.md)).
The lists are not published.

| Threshold | Value | Reasoning |
|---|---|---|
| home page weight | 2 / 4 / 7 MB transferred, without video | The rounded p50, p75 and p90 of list A, 58 sites measured up to `load` (2.2, 3.6 and 7.3 MB). What counts is what actually came over the network. JavaScript and CSS travel compressed, so for one site the decompressed bodies added up to 25 MB while 3.8 MB was transferred. Video does not count, because it downloads for as long as the measurement lets it: the same site transferred 77 MB of video in one run and 39 MB in another. Only requests started before the `load` event count, and the same goes for the request count. After `load` come analytics, chat widgets and lazy images, so the same site once had 179 requests and another time 281. The total, including what came after `load`, is only in the technical sentence ([ADR-016](docs/adr/ADR-016-weight-until-load.md), [ADR-020](docs/adr/ADR-020-threshold-calibration.md)). |
| requests up to `load` | 60 / 90 | The rounded p50 and p75 of list A (57 and 87). For checks with two levels, the same percentile gives the same severity as for weight: p50 is medium, p75 is high ([ADR-020](docs/adr/ADR-020-threshold-calibration.md)). |
| time to `load` | 6 / 9 s, under the network profile | The rounded p50 and p75 of list A (5.6 and 9.3 s), measured under the profile from a fast real connection. The 25 s timeout is p95 (22.1 s) plus a reserve ([ADR-020](docs/adr/ADR-020-threshold-calibration.md)). |
| load time measurement | one site at a time | When three sites load at once, they share one connection and slow each other down by up to 4.6 times. So sites load one by one up to the `load` event, while scrolling and reading the page run in parallel ([ADR-018](docs/adr/ADR-018-load-time-validity.md)). |
| diacritics for detecting Serbian | 0.005 | Serbian in Latin script has 2–5 % diacritics, English none. The threshold is ten times lower than expected so that it holds on short texts, and still ten times above the noise. |
| wrong language tag | medium | Google determines a page's language from its content and does not use `lang`. The consequence is accessibility (screen readers), not search position ([ADR-022](docs/adr/ADR-022-client-sentence-claims.md)). |
| uncompressed HTML | low | On the HTML alone the saving is tenths of a second. The sentence says exactly how much, computed from the size. |
| ratio for oversized images | 2.5 | Screens with `devicePixelRatio` 2 legitimately ask for an image twice as large. A threshold of 2 would call every correctly built retina site broken. |
| duplicates | ≥ 3 pages from ≥ 3 path groups | Eight blog posts with the same template title are not the same as a whole site that presents itself to Google as a single page. |
| empty HTML for escalation | 800 characters | Deliberately different from the threshold of the language heuristic (400): 400 is the limit of reliable language detection, 800 the limit of "this looks like empty HTML". |
| slow home page for escalation | 1500 ms | The only condition that catches a site with clean SEO and a slow page. |
| cap for level 2 | 60 domains | Without a cap, almost every site on a 200-domain list goes to level 2 and a run takes an hour. Sites without a strong level-1 finding go first, because for them level 2 is the only chance to find anything; a site that already has a strong finding already has a reason to be contacted. Every other site with a working home page gets light level 2: a browser without the network profile, several sites at once, after the full level 2. It measures weight, requests, `h1`, `alt` and images, and load time is "not applicable", so the site is not `partial` because of it. Fast, clean HTML says nothing about page weight: on list B two pages of 4.8 and 4.9 MB had no escalation reason at all (BUG-020; [ADR-019](docs/adr/ADR-019-run-duration-and-level2-coverage.md)). |
| unmeasured responses | > 5 → `unknown` | A measurement you do not trust is worse than one you do not have. |
| points per severity | 40 / 20 / 8 / 3 | The spacing is deliberately non-linear: one `critical` must outweigh five `low` findings. |
| level-2 network profile | 4.8 Mb/s (0.6 MB/s) down, 1.5 Mb/s up, 150 ms latency | Level 2 measures under this simulated connection (`[network_profile]`), so the same site gives the same time on a home connection, on a server and at a customer's. The seconds in client sentences are computed from the same speed, and the sentence states it. You have to be able to defend a number you send to a client. The CPU is not simulated, so time still depends slightly on the machine; the network part is fixed ([ADR-010](docs/adr/ADR-010-mrezni-profil.md)). The profile can only slow a connection down, so before level 2 the tool downloads a probe file (`probe_url`, by default from `speed.cloudflare.com`) and measures the real connection. If it is slower than 2 × the profile, load time is `unknown`, because it would be overstated ([ADR-018](docs/adr/ADR-018-load-time-validity.md)). |

Ranking is not by total but by the pair (most severe single finding, total). A site with one disaster
is a better lead than a site with ten small issues: the first has one clear reason to answer you,
and few people answer a list of ten items. Points are multiplied by an industry multiplier per
category (`[industry_multipliers.*]`); the multiplier changes the weight of a finding, never its
severity.

All thresholds live in [`sitetriage/sitetriage.toml`](sitetriage/sitetriage.toml), not in code, so `git diff` on it is a
readable history of calibration decisions. The calibration log behind them is
[`docs/sr/kalibracija.md`](docs/sr/kalibracija.md) (in Serbian); the decisions themselves are
summarized in English in the [ADRs](docs/adr/README.md).

Both lists come from one country and are mostly small businesses and associations. For other
industries and markets the distributions may differ, so repeat the calibration on your own lists
with `recheck`.

## Tests

```bash
docker compose run --rm sitetriage pytest -q               # offline, with a real Chromium, about 4 min
docker compose run --rm -e SITETRIAGE_LIVE_CSV=/work/live.csv sitetriage pytest -m live -v   # real sites from your own list; needs a network
```

The first layer does not depend on the network and runs in CI on every push. It covers every check
on snapshots, scoring, URL normalization and sitemap parsing. It also has integration tests against
a local HTTP server that serves broken sites on purpose: a slow response body, a stream that never
ends, bot protection, a sitemap in nine parts. That is how the per-domain budget, the pauses, the
semaphores and the browser measurements are tested. The second layer goes to real sites and is off
by default; otherwise CI would fail every time some site's certificate expired. The repository names
no real site: you give the list through `SITETRIAGE_LIVE_CSV`, a CSV in the format of
`domains.example.csv` (see `tests/test_live.py` for the optional column of expected findings).

The baseline is a clean site on which no check may find anything. Each positive test breaks exactly
one thing and checks that no other check woke up. Thresholds have boundary value tests (limit − 1,
limit, limit + 1), and rules with several conditions have decision tables. The test technique is in
the name of each case: `gv-` boundary value, `ke-` equivalence class, `tab-` decision table, `st-`
state transition, `pg-` error guessing (the prefixes come from the Serbian names of the techniques).

CI fails if line and branch coverage drops below 95 %. Mutation testing measures the quality of the
tests themselves: mutmut breaks the code on purpose, and the tests have to notice every change that
alters behaviour. mutmut 3.2.3 does not create mutants inside decorated functions, so it does not
mutate check bodies (`@check`). It runs through Docker, because mutmut does not work on Windows, and
takes about 20 minutes:

```bash
docker compose run --rm sitetriage python scripts/mutation.py
```

> The fixtures in `tests/fixtures/` are hand-written, not recorded from real sites. They describe
> what the specification says about those eight domains and check that the chain of checks works on
> that state, with the specification's thresholds. The domains are made up (`.example`). Real sites
> are checked by `pytest -m live`, over the list in `SITETRIAGE_LIVE_CSV`.

How to set up, run the tests and add a check is in [CONTRIBUTING.md](CONTRIBUTING.md). Before a
release that changes fetching or thresholds, run the [real-site verification](docs/real-site-verification.md)
and the [manual check](docs/manual-check-form.md). The history of how v1 and v2 were tested (test
plan, three test reports, calibration log and an ISO/IEC 25010 review) is in
[`docs/sr/`](docs/sr/README.md), in Serbian.

## Contributing, security, code of conduct and license

- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests, architecture rules, adding a check.
- [SECURITY.md](SECURITY.md): report a vulnerability privately, not in a public issue.
- [Code of Conduct](CODE_OF_CONDUCT.md) applies to everyone taking part in the project.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release.
- [docs/](docs/README.md): architecture decision records and procedures.
- The code is under the [MIT](LICENSE) license.

## Roadmap: not in v3

- `sitetriage diff` between two runs and `sitetriage outcomes` (which leads answered and turned into
  work). They come once there is a real subscription. "Since March the site has become 3 MB heavier"
  is a good opening for an email.
- A check for "home page with almost no content": a home page that has almost no text even after
  JavaScript (a splash page with one button, a parked domain) is the strongest argument for an
  email, and today it is not a finding. Of 160 home pages on lists A and B, 4 have fewer than 200
  characters; the limit will be calibrated on A and B.
- Core Web Vitals (LCP, CLS): useful numbers, but they need more careful measurement.
- CPU emulation, so that load time no longer depends slightly on the machine.
- A check for structured data (`schema.org`), which has real value for restaurants and clinics.
- CMS detection (WordPress, Wix, custom-built), because it changes how an offer is written.
