# ADR-011: `report.json` is a contract with a schema and a version

```
Status:  Accepted (schema file and version superseded by ADR-012)
Date:    2026-09-30
Author:  Milos Lazic
```

Originally written in Serbian; translated for v3.

> **Update for v3.** [ADR-012](ADR-012-english-public-interface.md) renamed the evidence keys to
> English, which under the rules below is a major change. It replaced `report-2.json`
> (`schema_version` `2.0`) with `sitetriage/schema/report-3.json` (`schema_version` `3.0`), and
> `report-2.json` was removed. The rules in this record are unchanged; read every `2.x` below as the
> version that was current when it was written. Paths use the current package name `sitetriage/`
> (the record originally said `skener/`).

## Context

HTML and CSV are for people. The web application, `sitetriage diff`, CRMs and other integrations
read the output with a program, and they need a shape that does not change silently. In v1 there
was no such output, so every change to the model would have quietly broken whoever reads it.

## Decision

- `report.json` is the serialized `ScanResult`. Fields are named as in `models.py`. A finding has no
  sentence, only `check_id`, the evidence and `variant`, and the reader builds the sentence in its
  own language ([ADR-009](ADR-009-katalog-poruka.md)).
- The shape is described by the schema `sitetriage/schema/report-2.json`, which ships with the
  package (now `report-3.json`, see the update above). The schema does not allow unknown fields, so
  a new field has to go into the schema first, and a test validates the output
  (`test_json_izvestaj_prolazi_semu`).
- `schema_version` is the first field. An added field raises the minor version (`2.0` → `2.1`),
  because an older reader can skip it. A removed field, a changed type or meaning of a field, and a
  renamed `check_id` raise the major version (`2.x` → `3.0`).
- `config_digest` is the sha256 of the configuration that affects the result, without the operator
  identity, concurrency and the browser path. With it, `diff` knows whether a difference between two
  runs comes from the site or from the thresholds
  (`test_otisak_ne_zavisi_od_identiteta_i_paralelizma`,
  `test_otisak_se_menja_kad_se_promeni_prag`).
- Snapshots from v1 stay readable. A check that lacks a field introduced in v2 returns `unknown`
  with a reason, never `ok` and never a crash (`test_v1_snapshot_daje_unknown_a_ne_pad`).
- Until release `v2.0.0` the schema is `2.0` and changes without a version bump, because nobody
  outside reads it. That is how `environment.network_profile` ([ADR-010](ADR-010-mrezni-profil.md))
  and `environment.link_mbps` ([ADR-018](ADR-018-load-time-validity.md)) were added. The change
  rules apply from the release on.

## Consequences

- Every new field in the model needs a schema change in the same commit, or the test fails.
- A breaking change goes into the CHANGELOG, under breaking changes.
- `diff` (planned, not yet built) refuses to compare reports with different major schema versions.
- The schema describes the report, not the snapshot. The snapshot is the tool's internal format and
  may change, as long as `recheck` reads it.
