# ADR-021: Acceptance is a manual, out-of-tool check of the top 10 and the bottom 5

```
Status:  Accepted
Date:    2026-09-30 (form), 2026-10-04 to 2026-10-06 (three rounds)
Author:  Milos Lazic
Covers:  Z-52 (with O-17, O-21)
```

Recorded on 2026-10-31 from `docs/manual-check-form.md`, `docs/sr/plan-testiranja.md` (§3, §4),
`docs/sr/izvestaj-testiranja-3.md` §3.6 and §4, `docs/sr/kalibracija.md` (2026-10-04 to 2026-10-06),
`docs/real-site-verification.md` §3 and the commit history.

## Context

Automated tests run against hand-written fixtures and a local server. They cannot tell whether a
finding is true on a real site, or whether the ranking puts the right sites at the top. The v1
checklist already required "first 5 in the ranking manually confirmed"; v2 makes this the acceptance
test, done by the product owner over the report of the run on list B (the validation list, see
[ADR-020](ADR-020-threshold-calibration.md)).

## Decision

The protocol is the form in `docs/manual-check-form.md`:

- The check is done as soon as possible after the run, at the latest within 3 days. Sites change, and a
  finding is judged against the state of the site at scan time. If the site changed in between, the
  finding counts as neither correct nor incorrect, with a note.
- Everything is checked outside the tool: `curl` (always with `--max-time 20`), a browser on a phone and on a
  computer, DNS queries. The client sentence comes from `findings.csv` (`message_client`), the
  measured numbers from `evidence_json`. The run is identified by `scanner_version` and
  `config_digest` from `report.json`.
- **Correct finding:** its client sentence holds on the site; every number in it matches what the reviewer
  sees or measures, and the problem exists. **Incorrect finding:** the sentence does not hold, even
  partly (wrong number, wrong page, no problem). Every incorrect finding is a defect and goes through
  the bug procedure.
- In the top 10, every finding is marked correct or incorrect with how it was checked, and for each
  site the reviewer answers "would I send this site a message: yes / no / maybe" and why.
- In the bottom 5, the reviewer opens each site and looks for an obvious serious problem the tool did not report (does
  not open on a phone, very slow, no https, pages return errors, empty or broken content), and names
  the check that should have found it, or "—" if none exists. Every miss is a false-negative defect
  (like BUG-005), gets a root-cause analysis, and after the fix the criteria are measured again on B.
- Pass criteria: 0 incorrect findings in the top 10; at least 7 of 10 "would send"; 0 missed serious
  problems in the bottom 5.
- A filled-in form contains domains, so it stays in `rad/` and never enters the
  repository; the test report carries only totals.

## Consequences

Three rounds were run on list B:

| | Round 1 (2026-10-04) | Round 2 (2026-10-05) | Round 3 (2026-10-06) |
|---|---|---|---|
| report | run of 10-03 | level 1 of 10-03, level 2 of 10-05 | run of 10-06 |
| findings in top 10 | 98 | 89 | 96 |
| correct / incorrect | 96 / 2 | 89 / 0 | 96 / 0 |
| "would send": yes / maybe / no | not filled in | 7 / 2 / 1 | 7 / 2 / 1 |
| missed serious problem in bottom 5 | 2 | 0 | 0 |

- Round 1 found BUG-019 (2 incorrect findings on one site: the level-2 User-Agent made ad networks
  and a font service send heavier content) and BUG-020 (2 misses: heavy pages that never went to the
  browser). Round 2 led to BUG-022. These were level-2 and coverage defects, not threshold problems;
  the Z-50 thresholds were not changed.
- Raw HTML and headers were checked with `urllib`, and weight, requests, time to `load`,
  `h1`, `alt` and oversized images with a script in a browser under the same network profile. That
  script is software too: it was tested before use (139 cases, 99 % branch coverage, 48 of 48 manual
  mutants killed) and 13 of its own defects were fixed first, one of them a blocker. A raw-HTML
  helper once confirmed "no description" findings on an empty page that had not loaded; it was fixed
  and the check repeated. Lesson recorded in IT-SKENER-003: a script that gives the verdict is tested
  before it is trusted.
- Proposed "would send" decisions were prepared by an AI assistant from phone screenshots and
  confirmed by the owner.
- The check also produced observations the tool does not cover: a near-empty home page (O-15) and a
  missing `<meta name="viewport">` (O-20) were reasons for "would send"; one "no" was an association,
  not a business, although all its findings were correct (O-17). Conclusion: choosing the domains is
  the job of the operator who builds the list, not of the tool.
- Unclear from the record: `docs/sr/kalibracija.md` (2026-10-06) and O-21 say that "the 80 % rule of
  Z-52" covers a site whose weight sat right at the 7 MB threshold and moved between modes. The rule
  itself is not written down anywhere in the repository; it is presumably part of the unpublished
  text of Z-52.
