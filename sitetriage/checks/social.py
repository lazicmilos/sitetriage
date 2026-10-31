"""Open Graph checks.

Hotel and restaurant links get shared in messages and groups; a guest who gets a bare
URL without an image and a title does not click. That is why `social` carries a
multiplier of 1.5 for hotels and 0.7 for b2b (`[industry_multipliers]` in `sitetriage.toml`).
"""

from __future__ import annotations

from sitetriage.checks.registry import Context, check, finding, ok
from sitetriage.models import SiteSnapshot


def _og_count(snapshot: SiteSnapshot) -> int:
    og = snapshot.home.og
    return sum(1 for value in (og.title, og.description, og.image, og.url) if value)


@check(
    "social.og.title.missing",
    level=1,
    category="social",
    base_severity="high",
    requires=["home", "home_complete"],
    description="Početna nema og:title.",
    threshold="nedostaje <meta property=og:title>",
)
def og_title_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.title:
        return ok(og_title_missing.spec)
    return finding(
        og_title_missing.spec,
        ctx,
        evidence={
            "page": snapshot.home.final_url or snapshot.home.url,
            "og_tag_count": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "social.og.description.missing",
    level=1,
    category="social",
    base_severity="medium",
    requires=["home", "home_complete"],
    description="Početna nema og:description.",
    threshold="nedostaje <meta property=og:description>",
)
def og_description_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.description:
        return ok(og_description_missing.spec)
    return finding(
        og_description_missing.spec,
        ctx,
        evidence={
            "page": snapshot.home.final_url or snapshot.home.url,
            "og_tag_count": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "social.og.image.missing",
    level=1,
    category="social",
    base_severity="medium",
    requires=["home", "home_complete"],
    description="Početna nema og:image.",
    threshold="nedostaje <meta property=og:image>",
)
def og_image_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.image:
        return ok(og_image_missing.spec)
    return finding(
        og_image_missing.spec,
        ctx,
        evidence={
            "page": snapshot.home.final_url or snapshot.home.url,
            "og_tag_count": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )
