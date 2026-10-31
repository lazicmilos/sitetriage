# ADR-008: A scan is a core function, not a command-line one

```
Status:  Accepted
Date:    2026-09-25
Author:  Milos Lazic
```

Originally written in Serbian; translated for v3.

## Context

The order level 1 → escalation → selection → level 2 → scoring → ranking existed only in `cli.py`.
A web worker would have had to copy it, and two copies of the same order drift apart over time. On
top of that, each level started its own `asyncio.run`, and level 2 installed an exception handler on
the loop (BUG-007) without restoring it. In a long-lived process that changes global state for
good.

## Decision

The whole scan lives in the module `sitetriage.pipeline`:

```python
async def scan(targets, config, *, level="auto", snapshot_dir=None, on_event=None) -> ScanResult
def recheck(snapshot_dir, config, *, on_event=None) -> ScanResult
async def record(targets, config, *, out_dir, level="auto") -> int
```

- `scan` is a single async function and runs in a single loop. The caller starts it with
  `asyncio.run` (CLI) or inside its own loop (worker).
- The pipeline does not print, does not read arguments and does not exit the process. Errors are
  `ConfigError` and `InputError`, and the caller decides what to do with them.
- Progress goes through `on_event(Event)`: phase started, domain finished, phase finished, with a
  `done`/`total` counter. An error inside that function is logged and the scan carries on.
- A cancelled scan (`CancelledError`) propagates out. The browser and the HTTP client are closed in
  `finally`, and the snapshots of finished domains stay on disk.
- Level 2 installs its exception handler only while it runs, and then restores the previous one.
- `cli.py` does not import `fetch.http`, `fetch.browser` or `score`, which
  `tests/test_architecture.py` checks.

## Consequences

- The CLI and the worker share the same code, so the same input gives the same ranking. A parity
  test compares `pipeline.recheck` with the path `recheck` took before this decision.
- `ScanResult` is the basis of the JSON report, so the JSON describes what the pipeline actually
  returns.
- Snapshots are still written as soon as a domain is done. Cancelling does not erase work already
  done.
- Fetchers get an `on_done` callback per domain. That is the only change to their interface.
