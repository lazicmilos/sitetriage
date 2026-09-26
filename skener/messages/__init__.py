"""Rečenice za klijenta i operatera, na srpskom i engleskom.

Nalaz nosi samo `check_id`, dokaz i `variant`, a rečenica se pravi tek pri prikazu, na
jeziku izveštaja. Zato isti nalaz može da se prikaže na oba jezika, a `diff` poredi dokaz,
ne tekst.

Šablon je običan `str.format`, uz dva dodatka:

- `{broj:n:oblik|oblik|oblik}` daje broj i imenicu u pravilnom obliku („3 kopije");
  srpski ima tri oblika, engleski dva;
- `{lista:join: → }` spaja listu datim razdvajačem;
- `{vreme:utc}` skraćuje UTC vreme iz dokaza na „2026-09-22 09:00"; zonu piše šablon.

U rečenici za klijenta decimalni broj se piše po pravilima jezika („14,9" ili „14.9"), a
tehnička rečenica ga ostavlja kakav jeste. Tehnički kodovi iz dokaza (izvor uzorka,
kodiranje) čitaju se kroz `CODES` jezika.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from skener.messages import en, sr

LANGS: tuple[str, ...] = ("sr", "en")
_CATALOGS: dict[str, ModuleType] = {"sr": sr, "en": en}


@dataclass(frozen=True)
class Message:
    client: str
    tech: str


def catalog(lang: str) -> ModuleType:
    try:
        return _CATALOGS[lang]
    except KeyError:
        raise ValueError(f"nepoznat jezik {lang!r}; podržani su {', '.join(LANGS)}") from None


class _Formatter(string.Formatter):
    def __init__(self, cat: ModuleType, *, localize: bool) -> None:
        self.cat = cat
        self.localize = localize

    def get_value(self, key: Any, args: Any, kwargs: dict[str, Any]) -> Any:
        value = super().get_value(key, args, kwargs)
        codes = self.cat.CODES.get(key)
        return codes.get(value, value) if codes else value

    def format_field(self, value: Any, format_spec: str) -> str:
        if format_spec.startswith("n:"):
            return f"{value} {self.cat.plural(value, format_spec[2:].split('|'))}"
        if format_spec.startswith("join:"):
            return format_spec[5:].join(str(item) for item in value)
        if format_spec == "utc":
            return value[:16].replace("T", " ")
        if self.localize and isinstance(value, float) and not format_spec:
            return self.cat.DECIMAL(value)
        return super().format_field(value, format_spec)


def templates(check_id: str, lang: str, variant: str | None = None) -> tuple[str, str]:
    """(klijentski, tehnički) šablon; varijanta menja samo ono što navodi."""
    entry = catalog(lang).FINDINGS[check_id]
    override = entry["variants"][variant] if variant else {}
    return override.get("client", entry["client"]), override.get("tech", entry["tech"])


def render(finding: Any, lang: str = "sr") -> Message:
    client, tech = templates(finding.check_id, lang, finding.variant)
    cat = catalog(lang)
    return Message(
        client=_Formatter(cat, localize=True).format(client, **finding.evidence),
        tech=_Formatter(cat, localize=False).format(tech, **finding.evidence),
    )


def number(value: float, lang: str = "sr") -> str:
    """Broj za prikaz, po pravilima jezika: „99,4" ili „99.4" (Z-28)."""
    return catalog(lang).DECIMAL(value)


def reason(r: Any, lang: str = "sr") -> str:
    """Razlog za `unknown` ili za eskalaciju, iz koda i podataka."""
    cat = catalog(lang)
    return _Formatter(cat, localize=True).format(cat.REASONS[r.code], **r.evidence)


def text(key: str, lang: str = "sr", **values: Any) -> str:
    """Oznaka iz izveštaja ili deo nacrta mejla."""
    cat = catalog(lang)
    return _Formatter(cat, localize=True).format(cat.TEXT[key], **values)
