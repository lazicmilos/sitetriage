"""Performance checks, and one QA check measured in the same run.

Thresholds are **tiered**: one finding is reported per `check_id`, at the highest
severity that applies, not three findings for the same page (ADR-020).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sitetriage.checks.registry import Context, check, finding, ok, unknown
from sitetriage.models import OversizedImage, SiteSnapshot

COMPRESSED = {"gzip", "br", "zstd", "deflate"}
BYTES_PER_MB = 1_000_000  # decimal MB: 14 903 221 B = 14.9 MB, the way it is written in the email


def _tier(value: float, tiers: dict[str, float]) -> str | None:
    """The highest severity whose threshold is exceeded, or `None`."""
    for severity in ("critical", "high", "medium"):
        if severity in tiers and value > tiers[severity]:
            return severity
    return None


def _vector_or_inline(src: str) -> bool:
    return src.startswith("data:") or urlsplit(src).path.lower().endswith(".svg")


def _mb_per_s(ctx: Context) -> float:
    """A slower mobile connection: 4.8 Mb/s = 0.6 MB/s (ADR-010)."""
    return ctx.th("network_profile.download_mbps") / 8


def _seconds_on_mobile(mb: float, ctx: Context) -> float:
    """0.6 MB/s plus overhead. The assumption must be stated in a report footnote (ADR-010)."""
    return round(mb / _mb_per_s(ctx) + ctx.th("report.mobile_overhead_s"), 1)


# --------------------------------------------------------------------------- #
# Level 1
# --------------------------------------------------------------------------- #
@check(
    "perf.compression.missing",
    level=1,
    category="perf",
    # low, not medium: the saving on the HTML alone is tenths of a second (docs/izvestaj-testiranja-100.md).
    base_severity="low",
    requires=["home"],
    description="The server does not send the HTML compressed.",
    threshold="content-encoding ∉ {gzip, br, zstd, deflate} and HTML > 50 kB",
)
def compression_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    encoding = (home.headers.get("content-encoding") or "").lower().strip()
    min_bytes = ctx.th("thresholds.perf.compression_min_kb") * 1024
    if encoding in COMPRESSED or home.html_bytes <= min_bytes:
        return ok(compression_missing.spec)
    # Truncated HTML is larger than what was read, so the size and the saving are a lower bound ("more than").
    return finding(
        compression_missing.spec,
        ctx,
        evidence={
            "encoding": encoding or None,
            "bytes": home.html_bytes,
            "kb": round(home.html_bytes / 1024),
            # gzip and br shrink HTML to about a quarter; the saving is the rest, on the slower connection
            "saving_s": round(home.html_bytes * 0.75 / BYTES_PER_MB / _mb_per_s(ctx), 1),
            "speed_mbps": ctx.th("network_profile.download_mbps"),
        },
        urls=[home.final_url or home.url],
        variant="truncated" if home.truncated else None,
    )


@check(
    "perf.redirect.chain",
    level=1,
    category="perf",
    base_severity="low",
    requires=["entry_response"],
    description="The home page opens through a chain of redirects.",
    threshold="number of hops ≥ thresholds.perf.redirect_hops (3)",
)
def redirect_chain(snapshot: SiteSnapshot, ctx: Context):
    chain = snapshot.entry.redirect_chain
    hops = max(len(chain) - 1, 0)
    if hops < ctx.th("thresholds.perf.redirect_hops"):
        return ok(redirect_chain.spec)
    return finding(
        redirect_chain.spec,
        ctx,
        evidence={"hops": hops, "chain": chain},
        urls=chain[:1],
    )


@check(
    "perf.html.size",
    level=1,
    category="perf",
    base_severity="low",
    requires=["home"],
    description="The HTML document itself is too large.",
    threshold="html_bytes > thresholds.perf.html_size_kb (500 kB)",
)
def html_size(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    limit_kb = ctx.th("thresholds.perf.html_size_kb")
    kb = round(home.html_bytes / 1024)
    if home.html_bytes <= limit_kb * 1024:
        # Truncated HTML is larger than what was read: whether it is larger than the threshold is not known.
        if home.truncated:
            return unknown(html_size.spec, "body_truncated", kb=kb)
        return ok(html_size.spec)
    return finding(
        html_size.spec,
        ctx,
        evidence={"bytes": home.html_bytes, "kb": kb, "threshold_kb": limit_kb},
        urls=[home.final_url or home.url],
        variant="truncated" if home.truncated else None,
    )


# --------------------------------------------------------------------------- #
# Level 2
# --------------------------------------------------------------------------- #
@check(
    "perf.page.weight",
    level=2,
    category="perf",
    base_severity="critical",
    requires=["network", "v2:network.bytes_at_load"],
    description="Weight of the home page: what is transferred for requests started before the `load` event.",
    threshold="transferred until load, without video: > 2 MB medium · > 4 MB high · > 7 MB critical",
)
def page_weight(snapshot, ctx: Context):
    network = snapshot.network
    # Without `load` the "until load" measure is incomplete, so even a large number is not a claim (ADR-016).
    if snapshot.timing.reached != "load":
        return unknown(page_weight.spec, "load_incomplete")
    max_unmeasured = ctx.th("browser.max_unmeasured_responses")
    if network.unmeasured_at_load > max_unmeasured:
        # A measurement you do not trust is worse than none (ADR-016).
        unmeasured = network.unmeasured_at_load
        return unknown(
            page_weight.spec, "unmeasured_responses", unmeasured=unmeasured, threshold=max_unmeasured
        )

    # Video downloads for as long as the measurement allows (the same site measured 8.5 MB once
    # and 26.9 MB another time), so it stays out of the threshold and is stated separately in the
    # message (ADR-016).
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
            "bytes": network.bytes_at_load,
            "mb": round(mb, 1),
            "video_mb": video_mb,
            "seconds": _seconds_on_mobile(mb, ctx),
            "speed_mbps": ctx.th("network_profile.download_mbps"),
            "requests": network.requests_at_load,
            "unmeasured": network.unmeasured_at_load,
            "reached": snapshot.timing.reached,
            "bytes_by_type": network.bytes_by_type_at_load,
            # Including what arrives after `load`, and video: informational only, outside the threshold.
            "total_bytes": network.total_bytes,
            "total_requests": network.request_count,
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
    description="Number of network requests started before the `load` event when opening the home page.",
    threshold="requests until load: > 60 medium · > 90 high",
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
            "requests": count,
            "total_requests": snapshot.network.request_count,
            "reached": snapshot.timing.reached,
        },
        urls=[snapshot.url],
    )


@check(
    "perf.load.time",
    level=2,
    category="perf",
    base_severity="high",
    # Seconds hold for the connection they were measured on; a snapshot without a profile was
    # measured on the real one (ADR-010), and the profile cannot speed up a link slower than itself
    # (ADR-018).
    requires=["browser", "level2_full", "network_profile", "link"],
    description=(
        "Time until the home page has fully loaded, on the simulated connection from `[network_profile]`."
    ),
    threshold="> 6 s medium · > 9 s high · cut off after the hard limit = high",
)
def load_time(snapshot, ctx: Context):
    required = ctx.th("network_profile.min_link_ratio") * snapshot.network_profile.download_mbps
    if snapshot.link_mbps < required:
        return unknown(load_time.spec, "link_slow", measured_mbps=snapshot.link_mbps, required_mbps=required)
    timing = snapshot.timing
    if timing.reached == "timeout":
        # A page that does not reach `load` within the hard limit is a measurement in itself.
        limit_s = ctx.th("browser.timeout_s")
        return finding(
            load_time.spec,
            ctx,
            severity="high",
            evidence={
                "load_ms": None,
                "seconds": limit_s,
                "speed_mbps": snapshot.network_profile.download_mbps,
                "reached": "timeout",
            },
            urls=[snapshot.url],
            # Not "it takes 25 s": how long it takes is not known, only that it is more than that.
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
            "seconds": round(timing.load_ms / 1000, 1),
            "speed_mbps": snapshot.network_profile.download_mbps,
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
    description="Images are sent much larger than they are displayed.",
    threshold=(
        "≥ 3 images with a ratio > 2.5 and measured waste, or estimated waste > 700 kB; "
        "SVG and data: images do not count"
    ),
)
def img_oversized(snapshot, ctx: Context):
    dom = snapshot.dom
    # An SVG has no "real" size, and a data: placeholder for lazy loading has no transfer.
    # The same image several times on a page (cloned slides) is downloaded once (BUG-030).
    by_src: dict[str, OversizedImage] = {}
    for img in dom.oversized_images:
        if _vector_or_inline(img.src):
            continue
        earlier = by_src.get(img.src)
        if earlier is None or img.est_waste_kb > earlier.est_waste_kb:
            by_src[img.src] = img
    raster = sorted(by_src.values(), key=lambda img: -img.est_waste_kb)
    # Without a measured transfer the waste is 0, and the sentence would say "about 0 kB" (BUG-023).
    oversized = [img for img in raster if img.est_waste_kb > 0]
    waste_kb = round(sum(img.est_waste_kb for img in oversized))
    min_count = ctx.th("thresholds.perf.oversized_min_count")
    max_waste = ctx.th("thresholds.perf.oversized_waste_kb")

    if len(oversized) >= min_count or waste_kb > max_waste:
        return finding(
            img_oversized.spec,
            ctx,
            evidence={
                "image_count": len(oversized),
                "kb": waste_kb,
                "ratio_threshold": ctx.th("thresholds.perf.image_ratio"),
                "unmeasured": dom.images_unmeasured,
                "worst_image": oversized[0].src if oversized else None,
            },
            urls=[img.src for img in oversized[:5]],
        )
    if len(raster) >= min_count:
        return unknown(img_oversized.spec, "oversized_unmeasured", count=len(raster) - len(oversized))
    # Without this you cannot tell whether "0 oversized images" is a result or a failed measurement.
    if dom.images_unmeasured and dom.images_unmeasured >= dom.images_total / 2:
        return unknown(
            img_oversized.spec, "images_unmeasured", unmeasured=dom.images_unmeasured, total=dom.images_total
        )
    return ok(img_oversized.spec)


@check(
    "qa.console.errors",
    level=2,
    category="qa",
    base_severity="low",
    requires=["browser"],
    description="Console errors: scripts and parts of the page that did not load.",
    threshold="> thresholds.qa.console_errors (3)",
)
def console_errors(snapshot, ctx: Context):
    # A weak sales signal, so it stays `low` and does not go into the email.
    console = snapshot.console
    if console.errors <= ctx.th("thresholds.qa.console_errors"):
        return ok(console_errors.spec)
    return finding(
        console_errors.spec,
        ctx,
        evidence={
            "errors": console.errors,
            "warnings": console.warnings,
            "first_error": console.samples[0] if console.samples else None,
        },
        urls=[snapshot.url],
    )
