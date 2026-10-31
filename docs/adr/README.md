# Architecture decision records

Each record describes one decision: the context, what was decided, and the consequences. ADR-006
to ADR-011 are written in Serbian; ADR-012 onward are in English. ADR-013 to ADR-022 were written
on 2026-10-31, after the fact. They reconstruct owner decisions that the code cites as `Z-nn`
requirements of the unpublished v2 specification, using the calibration log, the test reports and
the changelog.

| ADR | Title | Status | Date | Covers |
|---|---|---|---|---|
| [ADR-006](ADR-006-ssrf.md) | The scanner does not open private addresses (SSRF protection) | Accepted | 2026-09-25 | |
| [ADR-008](ADR-008-pipeline.md) | A scan is a core function, not a command-line one | Accepted | 2026-09-25 | BUG-007 |
| [ADR-009](ADR-009-katalog-poruka.md) | Sentences are built at display time, from a catalog | Accepted | 2026-09-25 | Z-12 (inferred) |
| [ADR-010](ADR-010-mrezni-profil.md) | Level 2 measures under a fixed network profile, without site isolation | Accepted | 2026-09-27 | Z-30 |
| [ADR-011](ADR-011-json-sema.md) | `report.json` is a contract with a schema and a version | Accepted | 2026-09-30 | Z-13 |
| ADR-012 | English public interface | In progress | | |
| [ADR-013](ADR-013-unreachable-after-second-attempt.md) | A site is "unreachable" only when that is certain, and only after a second attempt | Accepted | 2026-09-27 | Z-20, O-5, O-8, O-14 |
| [ADR-014](ADR-014-host-canonicalization.md) | Host canonicalization is two ordinary checks, paid for with a 19-request budget | Accepted | 2026-09-26 | Z-26, O-12, R-2 |
| [ADR-015](ADR-015-not-applicable-and-partial-causes.md) | `not_applicable` as a fourth result state, and `partial` split by cause | Accepted | 2026-09-27 | Z-21, Z-22, O-7 |
| [ADR-016](ADR-016-weight-until-load.md) | Page weight and request count are transferred bytes up to `load`, without video | Accepted | 2026-09-26 | Z-24, O-2, O-10, O-13, BUG-016 |
| [ADR-017](ADR-017-rendered-language-raw-seo-tags.md) | Language checks read the rendered page; title, description and canonical stay on raw HTML | Accepted | 2026-09-27 | Z-25, O-19 |
| [ADR-018](ADR-018-load-time-validity.md) | Load time is reported only when the link cannot distort it | Accepted | 2026-09-27 | Z-31, Z-33, BUG-006 |
| [ADR-019](ADR-019-run-duration-and-level2-coverage.md) | Run duration: who gets level 2, and concurrency chosen per machine | Accepted | 2026-10-05 | Z-32, BUG-005, BUG-020, O-18 |
| [ADR-020](ADR-020-threshold-calibration.md) | Thresholds come from percentiles of a calibration list, then are frozen and validated on a second list | Accepted | 2026-09-28 | Z-50, Z-51, Z-23 |
| [ADR-021](ADR-021-manual-verification.md) | Acceptance is a manual, out-of-tool check of the top 10 and the bottom 5 | Accepted | 2026-10-06 | Z-52 |
| [ADR-022](ADR-022-client-sentence-claims.md) | Client sentences claim only what the evidence proves | Accepted | 2026-09-26 | Z-27 |

ADR-001 to ADR-005 and ADR-007 were never published in this repository. Their numbers stay
unused.

## Legacy references

Code, tests and the Serbian documents cite specification sections (`§4.2`), v2 requirements
(`Z-26`), bugs (`BUG-020`), observations (`O-7`) and document or phase ids (`IT-SKENER-003`, `F4`).
None of these sources is public. [legacy-references.md](legacy-references.md) says what each id
means and where it is documented now.

## Writing a new ADR

Copy the header of an existing record (`Status`, `Date`, `Author`), take the next free number,
and write Context, Decision and Consequences. If the decision changes `report.json`, follow
[ADR-011](ADR-011-json-sema.md). Add a row to the table above.
