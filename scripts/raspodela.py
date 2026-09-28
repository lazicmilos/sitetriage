"""Raspodela mera nivoa 2 iz sačuvanih snapshota, za kalibraciju pragova (Z-50).

    python scripts/raspodela.py izvestaj/snapshots/
    python scripts/raspodela.py izvestaj/snapshots/ --sa-domenima > rad/raspodela-domeni.txt

Ispisuje p50, p75, p90, p95 i maksimum za težinu i broj zahteva do `load`, vreme do `load` pod
mrežnim profilom i trajanje nivoa 2 po domenu, plus canonical nalaze. Imena domena i adrese idu
samo uz `--sa-domenima`, i taj izlaz ide samo u `rad/`, jer rezultati po domenu ne ulaze u repo.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from skener import store
from skener.config import get, load_config
from skener.score import analyze


def raspodela(ime: str, vrednosti: list[float], napomena: str = "") -> None:
    if len(vrednosti) < 2:
        print(f"{ime:<34} nema dovoljno podataka {napomena}")
        return
    q = statistics.quantiles(vrednosti, n=100, method="inclusive")
    delovi = "  ".join(f"{p} {q[int(p[1:]) - 1]:6.1f}" for p in ("p50", "p75", "p90", "p95"))
    print(f"{ime:<34} n={len(vrednosti):<3} {delovi}  max {max(vrednosti):6.1f} {napomena}")


def main(directory: str, sa_domenima: bool) -> int:
    config = load_config()
    pairs = list(store.read_all(Path(directory)))
    browsers = [b for _, b in pairs if b is not None]
    if not browsers:
        print(f"nema snapshota nivoa 2 u {directory}")
        return 1

    do_load = [b for b in browsers if b.timing.reached == "load"]
    raspodela(
        "težina do load bez videa (MB)",
        [(b.network.bytes_at_load - b.network.bytes_by_type_at_load.get("media", 0)) / 1e6 for b in do_load],
    )
    raspodela("zahteva do load", [b.network.requests_at_load for b in do_load])

    # Vreme važi samo pod profilom i na vezi koju `perf.load.time` prihvata (Z-30, Z-33).
    ratio = get(config, "network_profile.min_link_ratio")
    pod_profilom = [
        b
        for b in browsers
        if b.network_profile and b.link_mbps and b.link_mbps >= ratio * b.network_profile.download_mbps
    ]
    timeout_s = get(config, "browser.timeout_s")
    prekinuti = sum(b.timing.reached == "timeout" for b in pod_profilom)
    # Prekid se broji kao sam rok: pravo vreme je duže, pa su gornji percentili donja granica.
    raspodela(
        "do load pod profilom (s)",
        [b.timing.load_ms / 1000 for b in pod_profilom if b.timing.reached == "load"]
        + [timeout_s] * prekinuti,
        f"(prekida: {prekinuti}, računati kao {timeout_s} s)" if prekinuti else "",
    )
    raspodela(
        "trajanje nivoa 2 po domenu (s)",
        [b.elapsed_ms / 1000 for b in browsers if b.elapsed_ms is not None],
        "(snimci pre Z-50 ga nemaju)",
    )

    print("\ncanonical nalazi:")
    for site, browser in pairs:
        for f in analyze(site, config, browser=browser).findings:
            if f.check_id != "seo.canonical.duplicate":
                continue
            e = f.evidence
            print(
                f"  {f.severity:<8} udeo {e['udeo']:.2f} ({e['stranica']}/{e['ukupno']} stranica, "
                f"{e['grupa_putanja']} grupe putanja, uzorak {e['uzorak']})"
            )
            if sa_domenima:
                print(f"    {site.domain} → {e['canonical']}")
                for url in f.evidence_urls:
                    print(f"      {url}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--sa-domenima"]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(main(args[0], "--sa-domenima" in sys.argv))
