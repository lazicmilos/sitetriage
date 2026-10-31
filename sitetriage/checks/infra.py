"""Infrastructure checks."""

from __future__ import annotations

from difflib import SequenceMatcher

from sitetriage.checks.registry import Context, check, finding, not_applicable, ok, unknown
from sitetriage.fetch.urls import host_of
from sitetriage.models import HostVariant, SiteSnapshot

SIMILARITY_CHARS = 2000
# Only these statuses claim that something does not exist. 401, 403, 429 and 5xx mean that access
# was refused or that the server is not working: then we do not know, so the result is `unknown`
# (BUG-003).
NOT_FOUND_STATUSES = frozenset({404, 410})
# A host variant we did not see the way a browser would: the certificate did not pass or the
# request was never sent. Whether it serves the site is not known (ADR-014). A DNS error and a
# connection without a response are not like that: they serve nothing.
# A temporary DNS error does not say the name does not exist, so whether it serves the site is not known.
UNCHECKED_KINDS = frozenset({"tls", "tls_handshake", "budget", "dns_temporary"})


@check(
    "infra.sitemap.missing",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["sitemap"],
    description="Nema sitemap.xml, ili postoji ali je prazan.",
    threshold=(
        "status 404 ili 410, ili 200 sa 0 URL-ova; ostali statusi i mapa veća od granice → unknown; "
        "ima URL-ova → ok"
    ),
)
def sitemap_missing(snapshot: SiteSnapshot, ctx: Context):
    info = snapshot.sitemap
    # `status` is the status of the first sitemap; a dead first `Sitemap:` next to a working second
    # one is not "no sitemap".
    if info.urls:
        return ok(sitemap_missing.spec)
    # No URLs, but truncated: the sitemap exists, it is just larger than the limit, so whether it is
    # empty is not known.
    if info.truncated:
        return unknown(sitemap_missing.spec, "sitemap_too_large")
    if info.status != 200 and info.status not in NOT_FOUND_STATUSES:
        return unknown(sitemap_missing.spec, "sitemap_status", status=info.status)
    return finding(
        sitemap_missing.spec,
        ctx,
        evidence={"status": info.status, "url_count": len(info.urls)},
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
    if status not in NOT_FOUND_STATUSES:
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
        refused = [s for s in statuses if s != 200 and s not in NOT_FOUND_STATUSES]
        if refused:
            return unknown(soft404.spec, "probe_status", statuses=refused)
        # One probe 200 and the other 404 → `ok`, not a finding: one probe can hit an existing URL by chance.
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
        "probe_count": len(probes),
        "similarity": round(similarity, 3),
        "hard_evidence": similarity >= ctx.th("thresholds.soft404.text_similarity"),
    }
    return finding(soft404.spec, ctx, evidence=evidence, urls=[p.url for p in probes])


@check(
    "infra.tls.invalid",
    level=1,
    category="infra",
    base_severity="high",
    requires=["entry"],
    description="Sertifikat je nevalidan ili istekao.",
    threshold=(
        "TLS provera odbila sertifikat; nepotpun lanac (nema međusertifikata) → unknown"
    ),
)
def tls_invalid(snapshot: SiteSnapshot, ctx: Context):
    entry = snapshot.entry
    tls = entry.tls
    if tls.valid:
        # A connection that was never established does not prove the certificate is valid.
        # `ok` here would be a claim we did not check.
        if entry.status is None:
            return unknown(tls_invalid.spec, "tls_no_connection", kind=entry.error_kind)
        # https failed, so the site was fetched over http: the certificate was never seen (BUG-004).
        https = next((e for e in snapshot.errors if e.stage == "entry"), None)
        if https is not None and entry.requested_url.startswith("http://"):
            return unknown(tls_invalid.spec, "tls_over_http", kind=https.kind, detail=https.detail[:120])
        return ok(tls_invalid.spec)
    # The server does not send the intermediate certificate: Python rejects it, but a browser can
    # fill it in by itself, so "the visitor sees a warning" is not proven.
    if "unable to get local issuer certificate" in (tls.error or ""):
        return unknown(tls_invalid.spec, "tls_incomplete_chain")
    return finding(
        tls_invalid.spec,
        ctx,
        evidence={"error": tls.error or "unknown", "valid": 0},
        urls=[snapshot.entry.requested_url],
    )


