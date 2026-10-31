# ADR-015: `not_applicable` as a fourth result state, and `partial` split by cause

```
Status:  Accepted
Date:    2026-09-25 (criterion split in test plan v2.0), 2026-09-27 (Z-21 accepted)
Author:  Milos Lazic
Covers:  Z-21, Z-22 (with O-7, O-7a, O-7b)
```

Recorded on 2026-10-31 from `docs/izvestaj-testiranja-2.md` §6 and §8, `docs/plan-testiranja.md`
§4, `docs/kalibracija.md` (run D, 2026-09-27; 2026-10-05), `docs/izvestaj-testiranja-3.md` §6.1 and
`CHANGELOG.md` (2.0.0).

## Context

A domain is `partial` when it was scanned but not every check could give an answer. The v1 exit
criterion was "`partial` < 10 % of working domains". After the fix cycle `partial` was 14.4 %, and
it did not come from defects (IT-SKENER-002, O-7):

- the budget was exhausted on 4 domains (4.4 %);
- the rest were honest `unknown` results: on 5 sites the sample had fewer than 3 pages, so the
  duplicate checks had nothing to compare (4 sites show only 1–2 pages, one ran out of budget after
  the home page); on 3 sites images load only on scroll; on 3 the text is drawn by JavaScript, so
  raw HTML has too little of it for language detection; on 2 the soft-404 probes gave no usable
  answer; on 1 the certificate was not verified.

The 10 % criterion had been written before the decision to turn false findings into `unknown`, and
that decision raised it. The report's lesson: an exit criterion should be written after deciding how
the tool should behave, not before. O-7 proposed (a) "does not apply" instead of `unknown` for
duplicate checks on a site with fewer than 3 pages, and (b) splitting the criterion.

## Decision

### Z-21: a fourth state

A check result is `ok`, `finding`, `unknown` or `not_applicable`.
`not_applicable` means the check has nothing to check on this site. Its reason is mandatory, as for
`unknown` (`test_not_applicable_bez_razloga_je_bug`). The domain report lists them in
`not_applicable`, in the same shape as `unknowns`, but they do not make the domain `partial`.

- Duplicate checks are `not_applicable` only when the site really has fewer than 3 pages. When the
  sample is small because of the budget or because links are drawn by JavaScript, they stay
  `unknown` with a reason.
- To tell the two apart, the sample is topped up with internal links from the home page when the
  sitemap lists fewer addresses than the sample needs. The level-1 snapshot keeps up to 200 internal
  links of the home page, and level 2 adds links from the rendered DOM.

### Z-22: `partial` by cause

Each domain report has `partial_causes` (`budget`, `unknown`, or
both). The summary counts them separately, and the JSON and HTML reports show `budget_share` (budget
exhaustion among working domains) and `unknown_share` (per check). The single exit criterion becomes
two:

- `partial` because of the budget: < 10 % of working domains;
- `unknown` per check: < 20 %.

The denominator of `unknown_share` is the working domains on which the check actually ran: for a
level-2 check, those that went through level 2; for load time, those measured under the network
profile (test plan v2.2, 2026-10-05).

### Later extension (2026-10-05, BUG-020)

A check whose precondition is not met was not run, so it
does not belong in the `unknown` denominator. Load time on the "light" level 2 (see
[ADR-019](ADR-019-run-duration-and-level2-coverage.md)) is therefore `not_applicable` with the
reason `requires.level2_full`, not `unknown`.

## Consequences

- Run D (2026-09-27): of the 5 domains that had fewer than 3 pages in run C, one reached 7 pages
  through the link top-up and became `scanned`. Three really have 1–2 pages; their duplicate checks
  are `not_applicable`, but they stay `partial` because of short text or an unchecked host variant.
  The fifth ran out of budget and stays `partial`, as Z-21 requires. The owner declared Z-21 met by
  interpretation: `partial` caused by other checks is outside the scope of Z-21.
- On list B the split criteria were met: budget 9.0 % and `unknown` at most 5.0 % (2026-10-03), 9.1 %
  and 5.1 % (2026-10-06).
- When the light level 2 first reported load time as `unknown`, `partial` on list B jumped from 21
  to 54 domains, for 29 of them only because of that. With `not_applicable` it went back to 25,
  with ranking and `findings.csv` unchanged.
- The fourth state and the `not_applicable` list are breaking changes in `CHANGELOG.md` 2.0.0.
- Tests: `tests/test_malo_stranica.py` (Z-21), `tests/test_uzrok_partial.py` (Z-22).
