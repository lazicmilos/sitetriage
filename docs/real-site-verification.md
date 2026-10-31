# Real-site verification

The offline tests never touch a real site. Fixtures are hand-written, and the local test server
answers in microseconds. This procedure was written as the gate for v2: at that point all 327
offline tests passed, and four bugs fixed just before the first real-site check (budget, time
measurement, soft-404 probes, TLS evidence; called B1–B4) had been invisible for exactly that
reason. The procedure exists to find the fifth. Run it again before a release that changes
fetching, level 2 or thresholds.

Run it locally, on a machine with a real network connection. The result is not "pass/fail" but
calibration decisions, each recorded in an [ADR](adr/README.md). The log of the v1 and v2 runs is
[docs/sr/kalibracija.md](sr/kalibracija.md), in Serbian.

## 0. Preparation (10 min; the first build pulls about 2 GB)

Everything goes through Docker: the same image, the same Chromium and Python versions as CI. If your
result differs from someone else's, the difference is in the network and the sites, not in the
environment.

```bash
git pull
mkdir -p rad                                    # input and output; the code stays in the image
export SITETRIAGE_OPERATOR_NAME="Operator name" SITETRIAGE_OPERATOR_CONTACT="contact@studio.example"  # who is scanning; no requests without it
export SITETRIAGE_UID=$(id -u) SITETRIAGE_GID=$(id -g)  # Linux: so the reports belong to you
docker compose build
docker compose run --rm sitetriage pytest -q        # every test must pass before anything else
```

In PowerShell, set the identity with `$env:SITETRIAGE_OPERATOR_NAME = "Operator name"` and
`$env:SITETRIAGE_OPERATOR_CONTACT = "contact@studio.example"`. On Windows you do not need
`SITETRIAGE_UID`.

If any test is skipped because Chromium does not start, the image is broken. Stop there.

## 1. Test set: specification against reality (10 min)

```bash
docker compose run --rm -e SITETRIAGE_LIVE_CSV=/rad/live.csv sitetriage pytest -m live -v 2>&1 | tee rad/live.txt
docker compose run --rm sitetriage sitetriage record /rad/live.csv --out /rad/recordings
docker compose run --rm sitetriage python scripts/metrics.py /rad/recordings | tee rad/metrics-testset.txt
```

`record` deliberately does not write over `tests/fixtures/`: look at the difference first, and only
then change the fixtures.

Every failure in `live.txt` is one of three things. Say which one:

| Cause | Example | What to do |
|---|---|---|
| the site changed | institucija.example fixed its canonical | a note in your results; the fixture is refreshed |
| the threshold is wrong | `lang.mismatch` does not fire on an obviously Serbian site | a change in `sitetriage.toml`, checked with `recheck` |
| a bug | the check says `ok`, but you can see the problem by hand | a failing test plus the fix, as with B1–B4 |

## 2. A real run: 30–50 domains from your lead list (20 min)

Put the list in `rad/leads.csv` (header `domain,industry,note`).

```bash
time docker compose run --rm sitetriage sitetriage scan /rad/leads.csv --out /rad/report 2>&1 | tee rad/run.log
docker compose run --rm sitetriage python scripts/metrics.py /rad/report/snapshots | tee rad/metrics.txt
```

When a domain looks odd:

```bash
docker compose run --rm sitetriage sitetriage scan /rad/leads.csv --only odd-site.example --debug-domain odd-site.example --out /rad/debug
```

## 3. Criteria

| Metric | Limit | Why this one |
|---|---|---|
| process crashes | **0** | as many rows come out as domains go in |
| `partial` among working domains | **< 10 %** | above that, the budget or a threshold does not match reality |
| `unknown` for any one check | **< 20 %** of live domains | a check that usually does not know is not worth having |
| time for 50 domains | **< 4 min** | linear towards the target of 200 domains in at most 15 min |
| klinika.example | **≤ 2 findings** | the deliberately clean control site of the test set |
| top 5 in the ranking | **confirmed by hand** | if #1 is not a better lead than #10, the ranking is not doing its job |

To confirm by hand, open the site, compare it with `message_client` from `findings.csv`, and mark
each finding as correct, false positive, or correct but irrelevant. Do the same for the bottom 5, to
check that no bad sites were missed. For the full acceptance check on a validation list, use the
[manual check form](manual-check-form.md) ([ADR-021](adr/ADR-021-manual-verification.md)).

## 4. What to send back

1. `rad/live.txt`
2. `rad/metrics-testset.txt` and `rad/metrics.txt`
3. `rad/report/summary.csv` and `rad/report/findings.csv`
4. your manual verdicts for the top 5 and the bottom 5
5. anything that caught your eye, even if you cannot explain why

Do not send snapshots. They contain the raw HTML of other people's sites, and everything needed from
them comes out of `metrics.py`.

## 5. Afterwards

Record every decision in the form **threshold, observation, decision**, in an ADR. Try
thresholds in `rad/calibration.toml`, which holds only what you change: the defaults ship with the
tool, and your own TOML passed with `--config` overrides only what it sets. That way there is no
image rebuild between two attempts and no second download of the sites:

```bash
docker compose run --rm sitetriage sitetriage recheck /rad/report/snapshots --config /rad/calibration.toml --out /rad/new
```

Once a threshold is decided, it moves into `sitetriage.toml` and is committed, with its reasoning.

Only when every criterion in section 3 is green: a new recording in `tests/fixtures/`, `git diff`,
and the release.
