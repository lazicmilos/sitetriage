"""SEO checks."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable

from sitetriage.checks.registry import CheckSpec, Context, check, finding, not_applicable, ok, unknown
from sitetriage.fetch.urls import collapse_ws, normalize, path_group, same_site
from sitetriage.models import CheckResult, PageSnapshot, SiteSnapshot

_SCHEME_AND_WWW = re.compile(r"^https?://(www\.)?")


def _too_few_pages(snapshot: SiteSnapshot, ctx: Context, spec: CheckSpec) -> CheckResult | None:
    """The sample has fewer pages than the comparison needs: `unknown` or `not_applicable` (ADR-015).

    `not_applicable` only when the site really has no more pages: the budget did not run out, all
    sources together (sitemap, links from the home page, links from the rendered DOM) see fewer
    URLs than the threshold, and at least one source sees what JS renders. Otherwise `unknown`, and
    the reason says which condition was not met.
    """
    threshold = ctx.th("thresholds.seo.duplicate_min_pages")
    if sum(1 for p in snapshot.pages if p.status == 200) >= threshold:
        return None
    if snapshot.budget.exhausted:
        return unknown(spec, "pages_budget", threshold=threshold)
    if snapshot.scanner_version.startswith("1."):
        return unknown(spec, "v1_snapshot", version=snapshot.scanner_version, field="home_links")

    home = snapshot.home
    base = home.final_url or home.url
    sources = [snapshot.home_links]
    if snapshot.sitemap.status == 200 and not snapshot.sitemap.truncated:
        sources.append(snapshot.sitemap.urls)
    b = ctx.browser
    level2 = b is not None and b.status != "failed" and b.dom.internal_links_total is not None
    if level2:
        sources.append(b.dom.internal_links)
    # The home page is a URL of the site even when no link leads to it.
    urls = {normalize(base)} | {u for source in sources for u in map(normalize, source) if same_site(u, base)}
    if len(urls) >= threshold:
        return unknown(spec, "pages_sample", threshold=threshold, address_count=len(urls))
    empty = home.text_length < ctx.th("escalation.empty_html_text_threshold") or not home.h1_count_raw
    if not level2 and empty:
        return unknown(spec, "pages_js", threshold=threshold)
    return not_applicable(spec, "few_pages", threshold=threshold, address_count=len(urls))


def _duplicates(
    snapshot: SiteSnapshot, value_of: Callable[[PageSnapshot], str | None], min_pages: int
) -> tuple[str, list[PageSnapshot], set[str]] | None:
    """The largest group of pages with an identical value, if it exceeds the threshold.

    It takes ≥ `min_pages` pages from ≥ `min_pages` **different** path groups. Requiring
    different groups is what protects a clean site from false positives: eight blog posts
    with the same template title are not the same as a whole site that presents itself as
    one page.
    """
    buckets: dict[str, list[PageSnapshot]] = defaultdict(list)
    # A URL that redirects to a page already seen is not one more page (BUG-029).
    seen: set[str | None] = set()
    for page in snapshot.pages:
        url = normalize(page.final_url or page.url)
        if page.status != 200 or url in seen:
            continue
        seen.add(url)
        value = value_of(page)
        if value:
            buckets[value].append(page)

    for value, pages in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        groups = {path_group(p.final_url or p.url) for p in pages}
        if len(pages) >= min_pages and len(groups) >= min_pages:
            return value, pages, groups
    return None


# --------------------------------------------------------------------------- #
# canonical
# --------------------------------------------------------------------------- #
@check(
    "seo.canonical.missing",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home", "home_complete"],
    description="Početna strana nema <link rel=canonical>.",
    threshold="nema oznake na početnoj",
)
def canonical_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    if home.canonical:
        return ok(canonical_missing.spec)
    return finding(
        canonical_missing.spec,
        ctx,
        evidence={"page": home.final_url or home.url, "canonical_tag_count": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.canonical.duplicate",
    level=1,
    category="seo",
    base_severity="critical",
    requires=["home", "home_complete"],
    description=(
        "Više stranica iz različitih delova sajta upućuje canonical-om na istu drugu adresu. "
        "Stranica koja upućuje na sebe, ili na svoju `http` ili `www` verziju, se ne broji."
    ),
    threshold=(
        "≥ 2 stranice sa tuđim canonical-om ka istoj adresi, iz ≥ 2 grupe putanja; udeo u uzorku "
        "≥ 0,4 high · ≥ 0,6 critical · inače medium"
    ),
)
def canonical_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if few := _too_few_pages(snapshot, ctx, canonical_duplicate.spec):
        return few

    def foreign(page: PageSnapshot) -> str | None:
        # A foreign canonical exists and points to a different URL from the one the page is on.
        # `http`/`https` and a leading `www.` of the same page are not a different URL: Google shows
        # that same page, so the sentence would show the owner their own URL (ADR-020).
        target = page.canonical_normalized
        own = normalize(page.final_url or page.url) or ""
        return target if target and _SCHEME_AND_WWW.sub("", target) != _SCHEME_AND_WWW.sub("", own) else None

    hit = _duplicates(snapshot, foreign, ctx.th("thresholds.seo.canonical_foreign_min"))
    if not hit:
        return ok(canonical_duplicate.spec)
    value, pages, groups = hit
    total = sum(1 for p in snapshot.pages if p.status == 200)
    share = len(pages) / total
    thresholds = ctx.th("thresholds.seo.canonical_share")
    return finding(
        canonical_duplicate.spec,
        ctx,
        evidence={
            "canonical": value,
            "page_count": len(pages),
            "total": total,
            "share": round(share, 4),
            "path_groups": len(groups),
            "sample": snapshot.sample_source,  # a sample taken from links is less reliable
        },
        urls=[p.final_url or p.url for p in pages],
        severity=next((s for s in ("critical", "high") if share >= thresholds[s]), "medium"),
    )


# --------------------------------------------------------------------------- #
# title
# --------------------------------------------------------------------------- #
@check(
    "seo.title.missing",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home", "home_complete"],
    description="Početna strana nema <title> ili je prazan.",
    threshold="prazan ili nepostojeći <title>",
)
def title_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    title = collapse_ws(home.title)
    if title:
        return ok(title_missing.spec)
    return finding(
        title_missing.spec,
        ctx,
        evidence={"page": home.final_url or home.url, "title_length": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.title.duplicate",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home", "home_complete"],
    description="Više stranica iz različitih delova sajta ima identičan naslov.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim naslovom",
)
def title_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if few := _too_few_pages(snapshot, ctx, title_duplicate.spec):
        return few
    hit = _duplicates(snapshot, lambda p: collapse_ws(p.title), ctx.th("thresholds.seo.duplicate_min_pages"))
    if not hit:
        return ok(title_duplicate.spec)
    value, pages, groups = hit
    return finding(
        title_duplicate.spec,
        ctx,
        evidence={
            "title": value,
            "page_count": len(pages),
            "path_groups": len(groups),
            "sample": snapshot.sample_source,  # a sample taken from links is less reliable
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# description
# --------------------------------------------------------------------------- #
@check(
    "seo.description.missing",
    level=1,
    category="seo",
    base_severity="medium",
    requires=["home", "home_complete"],
    description="Početna strana nema <meta name=description>.",
    threshold="prazan ili nepostojeći meta opis",
)
def description_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    if collapse_ws(home.meta_description):
        return ok(description_missing.spec)
    return finding(
        description_missing.spec,
        ctx,
        evidence={"page": home.final_url or home.url, "description_length": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.description.duplicate",
    level=1,
    category="seo",
    base_severity="medium",
    requires=["home", "home_complete"],
    description="Više stranica iz različitih delova sajta ima identičan meta opis.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim opisom",
)
def description_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if few := _too_few_pages(snapshot, ctx, description_duplicate.spec):
        return few
    hit = _duplicates(
        snapshot, lambda p: collapse_ws(p.meta_description), ctx.th("thresholds.seo.duplicate_min_pages")
    )
    if not hit:
        return ok(description_duplicate.spec)
    value, pages, groups = hit
    return finding(
        description_duplicate.spec,
        ctx,
        evidence={
            "description": value,
            "page_count": len(pages),
            "path_groups": len(groups),
            "sample": snapshot.sample_source,  # a sample taken from links is less reliable
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# h1: level 2, because the raw HTML can be empty with the content coming from JS
# --------------------------------------------------------------------------- #
@check(
    "seo.h1.missing",
    level=2,
    category="seo",
    base_severity="high",
    requires=["browser"],
    description="Nacrtana stranica nema nijedan <h1>.",
    threshold="h1_count == 0 posle učitavanja u browseru",
)
def h1_missing(snapshot, ctx: Context):
    if snapshot.dom.h1_count > 0:
        return ok(h1_missing.spec)
    if snapshot.timing.reached == "timeout":
        return unknown(h1_missing.spec, "h1_timeout")
    return finding(
        h1_missing.spec,
        ctx,
        evidence={"h1_count": snapshot.dom.h1_count, "reached": snapshot.timing.reached},
        urls=[snapshot.url],
    )


@check(
    "seo.h1.multiple",
    level=2,
    category="seo",
    base_severity="low",
    requires=["browser"],
    description="Stranica ima previše <h1> naslova.",
    threshold="h1_count > thresholds.seo.h1_multiple (3)",
)
def h1_multiple(snapshot, ctx: Context):
    limit = ctx.th("thresholds.seo.h1_multiple")
    if snapshot.dom.h1_count <= limit:
        return ok(h1_multiple.spec)
    return finding(
        h1_multiple.spec,
        ctx,
        evidence={
            "h1_count": snapshot.dom.h1_count,
            "threshold": limit,
        },
        urls=[snapshot.url],
    )
