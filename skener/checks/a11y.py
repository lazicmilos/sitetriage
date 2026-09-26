"""Pristupačnost (§7.4).

U HTML-u postoje **tri** stanja, ne dva: nema `alt` atributa (greška), `alt=""`
(namerno, dekorativna slika, ispravno po WCAG-u) i `alt="tekst"` (ispravno).
Alat koji prijavljuje `alt=""` kao grešku prijavljuje korektno urađen sajt kao
pokvaren, i to pošalješ u mejlu (§15, zamka 1).
"""

from __future__ import annotations

from skener.checks.registry import Context, check, finding, ok, unknown

# Zakonska izloženost po pristupačnosti je veća, pa je prag ozbiljnosti niži.
IZLOZENE_DELATNOSTI = {"zdravstvo", "institucija"}


@check(
    "a11y.img.alt.missing",
    level=2,
    category="a11y",
    base_severity="low",
    requires=["browser"],
    description="Većina slika nema alt atribut (prazan alt se ne broji).",
    threshold=(
        "≥ 5 slika i udeo bez alt atributa > 0,5; > 0,8 uz ≥ 15 slika → high; "
        "zdravstvo/institucija → bar medium"
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

    severity = "medium" if ctx.industry in IZLOZENE_DELATNOSTI else "low"
    if ratio > ctx.th("thresholds.a11y.high_ratio") and dom.images_total >= ctx.th(
        "thresholds.a11y.high_min_images"
    ):
        severity = "high"

    return finding(
        img_alt_missing.spec,
        ctx,
        severity=severity,
        evidence={
            "bez_alta": dom.images_without_alt_attr,
            "ukupno": dom.images_total,
            "prazan_alt": dom.images_empty_alt,
            "udeo": round(ratio, 3),
            "nemereno": dom.images_unmeasured,
        },
        urls=[snapshot.url],
    )