def _home_variant(snapshot: SiteSnapshot) -> HostVariant:
    """The final URL of the home page as a variant, to compare with the other three."""
    home = snapshot.home
    final = home.final_url or home.url
    canonical = home.canonical_normalized
    return HostVariant(url=final, status=home.status, final_url=final, canonical=canonical)


def _origin(url: str | None) -> str:
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
    home = _home_variant(snapshot)
    host = host_of(home.final_url)
    variants = {v.url: v for v in snapshot.host_variants}
    if not snapshot.entry.tls.valid:
        home.error_kind = "tls"
    scheme = home.final_url.split("://")[0]
    variants[f"{scheme}://{host}/"] = home
    https, http = variants.get(f"https://{host}/"), variants.get(f"http://{host}/")
    for url, variant in ((f"https://{host}/", https), (f"http://{host}/", http)):
        if variant is None or variant.error_kind in UNCHECKED_KINDS:
            kind = variant.error_kind if variant else "—"
            return unknown(spec, "variant_unchecked", url=url, kind=kind)
    if https.status != 200 or not (https.final_url or "").startswith("https://"):
        return not_applicable(spec, "no_https", url=https.url)
    if http.status == 200 and (http.final_url or "").startswith("http://"):
        evidence = {"http_url": http.url, "status": http.status, "https_url": https.url}
        return finding(spec, ctx, evidence=evidence, urls=[http.url])
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
    home = _home_variant(snapshot)
    bare = (host_of(home.final_url) or "").removeprefix("www.")
    # Only www and without www: http and https of the same host are reported by
    # `infra.https.redirect.missing`, and a URL that leads to a different domain is not a copy of the site.
    serving = [
        v
        for v in [home, *snapshot.host_variants]
        if v.status == 200 and host_of(v.final_url) in (bare, f"www.{bare}")
    ]
    hosts = {host_of(v.final_url) for v in serving}
    if len(hosts) < 2:
        for v in snapshot.host_variants:
            if v.error_kind in UNCHECKED_KINDS and host_of(v.url) not in hosts:
                return unknown(spec, "variant_unchecked", url=v.url, kind=v.error_kind)
        return ok(spec)
    canonical = {_origin(v.canonical) for v in serving}
    same = len(canonical) == 1 and "" not in canonical
    return finding(
        spec,
        ctx,
        evidence={
            # Hosts, not origins: with http without a redirect the list had four entries (BUG-017).
            "hosts": sorted(hosts),
            "host_count": len(hosts),
            "same_canonical": int(same),
        },
        urls=sorted({v.url for v in serving}),
        severity="low" if same else None,
        variant="same_canonical" if same else None,
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
        version = snapshot.scanner_version
        return unknown(unreachable.spec, "v1_snapshot", version=version, field="entry_attempts")
    cause = snapshot.entry_unreachable()
    attempts = snapshot.entry_attempts
    # A single attempt, a temporary DNS error, an interrupted TLS handshake or a block do not prove
    # that the site is down.
    if cause is None or len(attempts) < 2:
        return unknown(unreachable.spec, "unreachable_unsure", kind=entry.error_kind, attempts=len(attempts))
    return finding(
        unreachable.spec,
        ctx,
        evidence={
            "cause": cause,
            "attempt_count": len(attempts),
            "first_attempt": attempts[0],
            "second_attempt": attempts[-1],
            "detail": entry.error_detail or "",
        },
        urls=[entry.requested_url],
    )
