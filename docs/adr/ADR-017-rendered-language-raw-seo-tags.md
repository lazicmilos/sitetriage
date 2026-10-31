# ADR-017: Language checks read the rendered page; title, description and canonical stay on raw HTML

```
Status:  Accepted
Date:    2026-09-27 (Z-25), 2026-10-06 (O-19)
Author:  Milos Lazic
Covers:  Z-25, O-19 (with O-7)
```

Recorded on 2026-10-31 from `docs/sr/kalibracija.md` (run D, 2026-09-27; 2026-10-06),
`docs/sr/izvestaj-testiranja-3.md` §6.1–§6.3, `CHANGELOG.md` (2.0.0) and the commit history.

## Context

Level 1 reads raw HTML. Level 2 renders the page in Chromium, so it sees what JavaScript changes.
Two groups of checks are affected differently.

### Language

In IT-SKENER-002 (O-7) three sites seemed to have their text drawn by JavaScript:
raw HTML had too little text for language detection, so `i18n.lang.mismatch` was `unknown`, and a
`lang` attribute set by JavaScript was reported as missing. The audience of the language checks is a
screen reader, and a screen reader reads the page after JavaScript.

### Title, description, canonical (O-19)

These checks read raw HTML too. Google executes
JavaScript, so on a site that sets them by script `seo.title.missing`, `seo.description.missing` and
`seo.canonical.missing` would be false. Nobody knew how many such sites exist.

## Decision

### Z-25

When level 2 ran, `i18n.lang.missing`, `i18n.lang.invalid` and `i18n.lang.mismatch` look
at the page after JavaScript, as a screen reader reads it. The evidence names the source
(`sirovi_html` for raw HTML, `nivo2` for level 2). The level-2 snapshot records `lang` and the
visible text after JavaScript (up to 4000 characters). When there is too little text, the result is
`unknown` with the reason `text_too_short` (raw HTML) or `text_too_short_rendered` (level 2). Short
raw text is also an escalation signal for level 2.

### O-19, first step (owner decision, 2026-10-05)

Level 2 only records `dom.title`,
`dom.meta_description` and `dom.canonical` (`""` means absent, `None` means not recorded). The checks
are not changed until the next run over list B shows how many sites set these tags only by script.

### O-19, second step (owner decision, 2026-10-06)

On list B none of 99 sites set them only by
JavaScript; all 13 `seo.description.missing` and all 23 `seo.canonical.missing` findings stand after
JavaScript as well. The `seo.*.missing` checks keep reading raw HTML. The `dom.*` fields stay in the
snapshot.

## Consequences

- Run D (2026-09-27): all three sites from O-7 went through level 2, but even after JavaScript they
  have 12, 242 and 56 characters of text against a threshold of 400: a page with a single button, an
  "under construction" page and a page with only a footer. The O-7 assumption that JavaScript draws
  the text was wrong; there is no text in a browser either. `mismatch` is `unknown`
  (`text_too_short_rendered`), while `missing` and `invalid` work on the rendered state. The owner
  ruled that `unknown` with a reason is the correct answer here, because `ok` or a finding would be
  a guess, and declared Z-25 met.
- The two groups differ on purpose, and the choice was measured: language checks use the rendered page
  because their reader is a screen reader; SEO tag checks use raw HTML because on the measured lists
  no site depended on JavaScript for them. If a future list shows otherwise, the `dom.*` fields are
  already there.
- Without level 2 the language checks fall back to raw HTML.
- A home page with almost no text is not a finding today (O-15); it is planned as a separate check
  after v2.
