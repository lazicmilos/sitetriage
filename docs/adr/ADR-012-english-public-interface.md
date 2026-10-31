# ADR-012: English public interface (SiteTriage 3.0)

```
Status:  Accepted
Date:    2026-10-31
Author:  Milos Lazic
```

## Context

The project began as `skener`, a Serbian tool built for one operator. Its code, configuration,
report data and documentation were all in Serbian. It is now being open-sourced as SiteTriage under
the MIT license, and most of its future users and contributors will not read Serbian. Every public
name in Serbian (the command, the config keys, the environment variables, the industry values, the
evidence keys in `report.json`) is something they have to look up before they can use the output
or write an integration.

Nothing has been released under the new name yet, and nobody outside the project reads the
reports, so a clean break costs almost nothing today. After the first public release, each of these
renames would break someone.

Under [ADR-011](ADR-011-json-sema.md), renaming or removing a field in `report.json` raises the
major schema version. Renaming the evidence keys changes the shape of every finding, so this is a
3.0 change.

The migration to English runs in waves:

- Wave A, this ADR, covers the public interface and the v3.0.0 data contract.
- Wave B renames internal identifiers and translates comments, docstrings, log and error messages
  and test names. Several contributors do it in parallel, one directory each.
- Wave C translates the documentation and the older ADRs, and moves the Serbia-specific parts into
  a profile.

## Decision

1. Everything that leaves the program or is read back by it is in English: the package and the
   command, the config file and its keys, the environment variables, industry values, evidence
   keys and evidence code values, the JSON schema, and the HTML report title. The full mapping is
   in the tables below.
2. The old names get no aliases. If a user config still has the old section or an old industry
   table, the tool stops with an error that names the new key. A setting that is silently ignored
   does more harm than an error.
3. `check_id`s, reason codes, JSON field names, CSV column names, snapshot field names and status
   names were already in English and do not change.
4. The Serbian and English message catalogs keep their sentences word for word; only the
   placeholders change to the new evidence keys. The golden files in `tests/golden/` did not change,
   and the tests compare against them.
5. The report schema is `sitetriage/schema/report-3.json`, with `schema_version` `"3.0"`.
   `report-2.json` is removed.
