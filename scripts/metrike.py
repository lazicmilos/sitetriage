"""Metrike prolaza iz sačuvanih snapshota — bez ijednog mrežnog zahteva.

    python scripts/metrike.py izvestaj/snapshots/

Odgovara na pitanja iz `docs/provera-na-pravim-sajtovima.md`: koliko domena je
`partial`, zašto, i koja provera najčešće kaže `unknown`. Visok udeo `unknown`
je bag ili loš prag, ne „sajt je čist".
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from skener import store
from skener.config import load_config
from skener.score import analyze


def main(directory: str) -> int:
    config = load_config()
    pairs = list(store.read_all(Path(directory)))
    if not pairs:
        print(f"nema snapshota u {directory}")
        return 1

    reports = [analyze(site, config, browser=browser) for site, browser in pairs]
    n = len(reports)
    status = Counter(r.status for r in reports)
    budget = Counter(site.budget.aborted_reason for site, _ in pairs if site.budget.exhausted)
    # `unknown` na sajtu koji ne radi je očekivan; signal je `unknown` na sajtu koji radi.
    alive = [r for r in reports if r.status != "failed"]
    unknown = Counter(u.check_id for r in alive for u in r.unknowns)
    reasons = Counter((u.check_id, u.reason) for r in alive for u in r.unknowns)
    entry_errors = Counter(site.entry.error_kind for site, _ in pairs if site.entry and site.entry.error_kind)
    # Provera koja pali skoro svima ne razlikuje leadove — ili je prag loš, ili je nalaz šum.
    fired = Counter(check_id for r in alive for check_id in {f.check_id for f in r.findings})
    browser_failed = Counter(
        f"{e.kind}: {e.detail[:80]}" for _, b in pairs if b and b.status == "failed" for e in b.errors
    )
    requests = [site.budget.requests_made for site, _ in pairs]
    seconds = [site.budget.elapsed_ms / 1000 for site, _ in pairs]

    print(f"domena: {n}   nivo 2: {sum(b is not None for _, b in pairs)}")
    print("status:", ", ".join(f"{k} {v} ({v / n:.0%})" for k, v in status.most_common()))
    print(f"zahteva po domenu: prosek {sum(requests) / n:.1f}, max {max(requests)}")
    print(f"sekundi po domenu: prosek {sum(seconds) / n:.1f}, max {max(seconds):.1f}")
    if entry_errors:
        print("greške na početnoj:", dict(entry_errors.most_common()))
    if budget:
        print("\npotrošen budžet:")
        for reason, count in budget.most_common():
            print(f"  {count:4}  {reason}")
    if browser_failed:
        print("\nnivo 2 nije uspeo:")
        for reason, count in browser_failed.most_common():
            print(f"  {count:4}  {reason}")
    print(f"\nnalazi po proveri (udeo od {len(alive)} domena koji nisu `failed`):")
    for check_id, count in fired.most_common():
        print(f"  {count / max(len(alive), 1):5.0%}  {check_id}")
    print(f"\nunknown po proveri (udeo od {len(alive)} domena koji nisu `failed`):")
    for check_id, count in unknown.most_common():
        print(f"  {count / max(len(alive), 1):5.0%}  {check_id}")
    print("\nnajčešći razlozi:")
    for (check_id, reason), count in reasons.most_common(10):
        print(f"  {count:4}  {check_id}: {reason}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
