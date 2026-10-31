"""Accessibility checks.

HTML has **three** states, not two: no `alt` attribute (an error), `alt=""`
(deliberate, a decorative image, correct under WCAG) and `alt="text"` (correct).
A tool that reports `alt=""` as an error reports a correctly built site as
broken, and you send that in an email.
"""

from __future__ import annotations

from sitetriage.checks.registry import Context, check, finding, ok, unknown

# Legal exposure on accessibility is higher, so the severity threshold is lower.
EXPOSED_INDUSTRIES = {"healthcare", "institution"}


@check(
    "a11y.img.alt.missing",
    level=2,
    category="a11y",
    base_severity="low",
    requires=["browser"],
    description="Most images have no alt attribute (an empty alt does not count).",
    threshold=(
        "≥ 5 images and share without an alt attribute > 0.5; > 0.8 with ≥ 15 images → high; "
        "healthcare/institution → at least medium"
    ),
)
def img_alt_missing(snapshot, ctx: Context):
    dom = snapshot.dom
    min_images = ctx.th("thresholds.a11y.min_images")

    if dom.images_total == 0 and snapshot.timing.reached == "timeout":
        return unknown(img_alt_missing.spec, "images_timeout")
    if dom.images_total < min_images:
        return ok(img_alt_missing.spec)

    ratio = dom.images_without_alt_attr / dom.images_total
    if ratio <= ctx.th("thresholds.a11y.missing_ratio"):
        return ok(img_alt_missing.spec)

    severity = "medium" if ctx.industry in EXPOSED_INDUSTRIES else "low"
    if ratio > ctx.th("thresholds.a11y.high_ratio") and dom.images_total >= ctx.th(
        "thresholds.a11y.high_min_images"
    ):
        severity = "high"

    return finding(
        img_alt_missing.spec,
        ctx,
        severity=severity,
        evidence={
            "without_alt": dom.images_without_alt_attr,
            "total": dom.images_total,
            "empty_alt": dom.images_empty_alt,
            "share": round(ratio, 3),
            "unmeasured": dom.images_unmeasured,
        },
        urls=[snapshot.url],
    )
