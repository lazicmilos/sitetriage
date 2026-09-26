"""Infrastrukturne provere (§5, §5.2)."""

from __future__ import annotations

from difflib import SequenceMatcher

from skener.checks.registry import Context, check, finding, not_applicable, ok, unknown
from skener.fetch.urls import host_of
from skener.models import HostVariant, SiteSnapshot

SIMILARITY_CHARS = 2000
# Samo ovi statusi tvrde da nečega nema. 401, 403, 429 i 5xx znače da je pristup
# odbijen ili da server ne radi: tada ne znamo, pa je rezultat `unknown` (BUG-003).
NE_POSTOJI = frozenset({404, 410})
# Varijanta hosta koju nismo videli kao pretraživač: sertifikat nije prošao ili zahtev nije ni
# poslat. Ne zna se da li služi sajt (Z-26). DNS greška i veza bez odgovora nisu takve: ništa ne služe.
NEPROVERENA = frozenset({"tls", "tls_handshake", "budget"})


@check(
    "infra.sitemap.missing",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["sitemap"],
    description="Nema sitemap.xml, ili postoji ali je prazan.",
    threshold="status 404 ili 410, ili 200 sa 0 URL-ova; ostali statusi → unknown",
)
def sitemap_missing(snapshot: SiteSnapshot, ctx: Context):
    info = snapshot.sitemap
    if info.status == 200 and info.urls:
        return ok(sitemap_missing.spec)
    if info.status != 200 and info.status not in NE_POSTOJI:
        return unknown(sitemap_missing.spec, "sitemap_status", status=info.status)
    return finding(
        sitemap_missing.spec,
        ctx,
        evidence={"status": info.status, "broj_urlova": len(info.urls)},
        urls=[info.url] if info.url else [],
    )


@check(
    "infra.robots.missing",
    level=1,
    category="infra",
    base_severity="low",
    requires=["robots"],
    description="Nema robots.txt.",
    threshold="status 404 ili 410; ostali statusi osim 200 → unknown",
)
def robots_missing(snapshot: SiteSnapshot, ctx: Context):
    status = snapshot.robots.status
    if status == 200:
        return ok(robots_missing.spec)
    if status not in NE_POSTOJI:
        return unknown(robots_missing.spec, "robots_status", status=status)
    return finding(
        robots_missing.spec,
        ctx,
        evidence={"status": snapshot.robots.status},
    )


@check(
    "infra.soft404",
    level=1,
    category="infra",
    base_severity="high",
    requires=["soft404"],
    description="Nepostojeća adresa vraća 200 umesto 404.",
    threshold="obe sonde vraćaju konačni status 200 (§5.2); status van {200, 404, 410} → unknown",
)
def soft404(snapshot: SiteSnapshot, ctx: Context):
    probes = snapshot.soft404.probes
    statuses = [p.status for p in probes]
    if not all(s == 200 for s in statuses):
        odbijene = [s for s in statuses if s != 200 and s not in NE_POSTOJI]
        if odbijene:
            return unknown(soft404.spec, "probe_status", statusi=odbijene)
        # Jedna sonda 200 a druga 404 → `ok`, ne nalaz (§5.2).
        return ok(soft404.spec)

    home = snapshot.home
    similarity = 0.0
    if home and home.text_sample:
        similarity = max(
            SequenceMatcher(
                None, home.text_sample[:SIMILARITY_CHARS], p.text_sample[:SIMILARITY_CHARS]
            ).ratio()
            for p in probes
        )
    evidence = {
        "status": 200,
        "broj_sondi": len(probes),
        "slicnost": round(similarity, 3),
        "tvrd_dokaz": similarity >= ctx.th("thresholds.soft404.text_similarity"),
    }
    return finding(soft404.spec, ctx, evidence=evidence, urls=[p.url for p in probes])


@check(
    "infra.tls.invalid",
    level=1,
    category="infra",
    base_severity="high",
    requires=["entry"],
    description="Sertifikat je nevalidan ili istekao.",
    threshold="TLS provera odbila sertifikat",
)
def tls_invalid(snapshot: SiteSnapshot, ctx: Context):
    entry = snapshot.entry
    tls = entry.tls
    if tls.valid:
        # Veza koja nije ni uspostavljena ne dokazuje da je sertifikat ispravan.
        # `ok` bi ovde bio tvrdnja koju nismo proverili (§3.4).
        if entry.status is None:
            return unknown(tls_invalid.spec, "tls_no_connection", vrsta=entry.error_kind)
        # Https nije uspeo, pa je sajt dohvaćen preko http-a: sertifikat nije ni viđen (BUG-004).
        https = next((e for e in snapshot.errors if e.stage == "entry"), None)
        if https is not None and entry.requested_url.startswith("http://"):
            return unknown(tls_invalid.spec, "tls_over_http", vrsta=https.kind, detalj=https.detail[:120])
        return ok(tls_invalid.spec)
    return finding(
        tls_invalid.spec,
        ctx,
        evidence={"greska": tls.error or "nepoznata", "valid": 0},
        urls=[snapshot.entry.requested_url],
    )


def _pocetna(snapshot: SiteSnapshot) -> HostVariant:
    """Konačna adresa početne u obliku varijante, da se poredi sa ostalim trima."""
    home = snapshot.home
    konacna = home.final_url or home.url
    canonical = home.canonical_normalized
    return HostVariant(url=konacna, status=home.status, final_url=konacna, canonical=canonical)


