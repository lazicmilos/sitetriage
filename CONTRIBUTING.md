# Contributing to SiteTriage

Thanks for your interest in SiteTriage. It scans a list of domains and ranks the sites that deserve a
full manual audit. The Python package and the command are both called `sitetriage`. If you have not
used the tool yet, start with the [README](README.md).

> **Language.** The project started in Serbian. Since 3.0 the public interface is English
> ([ADR-012](docs/adr/ADR-012-english-public-interface.md)), and code identifiers, comments and test
> names are being translated, so you will still meet some Serbian in the code. Write new code,
> comments, docs, commit messages, issues and PRs in English. You are welcome to translate a Serbian
> comment you happen to touch, but put translation-only changes in their own commit, so a reviewer
> can tell a translation from a change in behaviour. The Serbian message catalog
> (`sitetriage/messages/sr.py`) is a product feature and stays Serbian.

## Development setup

### Docker (recommended)

The image is the official Playwright image, with exactly the Chromium revision that the pinned
`playwright` in `pyproject.toml` expects. Level 2 measurements and the browser tests then behave the
same on every machine. CI runs the same image.

```bash
git clone https://github.com/lazicmilos/sitetriage.git
cd sitetriage
mkdir rad
docker compose build
docker compose run --rm sitetriage pytest -q
```

The source is copied into the image, not mounted, so run `docker compose build` again after you
change code. Dependencies sit in their own layer, so a rebuild after a code-only change is quick.
`rad/` is mounted as `/rad` for input and output. On Linux, set `SITETRIAGE_UID=$(id -u)` and
`SITETRIAGE_GID=$(id -g)` so files written to `rad/` belong to you.

### Without Docker

You need Python 3.11 or newer (CI tests 3.11, 3.12 and 3.13).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium            # on Linux add --with-deps for the system libraries
```

`playwright` is pinned in the `dev` extra because each Playwright release expects one specific
Chromium revision. If you upgrade Playwright without running `playwright install chromium`, Chromium
fails at launch. The browser tests are then skipped, not failed (see [Running tests](#running-tests)).

To use a Chromium or Chrome that is already on the machine instead of Playwright's download, point
`SITETRIAGE_CHROMIUM` at the executable, or set `[browser] executable_path` in your own config file:

```bash
export SITETRIAGE_CHROMIUM=/usr/bin/chromium
```

A system browser can differ from the revision Playwright was built against. CI and the Docker image
use Playwright's own Chromium, so treat that one as the reference.

### Configuration

The defaults ship with the tool; your own TOML passed with `--config` overrides only what it sets.
The defaults, with a comment on every value, are in `sitetriage.toml`. Keep trial thresholds in a
small file of your own instead of editing the defaults.

### Operator identity

The tool refuses to send a single request without the operator's name and contact, because every
site administrator sees them in the User-Agent. The offline tests set a placeholder identity in
`tests/conftest.py`. To scan real sites, including `pytest -m live`, set your own, either in
`[operator] name` and `contact` of your config file or in the environment:

```bash
export SITETRIAGE_OPERATOR_NAME="Your name or studio" SITETRIAGE_OPERATOR_CONTACT="you@example.com"
```

## Running tests

```bash
pytest -q                                   # offline layer, the default
pytest -q --cov=sitetriage --cov-branch --cov-report=term --cov-fail-under=95   # what CI runs
SITETRIAGE_LIVE_CSV=my-domains.csv pytest -m live -v   # real sites from your own list; needs a network
pytest -m browser -rs                       # only level 2 tests, and why any were skipped
```

- **Offline layer** (the default, `-m 'not live'` in `pyproject.toml`). No network. Checks run on
  snapshots, and the integration tests run against a local HTTP server (`tests/localserver.py`)
  that serves broken sites on purpose: slow bodies, endless streams, bot protection, sitemaps in
  nine parts. It must pass on every PR.
- **`browser` marker.** These tests need a working Chromium. `tests/conftest.py` tries to launch
  Chromium once per session and, when Playwright is missing or Chromium does not start, skips every
  `browser` test and says why. A local skip means level 2 was not tested, so run these tests before
  you open a PR that touches `sitetriage/fetch/browser.py`, `pipeline.py` or the level 2 checks. CI
  installs Chromium and runs them.
- **`live` marker.** These tests go to real sites and are off by default, because an expired
  certificate on someone's site is not a defect in the tool. The repository names no real site: you
  give the list through `SITETRIAGE_LIVE_CSV`, a CSV in the format of `domains.example.csv`, and
  without it the tests are skipped. `tests/test_live.py` describes the optional column of expected
  findings. Run them by hand when you change fetching or calibration.
- **Coverage gate.** CI fails if line and branch coverage drops below 95 %.
- **Mutation testing** measures whether the tests notice changes in behaviour. mutmut only works on
  Linux and takes about 20 minutes, so it runs through Docker:

  ```bash
  docker compose run --rm sitetriage python scripts/mutacije.py
  ```

  Which modules are mutated is set in `[tool.mutmut]` in `pyproject.toml`. mutmut 3.2.3 does not
  mutate functions with decorators, so it does not cover check bodies (`@check`). Run it when you
  change scoring, address classification, parsing or other pure logic, and say in the PR if a new
  mutant survives.

### Test design conventions

- The baseline is a clean site on which no check may find anything. Each positive test breaks
  exactly one thing and asserts that no other check fired.
- Thresholds get boundary value tests (limit − 1, limit, limit + 1), and rules with several
  conditions get decision tables.
- The test case id starts with the technique it uses. The prefixes come from the Serbian names of
  the techniques:

  | Prefix | Technique | Serbian name |
  |---|---|---|
  | `gv-` | boundary value | granična vrednost |
  | `ke-` | equivalence class | klasa ekvivalencije |
  | `tab-` | decision table (one column per case) | tabela odlučivanja |
  | `st-` | state transition | prelaz stanja |
  | `pg-` | error guessing | pogađanje grešaka |

  See `tests/test_granice.py` for examples.
- Fixtures in `tests/fixtures/` are hand-written, not recorded from real sites, and use made-up
  `.example` domains.

## Lint and pre-commit

```bash
ruff check sitetriage/ tests/ scripts/
```

The rules and the line length (110) are in `[tool.ruff]` in `pyproject.toml`. The code base is not
formatted with `ruff format`, so do not reformat files you are not otherwise changing.

The repository has a [pre-commit](https://pre-commit.com/) configuration with `ruff check --fix` and
a few basic file hygiene hooks:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files                  # optional, once
```