6. Snapshot field names do not change, so the snapshot format is not versioned separately.
   `scanner_version` in each snapshot still records which version wrote it. Snapshots from 1.x and
   2.x stay readable: `recheck` maps the old industry values when it reads them (see
   [Snapshots](#snapshots)).
7. The version is `3.0.0.dev0` until the release, which shipped as 3.0.0 on 2026-10-31.
8. Wave B uses the glossary at the end of this ADR. An identifier that contains one of its Serbian
   terms gets the English term listed there. That way two people renaming different directories
   pick the same name for the same thing.

## Mapping

### Package, command and repository

| Old | New |
|---|---|
| Python package `skener` | `sitetriage` |
| distribution name `skener` | `sitetriage` |
| command `skener` (`skener.cli:main`) | `sitetriage` (`sitetriage.cli:main`) |
| `skener --version` → `skener X.Y.Z` | `sitetriage --version` → `sitetriage X.Y.Z` |
| `pip install 'skener[browser]'` | `pip install 'sitetriage[browser]'` |
| Docker Compose service `skener`, image `skener:dev` | service `sitetriage`, image `sitetriage:dev` |
| `docker compose run --rm skener skener scan …` | `docker compose run --rm sitetriage sitetriage scan …` |
| logger names `skener`, `skener.fetch`, `skener.browser` (the `logger` field of JSON log lines) | `sitetriage`, `sitetriage.fetch`, `sitetriage.browser` |
| `https://github.com/lazicmilos/skener` | `https://github.com/lazicmilos/sitetriage` |
| HTML report title `Skener — izveštaj` / `Skener — report` | `SiteTriage — izveštaj` / `SiteTriage — report` |
| HTML report heading `Skener sajtova — izveštaj` / `Website scanner — report` | `SiteTriage — izveštaj` / `SiteTriage — report` |

### Config file

| Old | New |
|---|---|
| `skener.toml` (repository root, default config; `--config` is merged over it) | `sitetriage.toml`, same meaning, comments in English; shipped inside the package as `sitetriage/sitetriage.toml`; a `sitetriage.toml` in the working directory is not read unless passed with `--config`, and then it is merged over the defaults like any other file (BUG-04) |

### Config keys

Every other section and key (`[http]`, `[net]`, `[sitemap]`, `[escalation]`, `[browser]`,
`[network_profile]`, `[thresholds.*]`, `[report]`, `[severity_points]`) was already English and
is unchanged.

| Old | New |
|---|---|
| `[identitet]` | `[operator]` |
| `identitet.naziv` | `operator.name` |
| `identitet.kontakt` | `operator.contact` |
| `identitet.izuzeti` | `operator.exclude_file` |
| `http.user_agent` placeholders `{verzija}`, `{kontakt}`, `{naziv}` | `{version}`, `{contact}`, `{name}` |
| `[industry_multipliers.restoran]` | `[industry_multipliers.restaurant]` |
| `[industry_multipliers.zdravstvo]` | `[industry_multipliers.healthcare]` |
| `[industry_multipliers.institucija]` | `[industry_multipliers.institution]` |
| `[industry_multipliers.ostalo]` | `[industry_multipliers.other]` |

The `operator` section, the concurrency keys, `http.user_agent` and `browser.executable_path` stay
out of `config_digest`, as before. The digest still changes in 3.0, because the multiplier table
names are part of it.

### Environment variables

| Old | New |
|---|---|
| `SKENER_NAZIV` | `SITETRIAGE_OPERATOR_NAME` |
| `SKENER_KONTAKT` | `SITETRIAGE_OPERATOR_CONTACT` |
| `SKENER_CHROMIUM` | `SITETRIAGE_CHROMIUM` |
| `SKENER_LIVE_CSV` (`pytest -m live`) | `SITETRIAGE_LIVE_CSV` |
| `SKENER_UID`, `SKENER_GID` (`compose.yaml`) | `SITETRIAGE_UID`, `SITETRIAGE_GID` |

### Industry values

These are used in the `industry` column of the input CSV, in `[industry_multipliers.*]`, in
`DomainReport.industry` (JSON, CSV, HTML) and in `SiteSnapshot.industry`. An empty or unknown value
still falls back to `other`, with a warning.

| Old | New |
|---|---|
| `hotel` | `hotel` |
| `restoran` | `restaurant` |
| `zdravstvo` | `healthcare` |
| `ecommerce` | `ecommerce` |
| `b2b` | `b2b` |
| `institucija` | `institution` |
| `ostalo` | `other` |

### Evidence keys of findings

One Serbian word can become different English keys depending on what it holds: `stranica` is the
page URL in the `*.missing` checks and a page count in the `*.duplicate` checks. That is why the
table goes check by check. Keys that were already English (`status`, `kb`, `mb`,
`video_mb`, `load_ms`, `h1_count`, `reached`, `lang`, `canonical`, `valid`) are not listed.

| `check_id` | Old key | New key | Holds |
|---|---|---|---|
| `a11y.img.alt.missing` | `bez_alta` | `without_alt` | images without an `alt` attribute |
| | `ukupno` | `total` | images in total |
| | `prazan_alt` | `empty_alt` | images with `alt=""` |
| | `udeo` | `share` | share without `alt` |
| | `nemereno` | `unmeasured` | images that were not measured |
| `i18n.lang.missing` | `stranica` | `page` | URL |
| | `lang_oznaka` | `lang_tag_count` | always 0 |
| | `izvor` | `source` | code, see below |
| `i18n.lang.invalid` | `stranica` | `page` | URL |
| | `duzina_koda` | `code_length` | length of the `lang` value |
| | `izvor` | `source` | code |
| `i18n.lang.mismatch` | `stranica` | `page` | URL |
| | `prepoznat_jezik` | `detected_language` | `sr` |
| | `cirilica_udeo` | `cyrillic_share` | share of Cyrillic letters |
| | `dijakritici_udeo` | `diacritic_share` | share of č/ć/š/ž/đ among Latin letters |
| | `duzina_teksta` | `text_length` | characters of text |
| | `izvor` | `source` | code |
| `infra.host.duplicate` | `adrese` | `hosts` | list of hosts |
| | `broj_adresa` | `host_count` | number of hosts |
| | `isti_canonical` | `same_canonical` | 0 or 1 |
| `infra.https.redirect.missing` | `http_adresa` | `http_url` | URL |
| | `https_adresa` | `https_url` | URL |
| `infra.robots.missing` | (only `status`) | | |
| `infra.sitemap.missing` | `broj_urlova` | `url_count` | URLs in the sitemap |
| `infra.soft404` | `broj_sondi` | `probe_count` | number of probes |
| | `slicnost` | `similarity` | 0–1 |
| | `tvrd_dokaz` | `hard_evidence` | boolean |
| `infra.tls.invalid` | `greska` | `error` | raw TLS error |
| `infra.unreachable` | `razlog` | `cause` | code, see below |
| | `broj_pokusaja` | `attempt_count` | number of attempts |
| | `prvi_pokusaj` | `first_attempt` | UTC time |
| | `drugi_pokusaj` | `second_attempt` | UTC time (the last attempt) |
| | `detalj` | `detail` | raw error |
| `perf.compression.missing` | `kodiranje` | `encoding` | `content-encoding` or `null` |
| | `bajtova` | `bytes` | HTML bytes |
| | `usteda_s` | `saving_s` | seconds saved |
| | `brzina` | `speed_mbps` | profile speed |
| `perf.html.size` | `bajtova` | `bytes` | HTML bytes |
| | `prag_kb` | `threshold_kb` | threshold |
| `perf.img.oversized` | `broj_slika` | `image_count` | oversized images |
| | `prag_odnosa` | `ratio_threshold` | threshold |
| | `nemereno` | `unmeasured` | images that were not measured |
| | `najgora` | `worst_image` | URL of the worst image |
| `perf.load.time` | `sekundi` | `seconds` | seconds |
| | `brzina` | `speed_mbps` | profile speed |
| `perf.page.weight` | `bajtova` | `bytes` | bytes until `load` |
| | `sekundi` | `seconds` | estimated seconds |
| | `brzina` | `speed_mbps` | profile speed |
| | `zahteva` | `requests` | requests until `load` |
| | `nemereno` | `unmeasured` | unmeasured responses |
| | `po_tipu` | `bytes_by_type` | bytes per resource type |
| | `ukupno_bajtova` | `total_bytes` | bytes including after `load` |
| | `ukupno_zahteva` | `total_requests` | requests including after `load` |
| `perf.redirect.chain` | `skokova` | `hops` | number of hops |
| | `lanac` | `chain` | list of URLs |
| `perf.request.count` | `zahteva` | `requests` | requests until `load` |
| | `ukupno_zahteva` | `total_requests` | requests including after `load` |
| `qa.console.errors` | `greske` | `errors` | console errors |
| | `upozorenja` | `warnings` | console warnings |
| | `primer` | `first_error` | first error message |
| `seo.canonical.missing` | `stranica` | `page` | URL |
| | `broj_canonical_oznaka` | `canonical_tag_count` | always 0 |
| `seo.canonical.duplicate` | `stranica` | `page_count` | pages with that canonical |
| | `ukupno` | `total` | pages in the sample |
| | `udeo` | `share` | share in the sample |
| | `grupa_putanja` | `path_groups` | number of path groups |
| | `uzorak` | `sample` | code, see below |
| `seo.description.missing` | `stranica` | `page` | URL |
| | `duzina_opisa` | `description_length` | always 0 |
| `seo.description.duplicate` | `opis` | `description` | the description |
| | `stranica` | `page_count` | pages with that description |
| | `grupa_putanja` | `path_groups` | number of path groups |
| | `uzorak` | `sample` | code |
| `seo.h1.multiple` | `prag` | `threshold` | threshold |
| `seo.title.missing` | `stranica` | `page` | URL |
| | `duzina_naslova` | `title_length` | always 0 |
| `seo.title.duplicate` | `naslov` | `title` | the title |
| | `stranica` | `page_count` | pages with that title |
| | `grupa_putanja` | `path_groups` | number of path groups |
| | `uzorak` | `sample` | code |
| `social.og.title.missing`, `social.og.description.missing`, `social.og.image.missing` | `stranica` | `page` | URL |
| | `og_oznaka_ukupno` | `og_tag_count` | `og:` tags on the page |

### Evidence code values and variants

| Where | Old | New |
|---|---|---|
| `source` (`i18n.lang.*`) | `sirovi_html` | `raw_html` |
| | `nivo2` | `rendered` |
| `error` (`infra.tls.invalid`) when the TLS error has no message | `nepoznata` | `unknown` |
| `variant` of `infra.host.duplicate` | `isti_canonical` | `same_canonical` |
| `sample` | `sitemap`, `links`, `none` | unchanged |
| `cause` | `dns`, `no_response` | unchanged |
| `variant` of `perf.page.weight`, `perf.load.time` | `video`, `timeout` | unchanged |

The catalogs turn these codes into words through `CODES`, so the sentences read the same as
before. The Serbian catalog gained an `error` table for one reason: to keep printing `nepoznata`
for `unknown`.

### Evidence keys of reasons

`Reason.code` values were already English and do not change. Their evidence keys:

| Reason code | Old key | New key |
|---|---|---|
| `v1_snapshot` | `verzija`, `polje` | `version`, `field` |
| `check_crashed` | `greska` | `error` |
| `probe_status` | `statusi` | `statuses` |
| `tls_no_connection` | `vrsta` | `kind` |
| `tls_over_http` | `vrsta`, `detalj` | `kind`, `detail` |
| `unmeasured_responses` | `nemereno`, `prag` | `unmeasured`, `threshold` |
| `images_unmeasured` | `nemereno`, `ukupno` | `unmeasured`, `total` |
| `oversized_unmeasured` | `broj` | `count` |
| `text_too_short`, `text_too_short_rendered` | `duzina`, `prag` | `length`, `threshold` |
| `unreachable_unsure` | `vrsta`, `pokusaja` | `kind`, `attempts` |
| `pages_budget`, `pages_js` | `prag` | `threshold` |
| `pages_sample`, `few_pages` | `prag`, `adresa` | `threshold`, `address_count` |
| `variant_unchecked` | `adresa`, `vrsta` | `url`, `kind` |
| `no_https` | `adresa` | `url` |
| `link_slow` | `izmereno`, `potrebno` | `measured_mbps`, `required_mbps` |
| `entry_error` | `vrsta`, `detalj` | `kind`, `detail` |
| `raw_text_short` | `znakova`, `prag` | `chars`, `threshold` |
| `html_large` | `bajtova`, `prag` | `bytes`, `threshold` |
| `slow_entry` | `prag` | `threshold` (`ms` unchanged) |
| `sitemap_status`, `robots_status`, `entry_status` | `status` | unchanged |

### Message catalog text placeholders

These are not evidence. They are the keyword arguments that `report/html_out.py` passes to
`messages.text()`, and they were renamed in the same change:

| `TEXT` key | Old | New |
|---|---|---|
| `percent`, `share_budget` | `{udeo}` | `{share}` |
| `not_applicable` | `{tekst}` | `{text}` |
| `draft_unreachable` | `{recenica}` | `{sentence}` |

### JSON report

| Old | New |
|---|---|
| `skener/schema/report-2.json`, `$id` `https://github.com/lazicmilos/skener/schema/report-2.json` | `sitetriage/schema/report-3.json`, `$id` `https://raw.githubusercontent.com/lazicmilos/sitetriage/main/sitetriage/schema/report-3.json` |
| `schema_version` `"2.0"` | `"3.0"` |
| `ranked[].industry` and the other domain lists: Serbian enum | English enum (see [Industry values](#industry-values)) |
| `findings[].evidence`, `reason.evidence` keys | see the tables above |
| schema `title` and `description` texts in Serbian | in English |

No field of `report.json` was renamed; the field names in `models.py` were already English.

### CSV columns

No column was renamed. `findings.csv` (`domain, industry, rank, check_id, level, category, severity, weight,
message_client, evidence_json, evidence_url, scanned_at`) and `summary.csv` (`domain, industry,
rank, status, level2_ran, total_score, max_finding_weight, findings_count, unknowns_count,
top_check_id`) keep their columns. The `industry` values and the keys inside `evidence_json`
change as described above.

### Snapshots

| Old | New |
|---|---|
| `SiteSnapshot.industry` Serbian values | English values; old ones are mapped on read (`store.LEGACY_INDUSTRIES`) |
| directory for a domain with no usable name: `snapshots/nepoznat-domen/` | `snapshots/unknown-domain/` |
| field names | unchanged (all English) |

`recheck` reads snapshots from 1.x, 2.x and 3.x. The field names did not change, so a separate
format version would not protect anything and there is none. Only the industry value needs a
migration. Without it, an old `restoran` snapshot would get the `other` multipliers and a different
score, and nothing would say so.

Snapshots still carry some Serbian free text: `budget.aborted_reason`, some
`SnapshotError.detail` values and `entry.error_detail` for blocked addresses. They are messages, and
Wave B translates them where they are produced. They can show up in evidence as `detail`, but no
check or score depends on their wording.

## Consequences

- An operator coming from 2.x renames `[identitet]` and the four Serbian industry tables in their
  own config, renames the environment variables, and updates the `industry` column of their lists.
  An old config name stops the tool with an error. An old CSV value falls back to `other`, with a
  warning for each row.
- Integrations that read `report.json` must check for `schema_version` `3.0` and read the new
  evidence keys. A future `sitetriage diff` will not compare a 2.x report with a 3.x report
  (ADR-011).
- `config_digest` values from 2.x do not match 3.x, even when the thresholds are the same.
- Old snapshots, including the calibration lists A and B, can still be rechecked.
- Waves B and C can rename internal code without touching the contract. If a test fails after an
  internal rename, a public name was missed here.

## Glossary for Wave B

Use this glossary to rename identifiers; prose is Wave C's job. When a Serbian term appears in a
function, variable, constant, parameter, test name or fixture, use the English term from this list,
in snake_case or UPPER_CASE. If a term is missing, pick a name, use it the same way everywhere, and
add it here in the same PR.

### Pipeline, levels and runs

| Serbian | English | Notes |
|---|---|---|
| prolaz | run | one scan over the list; `prolaz_u_velikom` → `large_run`; `prolazi` in tests is "passes" |
| nivo, nivoa | level | `nivo1` → `level1`, `nivo2` → `level2` |
| lagani nivo 2, lagano | light level 2, light | as in `level2_light` |
| pun nivo 2 | full level 2 | `level2_full` |
| faza, faze | phase | `FAZE` → `PHASES` |
| eskalacija, eskalirati | escalation, escalate | |
| izbor, izabrani | selection, chosen | |
| kandidat | candidate | |
| ponovni pokušaj, pokušaj, pokušaji | retry, attempt, attempts | |
| drugi pokušaj | second attempt | |
| događaj | event | |
| napredak, traka napretka | progress, progress bar | |
| brojač | counter | |
| trajanje | duration | |
| vreme | time | |
| sat (in tests) | clock | |
| rok, limit, tvrdi limit | deadline, limit, hard limit | |
| granica | limit, boundary | in tests: boundary, as in boundary value |
| budžet, budzet | budget | |
| potrošen budžet | budget exhausted | |
| odustati, odustani | give up | `ODUSTANI_STATUSI` → `GIVE_UP_STATUSES` |
| pauza | delay, pause | |
| red (waiting) | queue | `red` is also "row" in a CSV; see below |
| paralelizam, uporedo | concurrency, in parallel | |
| semafor | semaphore | |
| petlja | loop | |
| okruženje | environment | |
| otisak (konfiguracije) | digest | `config_digest` |
| spajanje, spojiti | merge | |

### Site, pages and addresses

| Serbian | English | Notes |
|---|---|---|
| sajt, sajtovi | site, sites | |
| domen, domeni | domain, domains | |
| početna, početna strana | home page | `home`; the first request for it is the `entry` |
| ulaz, ulazni zahtev | entry, entry request | the fetch of the home page; "ulaz" as user input is `input` |
| strana, stranica, stranice | page, pages | as a count: `page_count` |
| uzorak | sample | the sampled pages |
| izvor uzorka | sample source | `sample_source` |
| mapa sajta | sitemap | |
| podmapa | nested sitemap | |
| grupa putanja | path group | |
| putanja | path | |
| adresa | url, address, host | a URL → `url`; an IP address → `address`; a host name → `host`; a count → `address_count` |
| adrese | urls, addresses, hosts | |
| poreklo | origin | scheme + host |
| šema, sema | scheme, schema | URL scheme (`http`/`https`) → `scheme`; JSON schema → `schema` |
| varijanta hosta, varijante | host variant, variants | http/https × www/without www |
| preusmerenje | redirect | |
| lanac (preusmerenja) | chain, redirect chain | |
| skok, skokova | hop, hops | |
| konačni (URL) | final | `final_url` |
| veza | link, connection | a hyperlink → `link`; a network connection → `connection`; measured speed → `link_mbps` |
| interne veze | internal links | |
| tuđi (canonical) | foreign | `tudji_canonical` → `foreign_canonical` |
| sonda, sonde | probe, probes | soft-404 probes |
| lažni 404 | soft 404 | |
| sertifikat | certificate | |
| zahtev, zahteva | request, requests | |
| odgovor | response | |
| telo (odgovora) | body | |
| zaglavlje | header | |
| preuzimanje | download | |
| prenos, preneto | transfer, transferred | |
| sažimanje, kompresija, kodiranje | compression, encoding | |
| težina (strane) | weight | page weight in bytes; in scoring it is the finding `weight` |
| učitavanje | loading, load | |
| merenje, meren, izmereno | measurement, measured | |
| nemereno, nemerena | unmeasured | |
| sirovi HTML | raw HTML | `raw_html` |
| nacrtana / renderovana stranica, posle JS-a | rendered page | `rendered` |
| slika, slike | image, images | |
| prevelika / predimenzionirana slika | oversized image | |
| višak | waste, excess | `est_waste_kb` |
| odnos | ratio | |
| konzola | console | |
| čuvar (adresa) | address guard | `_cuvar` → `_address_guard` (the level-2 route that refuses non-public addresses) |
| razlog odbijanja | refusal reason | `_zasto_odbiti` → `_refusal_reason` |
| broj konteksta | context count | `_konteksta` → `_context_count` |
| slobodna memorija | available memory | `_slobodno_kb` → `_available_kb` |
| statusi bez tela | no-body statuses | `BEZ_TELA` → `NO_BODY_STATUSES` |
| raspakivanje | decoding, decoder | `_Raspakivanje` → `_Decoder`; `RASPAKOVANO_ODJEDNOM` → `DECOMPRESSED_PER_STEP` |
| lanac uzroka (izuzetka) | cause chain | `_lanac` → `_cause_chain` |
| kontekst (browsera) | context | |
| mrežni profil | network profile | |
| brzina | speed | |
| kašnjenje | latency | |
| privatna adresa, dozvoljena, zabranjena | private address, allowed, blocked | `dozvoljene_adrese` → `allowed_addresses`; `dozvoljen` → `allowed` |

### Checks, findings and scoring

| Serbian | English | Notes |
|---|---|---|
| provera, provere | check, checks | |
| registar | registry | |
| nalaz, nalazi | finding, findings | |
| ishod | outcome | |
| rezultat, rezultati | result, results | |
| dokaz | evidence | |
| tvrd dokaz | hard evidence | |
| razlog, razlozi | reason, reasons | |
| uzrok | cause | `partial_causes`; `uzrok_partial` → `partial_cause` |
| preduslov | requirement | `requires` |
| nepoznato | unknown | the `unknown` status |
| ne primenjuje se | not applicable | `not_applicable` |
| delimično | partial | |
| ne rade, ne radi | unreachable | the "Ne rade" list |
| nije skenirano | not scanned | |
| neuspešno | failed | |
| izuzeti, izuzet, izuzeto | excluded | |
| izuzimanje | exclusion | |
| prag, pragovi | threshold, thresholds | |
| udeo | share | |
| ukupno | total | |
| broj | count, number | |
| zbir | total, sum | the scoring total is `total_score` |
| skor | score | |
| bodovi, bodovanje | points, scoring | |
| množilac | multiplier | |
| ozbiljnost | severity | `OZBILJNOST` → `SEVERITY` |
| rangiranje, rang | ranking, rank | |
| najteži nalaz | worst finding | `max_finding_weight` |
| delatnost | industry | |
| izložene delatnosti | exposed industries | `IZLOZENE_DELATNOSTI` → `EXPOSED_INDUSTRIES` |
| duplikat, duplikati | duplicate, duplicates | |
| premalo stranica | too few pages | `_premalo_stranica` → `_too_few_pages` |
| jezik | language | |
| oznaka (jezika, og) | tag | `lang_tag_count`, `og_tag_count` |
| prepoznat jezik | detected language | |
| ćirilica, latinica | Cyrillic, Latin script | |
| dijakritici | diacritics | `DIJAKRITICI` → `DIACRITICS` |
| neodređeno (language) | undetermined | the return value of `detect_language`, internal only |
| sličan srpskom | similar to Serbian | `SLICNI_SRPSKOM` → `SIMILAR_TO_SERBIAN` |
| sličnost | similarity | |
| naslov | title, heading | `<title>` → `title`; `h1` → `heading` |
| opis | description | |
| novo polje (v2:) | new field | `NOVO_POLJE` → `NEW_FIELD_PREFIX` |
| ne postoji | not found | `NE_POSTOJI` → `NOT_FOUND_STATUSES` |
| neproverena | unchecked | `NEPROVERENA` → `UNCHECKED_KINDS` |
| rade (sajtovi koji rade) | working | `RADE` → `WORKING_STATUSES` |
| bez uticaja na rezultat | does not affect the result | `BEZ_UTICAJA_NA_REZULTAT` → `NOT_IN_DIGEST` |
| pozitivni celi brojevi | positive integers | `POZITIVNI_CELI` → `POSITIVE_INTS` |

### Messages and reports

| Serbian | English | Notes |
|---|---|---|
| poruka, poruke | message, messages | `test_poruke` → `test_messages` |
| rečenica | sentence | |
| rečenica za klijenta | client sentence | `client` |
| tehnička rečenica / formulacija | technical sentence | `tech` |
| katalog (poruka) | catalog | |
| šablon | template | |
| oblik (reči) | form | plural forms; `oblik` → `form` |
| jednina, paukal, množina | singular, paucal, plural | |
| sa brojem | with number | `sa_brojem` → `with_number` |
| decimalni | decimal | |
| izveštaj, izveštaji | report, reports | |
| zbir po statusu | summary | |
| predlog teksta, nacrt (mejla) | suggested text, draft | `email_draft` stays |
| oznaka (u izveštaju) | label | |
| kartica | card | |
| kolona | column | |
| red (CSV, tabela) | row | |
| zaglavlje (CSV) | header | |

### Operator, configuration and input

| Serbian | English | Notes |
|---|---|---|
| operater | operator | |
| identitet | identity, operator identity | |
| naziv, ime | name | |
| kontakt | contact | |
| konfiguracija | configuration, config | |
| ključ | key | |
| vrednost | value | |
| sekcija | section | |
| polje | field | |
| verzija | version | |
| lista domena | domain list | |
| unos (u fajlu izuzetih) | entry | |
| poddomen | subdomain | |
| greška | error | |
| upozorenje | warning | |
| detalj | detail | |
| vrsta (greške) | kind | `error_kind` |
| primer, primeri | example, examples | `PRIMER` in `cli.py` → `EXAMPLES` |
| fajl, folder, putanja do fajla | file, directory, path | |
| ceo broj | integer | `_ceo_broj` → `_int_at_least` |
| pročitaj, čitanje | read | |
| piši, upis | write | |

### Snapshots and fixtures

| Serbian | English | Notes |
|---|---|---|
| snimak, snimci | snapshot, snapshots | |
| snimi, snimiti | record | the `record` command |
| snimljeno | recorded | |
| fixture-i | fixtures | |
| ispitni skup | test set | `test_ispitni_skup` → `test_reference_set` |
| lista A, lista B | list A, list B | the calibration and validation lists |
| kalibracija | calibration | |
| merenje saobraćaja | traffic measurement | |

### Tests

| Serbian | English | Notes |
|---|---|---|
| slučaj, slučajevi | case, cases | `poruke_slucajevi` → `message_cases` |
| očekivano | expected | |
| dobijeno | actual | |
| čist (sajt) | clean (site) | `clean_site` |
| loš, pokvaren | broken | |
| lažni (sajt, server) | fake | `FakeSite` |
| lokalni server | local server | |
| pozitivni (slučajevi) | positive cases | `POZITIVNI` → `POSITIVE_CASES` |
| zlatni fajl | golden file | `GOLDEN`, `GOLDEN_RAZLOZI` → `GOLDEN_REASONS` |
| arhitektura | architecture | `test_arhitektura` → `test_architecture` |
| granice | boundaries | `test_granice` → `test_boundaries` |
| tehnika (u id-u slučaja) | technique | keep the prefixes `gv-`, `ke-`, `tab-`, `st-`, `pg-` until Wave C renames them together with the docs |
| granična vrednost | boundary value | `gv-` |
| klasa ekvivalencije | equivalence class | `ke-` |
| tabela odlučivanja | decision table | `tab-` |
| prelaz stanja | state transition | `st-` |
| pogađanje grešaka | error guessing | `pg-` |
| Chromium se pokreće | Chromium starts | `chromium_se_pokrece` → `chromium_starts`; `pyproject.toml` mentions it in a comment |
| srpski tekst | Serbian text | `SRPSKI_TEKST` → `SERBIAN_TEXT` |