def _poreklo(url: str | None) -> str:
    return f"{url.split('://')[0]}://{host_of(url)}" if url and host_of(url) else ""


@check(
    "infra.https.redirect.missing",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["home", "host_variants"],
    description="Sajt radi na https-u, ali se otvara i preko http-a, bez preusmerenja na https.",
    threshold=(
        "https na konačnom hostu vraća 200 sa ispravnim sertifikatom, a http:// istog hosta vraća 200 bez "
        "preusmerenja na https; TLS greška ili neposlat zahtev → unknown; https ne radi → ne primenjuje se"
    ),
)
def https_redirect_missing(snapshot: SiteSnapshot, ctx: Context):
    spec = https_redirect_missing.spec
    pocetna = _pocetna(snapshot)
    host = host_of(pocetna.final_url)
    adrese = {v.url: v for v in snapshot.host_variants}
    if not snapshot.entry.tls.valid:
        pocetna.error_kind = "tls"
    sema = pocetna.final_url.split("://")[0]
    adrese[f"{sema}://{host}/"] = pocetna
    https, http = adrese.get(f"https://{host}/"), adrese.get(f"http://{host}/")
    for url, varijanta in ((f"https://{host}/", https), (f"http://{host}/", http)):
        if varijanta is None or varijanta.error_kind in NEPROVERENA:
            vrsta = varijanta.error_kind if varijanta else "—"
            return unknown(spec, "variant_unchecked", adresa=url, vrsta=vrsta)
    if https.status != 200 or not (https.final_url or "").startswith("https://"):
        return not_applicable(spec, "no_https", adresa=https.url)
    if http.status == 200 and (http.final_url or "").startswith("http://"):
        dokaz = {"http_adresa": http.url, "status": http.status, "https_adresa": https.url}
        return finding(spec, ctx, evidence=dokaz, urls=[http.url])
    return ok(spec)


@check(
    "infra.host.duplicate",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["home", "host_variants"],
    description="Isti sajt se otvara i sa www i bez www, a nijedna adresa ne preusmerava na drugu.",
    threshold=(
        "varijante vraćaju 200 na oba hosta (www i bez www); low ako canonical na svima upućuje na isto "
        "poreklo; neproverena varijanta hosta koji nije viđen → unknown"
    ),
)
def host_duplicate(snapshot: SiteSnapshot, ctx: Context):
    spec = host_duplicate.spec
    pocetna = _pocetna(snapshot)
    bez = (host_of(pocetna.final_url) or "").removeprefix("www.")
    # Samo www i bez www: http i https istog hosta prijavljuje `infra.https.redirect.missing`, a
    # adresa koja vodi na tuđ domen nije kopija sajta.
    sluze = [
        v
        for v in [pocetna, *snapshot.host_variants]
        if v.status == 200 and host_of(v.final_url) in (bez, f"www.{bez}")
    ]
    hostovi = {host_of(v.final_url) for v in sluze}
    if len(hostovi) < 2:
        for v in snapshot.host_variants:
            if v.error_kind in NEPROVERENA and host_of(v.url) not in hostovi:
                return unknown(spec, "variant_unchecked", adresa=v.url, vrsta=v.error_kind)
        return ok(spec)
    canonical = {_poreklo(v.canonical) for v in sluze}
    isti = len(canonical) == 1 and "" not in canonical
    return finding(
        spec,
        ctx,
        evidence={
            "adrese": sorted({_poreklo(v.final_url) for v in sluze}),
            "broj_adresa": len(hostovi),
            "isti_canonical": int(isti),
        },
        urls=sorted({v.url for v in sluze}),
        severity="low" if isti else None,
        variant="isti_canonical" if isti else None,
    )


@check(
    "infra.unreachable",
    level=1,
    category="infra",
    base_severity="critical",
    requires=["entry"],
    description=(
        "Sajt se ne otvara ni u drugom pokušaju: ime ne postoji u DNS-u ili nema adresu, ili server "
        "ne prihvata vezu ni preko https ni preko http. Domen ide u listu „Ne rade”, a ne u rangiranje."
    ),
    threshold=(
        "oba pokušaja, u razmaku od bar http.second_attempt_after_s (60 s): EAI_NONAME ili EAI_NODATA, "
        "ili TCP veza odbijena ili istekla i na https i na http; bilo kakav HTTP odgovor → ok"
    ),
)
def unreachable(snapshot: SiteSnapshot, ctx: Context):
    entry = snapshot.entry
    if entry.status is not None:
        return ok(unreachable.spec)
    if snapshot.scanner_version.startswith("1."):
        verzija = snapshot.scanner_version
        return unknown(unreachable.spec, "v1_snapshot", verzija=verzija, polje="entry_attempts")
    razlog = snapshot.entry_unreachable()
    pokusaji = snapshot.entry_attempts
    # Jedan pokušaj, privremen DNS, prekinuto TLS rukovanje ili blokada ne dokazuju da sajt ne radi.
    if razlog is None or len(pokusaji) < 2:
        return unknown(unreachable.spec, "unreachable_unsure", vrsta=entry.error_kind, pokusaja=len(pokusaji))
    return finding(
        unreachable.spec,
        ctx,
        evidence={
            "razlog": razlog,
            "broj_pokusaja": len(pokusaji),
            "prvi_pokusaj": pokusaji[0],
            "drugi_pokusaj": pokusaji[-1],
            "detalj": entry.error_detail or "",
        },
        urls=[entry.requested_url],
    )
