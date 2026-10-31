"""Distribution of level-2 measurements from saved snapshots, for threshold calibration (ADR-020).

    python scripts/distribution.py out/snapshots/
    python scripts/distribution.py out/snapshots/ --with-domains > work/distribution-domains.txt

Prints p50, p75, p90, p95 and the maximum of the weight and the request count until `load`, the
time until `load` under the network profile and the level-2 duration per domain, plus the
canonical findings. Domain names and URLs are printed only with `--with-domains`, and that output
goes only into `work/`, because per-domain results do not go into the repository.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from sitetriage import store
from sitetriage.config import get, load_config
from sitetriage.score import analyze


def distribution(name: str, values: list[float], note: str = "") -> None:
    if len(values) < 2:
        print(f"{name:<34} not enough data {note}")
        return
    q = statistics.quantiles(values, n=100, method="inclusive")
    parts = "  ".join(f"{p} {q[int(p[1:]) - 1]:6.1f}" for p in ("p50", "p75", "p90", "p95"))
    print(f"{name:<34} n={len(values):<3} {parts}  max {max(values):6.1f} {note}")


def main(directory: str, with_domains: bool) -> int:
    config = load_config()
    pairs = list(store.read_all(Path(directory)))
    browsers = [b for _, b in pairs if b is not None]
    if not browsers:
        print(f"no level-2 snapshots in {directory}")
        return 1

    loaded = [b for b in browsers if b.timing.reached == "load"]
    distribution(
        "weight until load w/o video (MB)",
        [(b.network.bytes_at_load - b.network.bytes_by_type_at_load.get("media", 0)) / 1e6 for b in loaded],
    )
    distribution("requests until load", [b.network.requests_at_load for b in loaded])

    # Time is valid only under the profile and on a link that `perf.load.time` accepts
    # (ADR-010, ADR-018).
    ratio = get(config, "network_profile.min_link_ratio")
    under_profile = [
        b
        for b in browsers
        if b.network_profile and b.link_mbps and b.link_mbps >= ratio * b.network_profile.download_mbps
    ]
    timeout_s = get(config, "browser.timeout_s")
    timed_out = sum(b.timing.reached == "timeout" for b in under_profile)
    # A timeout counts as the timeout itself: the real time is longer, so the upper percentiles
    # are a lower bound.
    distribution(
        "until load under profile (s)",
        [b.timing.load_ms / 1000 for b in under_profile if b.timing.reached == "load"]
        + [timeout_s] * timed_out,
        f"(timeouts: {timed_out}, counted as {timeout_s} s)" if timed_out else "",
    )
    distribution(
        "level 2 duration per domain (s)",
        [b.elapsed_ms / 1000 for b in browsers if b.elapsed_ms is not None],
        "(snapshots from before 2.0 do not have it)",
    )

    print("\ncanonical findings:")
    for site, browser in pairs:
        for f in analyze(site, config, browser=browser).findings:
            if f.check_id != "seo.canonical.duplicate":
                continue
            e = f.evidence
            print(
                f"  {f.severity:<8} share {e['share']:.2f} ({e['page_count']}/{e['total']} pages, "
                f"{e['path_groups']} path groups, sample {e['sample']})"
            )
            if with_domains:
                print(f"    {site.domain} → {e['canonical']}")
                for url in f.evidence_urls:
                    print(f"      {url}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--with-domains"]
    if len(args) != 1 or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    sys.exit(main(args[0], "--with-domains" in sys.argv))
