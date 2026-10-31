# Manual check form

The manual check is the acceptance test of a release ([ADR-021](adr/ADR-021-manual-verification.md)).
The product owner does it over the report of a run on the validation list (list B, see
[ADR-020](adr/ADR-020-threshold-calibration.md)). It was introduced as the acceptance test of v2,
as defined in the [test plan](sr/plan-testiranja.md). This page is the empty form. A filled-in copy
contains domains, so it stays in `work/` and never enters the repository; the test report carries
only the totals.

## Before you start

- Copy this file to `work/manual-check-b.md` and fill in the copy.
- Check as soon as possible after the run, at the latest within 3 days. Sites change, and a finding
  is judged against the state of the site at scan time. If the site changed in the meantime, write
  that in the note and count the finding as neither correct nor incorrect.
- Check each finding outside the tool: `curl` (always with `--max-time 20`), a browser on a phone and
  on a computer, DNS (`Resolve-DnsName`). Read the client sentence from `findings.csv`
  (`message_client`) and the measured numbers from `evidence_json`.

A **correct finding** is one whose client sentence holds on the site: every number in it matches
what you see or measure, and the problem exists. An **incorrect finding** is one whose sentence does
not hold, even partly (wrong number, wrong page, no problem). Every incorrect finding is a defect and
goes through the bug procedure (section 5 of [IT-SKENER-002](sr/izvestaj-testiranja-2.md)).

Run details:

| | |
|---|---|
| date of the run | |
| tool version (`scanner_version` from `report.json`) | |
| configuration digest (`config_digest`) | |
| date of the check | |
| checked by | |

## 1. Top 10 in the ranking

One table per domain. The rows are the findings from `findings.csv` for that domain.

**Place 1**: domain: ______________________ industry: ______________

| `check_id` | Correct / incorrect | How it was checked | Note |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

Would I send this site a message: **yes / no / maybe**. Why:

(repeat for places 2–10)

## 2. Bottom 5 in the ranking

Open the site and look for an obvious serious problem the tool did not report: the site does not
open on a phone, loads very slowly, has no https, pages return errors, the content is empty or
broken. For each problem, also write down which check should have found it. If no check in
`sitetriage explain --all` covers it, write "—".

| Place | Domain | Serious problem the tool did not find | Check that should have found it | How it was checked |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |

Every miss is a false-negative defect (like BUG-005) and gets a root-cause analysis. After the fix,
the criteria are measured again on list B.

## 3. Totals

| Criterion (v2 exit criteria) | Limit | Result |
|---|---|---|
| incorrect findings in the top 10 | 0 | |
| "would send" (yes) in the top 10 | ≥ 7 of 10 | |
| missed serious problems in the bottom 5 | 0 | |

Open defects (BUG-xxx) and observations:
