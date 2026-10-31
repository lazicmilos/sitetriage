"""Client and operator sentences, in Serbian and English (ADR-009).

A finding carries only its `check_id`, evidence and `variant`; the sentence is built at display
time, in the report language. That is why the same finding can be shown in both languages, and
`diff` compares evidence, not text.

A template is a plain `str.format`, with these additions:

- `{count:n:form|form|form}` gives the number and the noun in the right form ("3 kopije");
  Serbian has three forms, English two;
- `{items:join: → }` joins a list with the given separator;
- `{time:utc}` shortens a UTC time from the evidence to "2026-09-22 09:00"; the template
  writes the zone.

In the client sentence a decimal number is written by the rules of the language ("14,9" or
"14.9"); the technical sentence leaves it as it is. Technical codes from the evidence (sample
source, encoding) are read through the language's `CODES`.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from sitetriage.messages import en, sr

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
        raise ValueError(f"unknown language {lang!r}; supported: {', '.join(LANGS)}") from None


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
    """(client, technical) template; a variant overrides only what it names."""
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
    """A number for display, by the rules of the language: "99,4" or "99.4"."""
    return catalog(lang).DECIMAL(value)


def reason(r: Any, lang: str = "sr") -> str:
    """The reason for `unknown` or for escalation, from its code and data."""
    cat = catalog(lang)
    return _Formatter(cat, localize=True).format(cat.REASONS[r.code], **r.evidence)


def text(key: str, lang: str = "sr", **values: Any) -> str:
    """A report label or a part of the email draft."""
    cat = catalog(lang)
    return _Formatter(cat, localize=True).format(cat.TEXT[key], **values)
