# ADR-022: Client sentences claim only what the evidence proves

```
Status:  Accepted
Date:    2026-09-26 (Z-27), 2026-10-05 (owner review of the catalog)
Author:  Milos Lazic
Covers:  Z-27 (with O-3, BUG-013, BUG-014, BUG-015, BUG-018, BUG-023 to BUG-026)
```

Recorded on 2026-10-31 from `docs/izvestaj-testiranja-100.md` (O-3), `docs/izvestaj-testiranja-2.md`
§3.3, `docs/izvestaj-testiranja-3.md` §3.3 and §8, `CHANGELOG.md` (2.0.0) and the commit history.
Builds on [ADR-009](ADR-009-katalog-poruka.md) (sentences come from a per-language catalog).

## Context

Every finding comes with a sentence written for the site owner, and the operator may paste it into a
message as is. A sentence that overstates is a false finding, even if the measurement is right.

- O-3 (IT-SKENER-001): `i18n.lang.mismatch` was correct in 28 of 28 cases, but its sentence said
  search engines therefore show the site to the wrong market. Google determines page language from
  the visible content and does not use `lang`; the defensible consequence is the screen reader.
- IT-SKENER-002 §3.3 reviewed all 28 sentences by three rules: a claim must be verifiable, every
  number must come from the evidence, and number and noun must agree. This found BUG-013 (a
  compression saving of "a second and a half" that was really tenths of a second), BUG-014 (number
  and noun disagreeing) and BUG-015 (a decimal point in a Serbian sentence), and toned down several
  claims ("most visitors do not wait that long", images downloaded "on every load" although browsers
  cache them, console errors "mostly on older phones").
- Even after that review, `infra.tls.invalid` said that most visitors turn back at the warning, and
  `infra.robots.missing` said that every search engine asks for that file first. Neither had a
  source.

## Decision

### Z-27 (2026-09-26)

A test forbids, in the sentences of both languages, words that claim frequency
or human behaviour: at the time of IT-SKENER-003, 8 Serbian words (for example `većina`, `uvek`,
`svaki`) and 7 English ones (`most`, `always`, `every` …), for every check. An exception is allowed
only through a list in the test that names a source. The list may grow. The two sentences above were
rewritten to what is checked: the browser shows a warning before entering the site, and Google reads
`robots.txt` before crawling. English sentences that used such a word only as an idiom ("most of
all", "at all") were rephrased.

### Catalog review rules (owner review, 2026-10-05)

All 131 catalog items per language (client
sentences, reasons for "not known", report labels and the suggested text) are judged by four rules:

1. the claim can be verified;
2. every number comes from the evidence;
3. no claim about human behaviour without a source;
4. the English sentence never claims more than the Serbian one.

Outcome: 111 items OK, 15 corrected (for example, `h1`, `alt` and `lang` are measured only on the
home page, so the sentence says "the home page"), and 5 owner questions. Sentences about visitor
behaviour without a source ("many visitors do not wait that long" in 4 sentences, and a claim about
link sharing in messaging groups for `og:image`) were removed, and "many" and "often" joined the
words that require a source. `test_ispravljena_netacna_tvrdnja_se_ne_vraca` keeps every corrected
claim from coming back, across sentences, reasons and report texts.

### The question that finds defects

For each sentence the review asks: does this sentence hold in
every case in which the check fails? Four checks failed in cases where their correct sentence does
not hold, and were fixed as defects in the checks, not in the catalog: BUG-023 (SVG and `data:`
placeholders counted as oversized images, "about 0 kB" of waste), BUG-024 (incomplete certificate
chain reported as a visitor warning), BUG-025 (other languages written in the same script reported
as Serbian) and BUG-026 (a dead first sitemap next to a working one reported as "no sitemap").

## Consequences

- Adding a check means adding its sentence to both catalogs, and the sentence must pass these tests
  in both languages ([ADR-009](ADR-009-katalog-poruka.md)).
- The real-site run still found two sentence defects the tests did not catch: BUG-017 (the address
  count did not match the list) and BUG-018 (all console errors called "JavaScript errors", although
  the console also logs blocked mixed content and missing resources). Tests protect against known
  wording; review and real sites find the rest.
- Lesson recorded in IT-SKENER-003 §8: reviewing sentences is also reviewing checks. The question
  above found four classes of false findings that neither tests nor the manual check of the top 10
  had seen.
- Machine output is not affected: technical sentences, evidence, CSV and JSON keep machine notation
  (decimal point, full precision). Only text for people goes through the language formatter (Z-28).
