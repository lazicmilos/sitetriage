"""SEO provere (§5, §7.3)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from skener.checks.registry import CheckSpec, Context, check, finding, not_applicable, ok, unknown
from skener.fetch.urls import collapse_ws, normalize, path_group, same_site
from skener.models import CheckResult, PageSnapshot, SiteSnapshot


def _premalo_stranica(snapshot: SiteSnapshot, ctx: Context, spec: CheckSpec) -> CheckResult | None:
    """Uzorak ima manje stranica nego što poređenje traži: `unknown` ili `not_applicable` (Z-21).

    `not_applicable` samo kad sajt stvarno nema više stranica: budžet nije istekao, svi izvori
    zajedno (mapa sajta, veze sa početne, veze iz renderovanog DOM-a) vide manje adresa od praga,
    i bar jedan izvor vidi ono što crta JS. Inače `unknown`, a razlog kaže šta nije ispunjeno.
    """
    prag = ctx.th("thresholds.seo.duplicate_min_pages")
    if sum(1 for p in snapshot.pages if p.status == 200) >= prag:
        return None
    if snapshot.budget.exhausted:
        return unknown(spec, "pages_budget", prag=prag)
    if snapshot.scanner_version.startswith("1."):
        return unknown(spec, "v1_snapshot", verzija=snapshot.scanner_version, polje="home_links")

    home = snapshot.home
    base = home.final_url or home.url
    izvori = [snapshot.home_links]
    if snapshot.sitemap.status == 200 and not snapshot.sitemap.truncated:
        izvori.append(snapshot.sitemap.urls)
    b = ctx.browser
    nivo2 = b is not None and b.status != "failed" and b.dom.internal_links_total is not None
    if nivo2:
        izvori.append(b.dom.internal_links)
    # Početna je adresa sajta i kad nijedna veza ne vodi na nju.
    adrese = {normalize(base)} | {u for izvor in izvori for u in map(normalize, izvor) if same_site(u, base)}
    if len(adrese) >= prag:
        return unknown(spec, "pages_sample", prag=prag, adresa=len(adrese))
    prazan = home.text_length < ctx.th("escalation.empty_html_text_threshold") or not home.h1_count_raw
    if not nivo2 and prazan:
        return unknown(spec, "pages_js", prag=prag)
    return not_applicable(spec, "few_pages", prag=prag, adresa=len(adrese))


def _duplicates(
    snapshot: SiteSnapshot, value_of: Callable[[PageSnapshot], str | None], min_pages: int
) -> tuple[str, list[PageSnapshot], set[str]] | None:
    """Najveća grupa stranica sa identičnom vrednošću, ako prelazi prag.

    Traži se ≥ `min_pages` stranica iz ≥ `min_pages` **različitih** grupa putanja
    (§5). Zahtev za različitim grupama je ono što čuva U4: osam blog postova sa
    istim naslovom šablona nije isto što i ceo sajt koji se predstavlja kao jedna
    stranica.
    """
    buckets: dict[str, list[PageSnapshot]] = defaultdict(list)
    for page in snapshot.pages:
        if page.status != 200:
            continue
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
    requires=["home"],
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
        evidence={"stranica": home.final_url or home.url, "broj_canonical_oznaka": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.canonical.duplicate",
    level=1,
    category="seo",
    base_severity="critical",
    requires=["home"],
    description=(
        "Više stranica iz različitih delova sajta upućuje canonical-om na istu drugu adresu. "
        "Stranica koja upućuje na sebe se ne broji."
    ),
    threshold=(
        "≥ 2 stranice sa tuđim canonical-om ka istoj adresi, iz ≥ 2 grupe putanja; udeo u uzorku "
        "≥ 0,4 high · ≥ 0,6 critical · inače medium"
    ),
)
def canonical_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if malo := _premalo_stranica(snapshot, ctx, canonical_duplicate.spec):
        return malo

    def tudji(page: PageSnapshot) -> str | None:
        # Tuđi canonical: postoji i upućuje na drugu adresu od one na kojoj je stranica (Z-23).
        target = page.canonical_normalized
        return target if target and target != normalize(page.final_url or page.url) else None

    hit = _duplicates(snapshot, tudji, ctx.th("thresholds.seo.canonical_foreign_min"))
    if not hit:
        return ok(canonical_duplicate.spec)
    value, pages, groups = hit
    ukupno = sum(1 for p in snapshot.pages if p.status == 200)
    udeo = len(pages) / ukupno
    pragovi = ctx.th("thresholds.seo.canonical_share")
    return finding(
        canonical_duplicate.spec,
        ctx,
        evidence={
            "canonical": value,
            "stranica": len(pages),
            "ukupno": ukupno,
            "udeo": round(udeo, 4),
            "grupa_putanja": len(groups),
            "uzorak": snapshot.sample_source,  # uzorak iz linkova je manje pouzdan (§4.4)
        },
        urls=[p.final_url or p.url for p in pages],
        severity=next((s for s in ("critical", "high") if udeo >= pragovi[s]), "medium"),
    )


# --------------------------------------------------------------------------- #
# title
# --------------------------------------------------------------------------- #
@check(
    "seo.title.missing",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home"],
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
        evidence={"stranica": home.final_url or home.url, "duzina_naslova": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.title.duplicate",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home"],
    description="Više stranica iz različitih delova sajta ima identičan naslov.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim naslovom",
)
def title_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if malo := _premalo_stranica(snapshot, ctx, title_duplicate.spec):
        return malo
    hit = _duplicates(snapshot, lambda p: collapse_ws(p.title), ctx.th("thresholds.seo.duplicate_min_pages"))
    if not hit:
        return ok(title_duplicate.spec)
    value, pages, groups = hit
    return finding(
        title_duplicate.spec,
        ctx,
        evidence={
            "naslov": value,
            "stranica": len(pages),
            "grupa_putanja": len(groups),
            "uzorak": snapshot.sample_source,  # uzorak iz linkova je manje pouzdan (§4.4)
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
    requires=["home"],
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
        evidence={"stranica": home.final_url or home.url, "duzina_opisa": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.description.duplicate",
    level=1,
    category="seo",
    base_severity="medium",
    requires=["home"],
    description="Više stranica iz različitih delova sajta ima identičan meta opis.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim opisom",
)
def description_duplicate(snapshot: SiteSnapshot, ctx: Context):
    if malo := _premalo_stranica(snapshot, ctx, description_duplicate.spec):
        return malo
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
            "opis": value,
            "stranica": len(pages),
            "grupa_putanja": len(groups),
            "uzorak": snapshot.sample_source,  # uzorak iz linkova je manje pouzdan (§4.4)
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# h1 — nivo 2, jer sirovi HTML ume da bude prazan a sadržaj iz JS-a (§6)
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
            "prag": limit,
        },
        urls=[snapshot.url],
    )
