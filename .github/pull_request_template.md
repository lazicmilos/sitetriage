## Summary

<!-- What does this change and why? Link the issue it closes, e.g. "Closes #123". -->

## Type of change

- [ ] Bug fix
- [ ] New check or change to an existing check
- [ ] New feature or option
- [ ] Threshold or calibration change (`sitetriage.toml`)
- [ ] Refactor or performance, no change in behaviour
- [ ] Documentation, tests, CI or tooling
- [ ] Breaking change (domain status, `check_id`, finding shape or `report.json`)

## How it was verified

<!-- Tests added or run. For fetching or level 2 changes, say whether you ran `pytest -m browser`,
`pytest -m live` or `sitetriage recheck` on saved snapshots. Do not paste private domains. -->

## Checklist

- [ ] Tests cover the change and fail without it (boundary values `gv-` for new thresholds).
- [ ] `ruff check sitetriage/ tests/ scripts/` passes.
- [ ] `pytest -q --cov=sitetriage --cov-branch --cov-fail-under=95` passes locally (or in CI).
- [ ] `CHANGELOG.md` is updated for user-visible changes; breaking changes are listed under breaking
      changes in the same commit.
- [ ] If `report.json` changes: the schema in `sitetriage/schema/` and its version follow
      [ADR-011](https://github.com/lazicmilos/sitetriage/blob/main/docs/adr/ADR-011-json-sema.md), and an ADR is added or updated if a decision changed.
- [ ] If a client-facing sentence or reason changes: both `sitetriage/messages/sr.py` and
      `sitetriage/messages/en.py` are updated, claim the same thing, and the golden files are regenerated.
- [ ] If a check was added or its threshold text changed: the README table is regenerated with
      `sitetriage explain --all --markdown`.
- [ ] No real domain lists, scan results or unredacted snapshots are included.
