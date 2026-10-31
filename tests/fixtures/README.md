# Test-set fixtures

**These snapshots are written by hand, not recorded from real sites.**

They were made without network access by the generator [`../make_fixtures.py`](../make_fixtures.py),
and they describe the state that the original specification set for eight typical sites, together
with the `check_id`s each must produce. `klinika.example` is the control clean site. The domains are
made up, under the reserved TLD `.example` (RFC 2606); none of them belongs to a real site.

What that makes them, and what it does not:

- They **are** a check that the chain `snapshot → checks → scoring → ranking` gives the expected
  `check_id`s and the exact scores the specification gives for these sites.
- They are **not** a check that any real site is in that state. That is what `pytest -m live`
  against your own domain list is for (`SITETRIAGE_LIVE_CSV`, see [`../test_live.py`](../test_live.py)).

After changing the generator, make them again:

```bash
python tests/make_fixtures.py
```

The generator writes gzip without a time in its header, so `git diff` shows only real changes.
