"""Infrastrukturne provere (§5, §5.2)."""

from __future__ import annotations

from difflib import SequenceMatcher

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

SIMILARITY_CHARS = 2000
# Samo ovi statusi tvrde da nečega nema. 401, 403, 429 i 5xx znače da je pristup
# odbijen ili da server ne radi: tada ne znamo, pa je rezultat `unknown` (BUG-003).
NE_POSTOJI = frozenset({404, 410})


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
