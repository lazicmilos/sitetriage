"""Provere performansi (§5, §7.3) i jedna QA provera koja se meri istim prolazom.

Pragovi su **stepenasti**: prijavljuje se jedan nalaz po `check_id`, sa najvišom
ozbiljnošću koja važi — ne tri nalaza za istu stranicu (§7.3).
"""

from __future__ import annotations

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

COMPRESSED = {"gzip", "br", "zstd", "deflate"}
BYTES_PER_MB = 1_000_000  # decimalni MB — 14 903 221 B = 14,9 MB, kako se i piše u mejlu


def _tier(value: float, tiers: dict[str, float]) -> str | None:
    """Najviša ozbiljnost čiji je prag prekoračen, ili `None`."""
    for severity in ("critical", "high", "medium"):
        if severity in tiers and value > tiers[severity]:
            return severity
    return None


def _mb_per_s(ctx: Context) -> float:
    """Sporija mobilna veza: 4,8 Mb/s = 0,6 MB/s (§10.3)."""
    return ctx.th("thresholds.perf.mobile_speed_mbps") / 8


def _seconds_on_mobile(mb: float, ctx: Context) -> float:
    """0,6 MB/s + režija. Pretpostavka mora da stoji u fusnoti izveštaja (§10.3)."""
    return round(mb / _mb_per_s(ctx) + ctx.th("report.mobile_overhead_s"), 1)


# --------------------------------------------------------------------------- #
# Nivo 1
# --------------------------------------------------------------------------- #
@check(
    "perf.compression.missing",
    level=1,
    category="perf",
    # low, ne medium: ušteda na samom HTML-u je desetinke sekunde (docs/izvestaj-testiranja-100.md).
    base_severity="low",
    requires=["home"],
    description="Server ne šalje HTML kompresovan.",
    threshold="content-encoding ∉ {gzip, br, zstd, deflate} i HTML > 50 kB",
)
def compression_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    encoding = (home.headers.get("content-encoding") or "").lower().strip()
    min_bytes = ctx.th("thresholds.perf.compression_min_kb") * 1024
    if encoding in COMPRESSED or home.html_bytes <= min_bytes:
        return ok(compression_missing.spec)
    return finding(
        compression_missing.spec,
        ctx,
        evidence={
            "kodiranje": encoding or None,
            "bajtova": home.html_bytes,
            "kb": round(home.html_bytes / 1024),
            # gzip i br svode HTML na otprilike četvrtinu; ušteda je ostatak, na sporijoj vezi
            "usteda_s": round(home.html_bytes * 0.75 / BYTES_PER_MB / _mb_per_s(ctx), 1),
            "brzina": ctx.th("thresholds.perf.mobile_speed_mbps"),
        },
        urls=[home.final_url or home.url],
    )


@check(
    "perf.redirect.chain",
    level=1,
    category="perf",
    base_severity="low",
    requires=["entry_response"],
    description="Početna se otvara kroz niz preusmerenja.",
    threshold="broj skokova ≥ thresholds.perf.redirect_hops (3)",
)
def redirect_chain(snapshot: SiteSnapshot, ctx: Context):
    chain = snapshot.entry.redirect_chain
    hops = max(len(chain) - 1, 0)
    if hops < ctx.th("thresholds.perf.redirect_hops"):
        return ok(redirect_chain.spec)
    return finding(
        redirect_chain.spec,
        ctx,
        evidence={"skokova": hops, "lanac": chain},
        urls=chain[:1],
    )