## Architecture rules

These rules are what make the tool testable without a network and its reports defensible. A PR that
breaks one of them will not be merged, however useful the feature.

1. **Checks never touch the network.** Code that fetches and code that draws conclusions are
   separate layers. A check receives a snapshot that was already collected and returns results.
   `sitetriage/checks/` does not import `httpx`, `playwright`, `sitetriage.fetch` (except
   `sitetriage.fetch.urls`), `sitetriage.pipeline`, `sitetriage.messages` or `sitetriage.report`. If a
   check needs something from the network, the snapshot is missing a field: add the field to the
   snapshot instead.
2. **The order of phases lives only in `sitetriage.pipeline`**
   ([ADR-008](docs/adr/ADR-008-pipeline.md)). `cli` does not import `fetch.http`, `fetch.browser` or
   `score`. `tests/test_arhitektura.py` enforces both rules.
3. **Thresholds live in `sitetriage.toml`, not in code.** Read them through the check context
   (`ctx.th("thresholds.perf.html_size_kb")`). A threshold change comes with its reasoning: in the
   commit message, in an ADR when it is a decision users will notice, and, for user-visible
   thresholds, in the README table of thresholds.
4. **Every check returns one of four states**: `ok`, `finding`, `unknown` or `not_applicable`. Use
   the helpers in `sitetriage/checks/registry.py`. `unknown` and `not_applicable` require a reason
   code. A check that could not verify something says `unknown`. It never reports `ok` for something
   it did not see, and never crashes on an older snapshot that lacks a field.
5. **Findings carry evidence, not sentences.** Evidence is data: numbers, URLs and technical codes.
   The catalogs in `sitetriage/messages/` build the sentence from it at display time
   ([ADR-009](docs/adr/ADR-009-katalog-poruka.md)).
6. **Client-facing sentences claim only what was measured**
   ([ADR-022](docs/adr/ADR-022-client-sentence-claims.md)). Every number in a sentence comes from the
   evidence, and numbers agree with nouns in both languages. A sentence must exist in **both**
   `sitetriage/messages/sr.py` and `sitetriage/messages/en.py`, and the English one claims exactly
   what the Serbian one claims, no more and no less. `tests/test_poruke.py` enforces this.
7. **Politeness and safety guarantees are not negotiable.** One request at a time per site, a pause
   between requests (longer if `Crawl-delay` asks for it), `robots.txt` `Disallow` respected, a hard
   budget per domain, giving up on `429`/`503`, an operator identity in every request, and no
   private or special addresses ([ADR-006](docs/adr/ADR-006-ssrf.md)). There is no global switch
   that turns these off, and a PR must not add one.
8. **No real lead lists or scan results in the repository.** Domain lists, per-domain results and
   snapshots of real sites stay out of git, issues and PRs.

## Adding a new check

1. **Register it.** Add a function with the `@check(...)` decorator in the module for its category
   under `sitetriage/checks/` (`seo.py`, `perf.py`, ...). Give it a `check_id` of the form
   `category.subject.problem`, its level, base severity, the snapshot parts it `requires`, a short
   description and the threshold in words. The registry feeds the engine, the README table and
   `sitetriage explain` from one place.
