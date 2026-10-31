# ADR-023: Profiles, with Serbian content detection in the `rs` profile

```
Status:  Accepted
Date:    2026-10-31
Author:  Milos Lazic
```

Builds on [ADR-012](ADR-012-english-public-interface.md), whose wave C moves the Serbia-specific
parts into a profile, and on [ADR-015](ADR-015-not-applicable-and-partial-causes.md) (the
`not_applicable` state).

## Context

`i18n.lang.mismatch` is the only part of SiteTriage that is specific to one country. Its content
detector knows a single language, Serbian: it counts the share of Cyrillic letters and the share of
č/ć/š/ž/đ among Latin letters. When the content is "reliably Serbian" and the page declares a `lang`
outside a list of languages that the detector cannot tell apart from Serbian, the check reports a
finding.

That worked for the tool's first operator, who scans Serbian sites. SiteTriage is now open source
under the MIT license, and most of its users will scan sites in other countries. For them the check
does nothing useful, and sometimes it reports a false finding. Croatian, Bosnian, Slovenian, Czech,
Slovak and other languages use the same diacritics, and the detector cannot tell them apart from
Serbian. The check stays quiet only when the declared `lang` is on a hand-written list. A Croatian
site that declares `lang="en"` on Croatian content gets a client sentence saying its content is
Serbian.

`i18n.lang.missing` and `i18n.lang.invalid` do not depend on the content language and work for
every site.

## Decision

1. A profile is a TOML file shipped inside the package, as
   `sitetriage/profiles/<name>.toml` (package data, like `sitetriage/sitetriage.toml`). The merge
   order is: package defaults, then the profile, then the user's `--config` file. The merged result
   is validated as strictly as before. A profile cannot choose another profile.
2. A profile is chosen with `--profile NAME` on `scan`, `recheck` and `record`, or a top-level
   `profile = "NAME"` in the user's `--config` file. The flag wins over the key, and `--profile ""`
   turns off a profile the key would choose. The defaults have `profile = ""`, which means no
   profile. An unknown name fails with an error that lists the available profiles. Only names from
   that list are accepted, so a name cannot point at a file outside `sitetriage/profiles/`.
3. A new key, `thresholds.i18n.content_languages`, lists the content
   languages `i18n.lang.mismatch` detects. It is `[]` in the defaults. Every entry must have a
   detector in `sitetriage/checks/i18n.py`; the only one is `sr`. The known codes are
   `CONTENT_LANGUAGES` in `sitetriage/models.py`, so the config can validate them without importing
   the checks.
4. The `rs` profile sets `content_languages = ["sr"]` and nothing else. `cyrillic_ratio` and
   `diacritic_ratio` stay in the defaults, with a comment that only the `sr` detector reads them.
   That keeps validation simple: every threshold a check reads always exists, whatever the profile,
   and the README table of thresholds still points at one file.
5. Without a content language, `i18n.lang.mismatch` is `not_applicable` with the reason
   `no_content_language`. It returns this before it looks at the page, so a short or truncated home
   page does not make it `unknown`. The reason has a sentence in both catalogs, and both say the same
   thing: content language detection is off, and a profile such as `rs` turns it on.
   `not_applicable` does not make a domain `partial`. Like a check with an unmet requirement, a check
   the config switched off did not run, so it is also left out of `unknown_share`.
6. The report records the profile. `report.json` gets `profile` (`"rs"` or `null`) right after
   `config_digest`, added to `report-3.json` directly because 3.0 is not released yet. The HTML
   report shows the profile next to the run time and version, and the summary line on stderr names
   it. `config_digest` covers what the profile changes (`content_languages`), not the profile's
   name, so a user config that sets the same values gets the same digest.

## Consequences

- By default, users lose `i18n.lang.mismatch`, and nobody gets a false Serbian finding. The check
  stays in the registry, in `sitetriage explain` and in the README table, whose threshold text says
  it needs a content-language profile.
- The owner, who scans Serbian sites, runs with `--profile rs` (or `profile = "rs"` in their own
  config) and gets exactly the old behaviour. The fixtures in `tests/fixtures/` are Serbian sites, so
  the reference set, the golden files and the boundary tests of the check run with the `rs` profile
  and their values are unchanged. The live tests take the profile from `SITETRIAGE_LIVE_PROFILE`,
  and `scripts/metrics.py` takes `--profile`.
- Escalation to level 2 does not run the detector. It sees a mismatch finding only when a profile
  turned the check on, so without a profile that finding cannot send a domain to level 2.
- Without a profile, a domain whose home page has too little text is no longer `partial` because of
  this check: there was no language to detect, so there was nothing the check did not know.
- Another language means a new profile and a new detector. The detector goes into `DETECTORS` in
  `sitetriage/checks/i18n.py` together with the `lang` codes it cannot tell apart from its language,
  and its code into `CONTENT_LANGUAGES`. The client sentence of `i18n.lang.mismatch` names Serbian,
  so a second language also needs its own sentence (a variant) in both catalogs.
- A profile may set any key of the defaults. Today `rs` sets one key. Other country-specific values,
  for example industry multipliers calibrated on a national list, can move into profiles later
  without another change to the loader.