@check(
    "perf.html.size",
    level=1,
    category="perf",
    base_severity="low",
    requires=["home"],
    description="Sam HTML dokument je prevelik.",
    threshold="html_bytes > thresholds.perf.html_size_kb (500 kB)",
)
def html_size(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    limit_kb = ctx.th("thresholds.perf.html_size_kb")
    if home.html_bytes <= limit_kb * 1024:
        return ok(html_size.spec)
    return finding(
        html_size.spec,
        ctx,
        evidence={"bajtova": home.html_bytes, "kb": round(home.html_bytes / 1024), "prag_kb": limit_kb},
        urls=[home.final_url or home.url],
    )


# --------------------------------------------------------------------------- #
# Nivo 2
# --------------------------------------------------------------------------- #
@check(
    "perf.page.weight",
    level=2,
    category="perf",
    base_severity="critical",
    requires=["network", "v2:network.bytes_at_load"],
    description="Težina početne strane: šta se prenese za zahteve započete do događaja `load`.",
    threshold="preneto do load, bez videa: > 3 MB medium · > 5 MB high · > 8 MB critical",
)
def page_weight(snapshot, ctx: Context):
    network = snapshot.network
    # Bez `load` mera „do load" je nepotpuna, pa ni velik broj nije tvrdnja (Z-24).
    if snapshot.timing.reached != "load":
        return unknown(page_weight.spec, "load_incomplete")
    max_unmeasured = ctx.th("browser.max_unmeasured_responses")
    if network.unmeasured_at_load > max_unmeasured:
        # Merenje u koje nemaš poverenja gore je od merenja kojeg nema (§7.2).
        nemereno = network.unmeasured_at_load
        return unknown(page_weight.spec, "unmeasured_responses", nemereno=nemereno, prag=max_unmeasured)

    # Video se skida koliko vreme merenja dozvoli — isti sajt je izmeren jednom 8,5, a
    # drugi put 26,9 MB — pa ne ulazi u prag, nego stoji posebno u poruci (O-2).
    video = network.bytes_by_type_at_load.get("media", 0)
    video_mb = round(video / BYTES_PER_MB, 1)
    mb = (network.bytes_at_load - video) / BYTES_PER_MB
    severity = _tier(mb, ctx.th("thresholds.perf.page_weight_mb"))
    if severity is None:
        return ok(page_weight.spec)
    return finding(
        page_weight.spec,
        ctx,
        severity=severity,
        evidence={
            "bajtova": network.bytes_at_load,
            "mb": round(mb, 1),
            "video_mb": video_mb,
            "sekundi": _seconds_on_mobile(mb, ctx),
            "brzina": ctx.th("thresholds.perf.mobile_speed_mbps"),
            "zahteva": network.requests_at_load,
            "nemereno": network.unmeasured_at_load,
            "reached": snapshot.timing.reached,
            "po_tipu": network.bytes_by_type_at_load,
            # Sa onim što stigne posle `load`, i sa videom: samo informativno, van praga.
            "ukupno_bajtova": network.total_bytes,
            "ukupno_zahteva": network.request_count,
        },
        urls=[snapshot.url],
        variant="video" if video else None,
    )


@check(
    "perf.request.count",
    level=2,
    category="perf",
    base_severity="high",
    requires=["network", "v2:network.requests_at_load"],
    description="Broj mrežnih zahteva započetih do događaja `load` pri otvaranju početne.",
    threshold="zahtevi do load: > 100 medium · > 150 high",
)
def request_count(snapshot, ctx: Context):
    count = snapshot.network.requests_at_load
    severity = _tier(count, ctx.th("thresholds.perf.request_count"))
    if severity is None:
        if snapshot.timing.reached == "timeout":
            return unknown(request_count.spec, "load_incomplete")
        return ok(request_count.spec)
    return finding(
        request_count.spec,
        ctx,
        severity=severity,
        evidence={
            "zahteva": count,
            "ukupno_zahteva": snapshot.network.request_count,
            "reached": snapshot.timing.reached,
        },
        urls=[snapshot.url],
    )


@check(
    "perf.load.time",
    level=2,
    category="perf",
    base_severity="high",
    requires=["browser"],
    description="Vreme do potpunog učitavanja početne.",
    threshold="> 4 s medium · > 8 s high · prekid posle tvrdog limita = high",
)
def load_time(snapshot, ctx: Context):
    timing = snapshot.timing
    if timing.reached == "timeout":
        # Stranica koja ne stigne do `load` unutar tvrdog limita je merenje samo po sebi.
        limit_s = ctx.th("browser.timeout_s")
        return finding(
            load_time.spec,
            ctx,
            severity="high",
            evidence={"load_ms": None, "sekundi": limit_s, "reached": "timeout"},
            urls=[snapshot.url],
            # Ne „treba joj 25 s": ne zna se koliko joj treba, samo da je više od toga.
            variant="timeout",
        )
    if timing.load_ms is None:
        return unknown(load_time.spec, "load_not_measured")
    severity = _tier(timing.load_ms, ctx.th("thresholds.perf.load_ms"))
    if severity is None:
        return ok(load_time.spec)
    return finding(
        load_time.spec,
        ctx,
        severity=severity,
        evidence={
            "load_ms": timing.load_ms,
            "sekundi": round(timing.load_ms / 1000, 1),
            "reached": timing.reached,
        },
        urls=[snapshot.url],
    )


@check(
    "perf.img.oversized",
    level=2,
    category="perf",
    base_severity="medium",
    requires=["browser"],
    description="Slike se šalju znatno veće nego što se prikazuju.",
    threshold="≥ 3 slike sa odnosom > 2,5 ili procenjen višak > 700 kB",
)
def img_oversized(snapshot, ctx: Context):
    dom = snapshot.dom
    oversized = dom.oversized_images
    waste_kb = round(sum(img.est_waste_kb for img in oversized))
    min_count = ctx.th("thresholds.perf.oversized_min_count")
    max_waste = ctx.th("thresholds.perf.oversized_waste_kb")

    if len(oversized) >= min_count or waste_kb > max_waste:
        return finding(
            img_oversized.spec,
            ctx,
            evidence={
                "broj_slika": len(oversized),
                "kb": waste_kb,
                "prag_odnosa": ctx.th("thresholds.perf.image_ratio"),
                "nemereno": dom.images_unmeasured,
                "najgora": oversized[0].src if oversized else None,
            },
            urls=[img.src for img in oversized[:5]],
        )
    # Bez ovoga ne znaš da li je „0 predimenzioniranih slika" nalaz ili neuspelo merenje (§3.3).
    if dom.images_unmeasured and dom.images_unmeasured >= dom.images_total / 2:
        return unknown(
            img_oversized.spec, "images_unmeasured", nemereno=dom.images_unmeasured, ukupno=dom.images_total
        )
    return ok(img_oversized.spec)


@check(
    "qa.console.errors",
    level=2,
    category="qa",
    base_severity="low",
    requires=["browser"],
    description="JavaScript greške u konzoli.",
    threshold="> thresholds.qa.console_errors (3)",
)
def console_errors(snapshot, ctx: Context):
    # Slab prodajni signal — zato ostaje `low` i ne ide u mejl (§15, zamka 9).
    console = snapshot.console
    if console.errors <= ctx.th("thresholds.qa.console_errors"):
        return ok(console_errors.spec)
    return finding(
        console_errors.spec,
        ctx,
        evidence={
            "greske": console.errors,
            "upozorenja": console.warnings,
            "primer": console.samples[0] if console.samples else None,
        },
        urls=[snapshot.url],
    )