2. **Put the threshold in `sitetriage.toml`** under `[thresholds.<category>]` and read it with
   `ctx.th`.
3. **Return every state deliberately**: `finding(...)` with evidence, `ok(...)`, and `unknown(...)`
   or `not_applicable(...)` with a reason code whenever the input does not allow a verdict.
4. **Write the messages** in both `sitetriage/messages/sr.py` and `sitetriage/messages/en.py`: a
   `FINDINGS` entry with the client and the technical sentence, and a `REASONS` entry for every new
   reason code. The catalog and the registry must have the same keys.
5. **Test it.**
   - Add the check to `POZITIVNI` (the positive cases) in `tests/test_checks_level1.py` or
     `tests/test_checks_level2.py`: one broken thing, and only this check fires. The clean-site
     tests fail until you do.
   - Add boundary value tests (`gv-`) for every threshold, and a decision table (`tab-`) if the rule
     has several conditions, in `tests/test_granice.py`.
   - Add message cases to `tests/poruke_slucajevi.py`, including the plural forms.
   - Add an `unknown` or `not_applicable` case for each reason the check can give.
6. **Update the README table.** Run `sitetriage explain --all --markdown` and paste the result over
   the table of checks in `README.md`. CI fails if a registered `check_id` is missing from the
   README.
7. **Calibrate.** Run `sitetriage recheck <snapshots> --config <trial.toml> --out <dir>` on saved
   snapshots to see what the new check would report, without fetching the sites again.
8. **Update `CHANGELOG.md`** (see [Pull requests](#pull-requests)). A new check changes
   `config_digest` and adds findings that users will see.

## Changing `report.json`

`report.json` is a contract for programs (the web app, `sitetriage diff`, CRMs). Its shape is
described by `sitetriage/schema/report-3.json`, which ships with the package. The rules are in
[ADR-011](docs/adr/ADR-011-json-sema.md) and [ADR-012](docs/adr/ADR-012-english-public-interface.md):

- The schema rejects unknown fields, so a new field goes into the schema in the **same commit** as
  the model change. The tests validate the output against the schema.
- An added field raises the minor version (`3.0` → `3.1`), because an older reader can skip it.
- A removed field, a changed type or meaning, or a renamed `check_id` raises the major version
  (`3.x` → `4.0`), and is listed under breaking changes in `CHANGELOG.md`.
- Snapshots are internal and may change, as long as `sitetriage recheck` still reads old ones. A
  check that misses a field introduced later returns `unknown` with a reason, never `ok` and never a
  crash.

## Design decisions

Decisions that shaped the tool are recorded as architecture decision records in
[docs/adr/](docs/adr/README.md). Read the relevant one before you change the behaviour it describes,
and write a new one when your change makes a decision of the same weight: a new threshold policy, a
new kind of measurement, a change to the report contract. The index explains the format. Older code
comments and the Serbian documents in [docs/sr/](docs/sr/README.md) cite section numbers,
requirement ids and observation ids from specifications that were never published;
[legacy-references.md](docs/adr/legacy-references.md) decodes them. Do not add new references of
that kind: link to an ADR or explain the point in place.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) in English:

```
fix(BUG-030): count a repeated oversized image once
feat: compare two runs with sitetriage diff
docs: explain level 2 limits in ADR-006
```

- Common types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `ci`, `chore`.
- The scope is optional. Use it for a bug id (`BUG-030`) or the area you change (`report`,
  `fetch`).
- Mark breaking changes with `!` (`feat(report)!: ...`). A breaking change is anything that changes
  a domain status, a `check_id`, the shape of a finding or `report.json`. Record it in
  `CHANGELOG.md` under breaking changes **in the same commit**.
- Keep commits focused. Formatting, translation and behaviour changes go in separate commits.

## Pull requests

- Open an issue first for a new check, a new dependency or a change to the report format, so the
  direction is agreed before you write code.
- One logical change per PR. Fill in the PR template.
- CI must be green: lint, tests on every supported Python version, the coverage gate, the README
  table check and the Docker build.
- Add tests that fail without your change. For a bug fix, the test reproduces the bug.
- User-visible changes get an entry in the "Unreleased" section of `CHANGELOG.md`.
- If a client-facing sentence changes, change it in both languages and regenerate the golden files
  in `tests/golden/` in the same commit, so the difference is visible in `git diff`.
- Describe how you verified the change: which tests and, for fetching or level 2 changes, whether you
  ran `-m browser`, `-m live` or a `recheck`. Before a release that changes fetching or thresholds,
  run the [real-site verification](docs/real-site-verification.md).
- Do not post private domains, lead lists or unredacted snapshots in a PR or issue.

## Reporting problems

- Bugs, wrong findings and missed problems: use the issue templates. For a wrong finding, attach the
  relevant part of `report.json` or a snapshot, with the domain anonymized.
- Security vulnerabilities: do **not** open a public issue. See [SECURITY.md](SECURITY.md).

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
