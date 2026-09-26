"""Šeme podataka (§3) i serijalizacija bez gubitka.

Modul je čist: bez mreže, bez diska. Sve šeme su `dataclass`-ovi, a `to_jsonable`
i `from_dict` rade generički nad anotacijama tipova, pa dodavanje polja u šemu ne
traži ručno pisanje (de)serijalizacije.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Literal

from skener import __version__

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["seo", "social", "i18n", "infra", "perf", "a11y", "qa"]
# `not_applicable`: provera nema šta da proveri na ovom sajtu (Z-21); razlog je obavezan.
CheckStatus = Literal["ok", "finding", "unknown", "not_applicable"]
Industry = Literal[
    "hotel", "restoran", "zdravstvo", "ecommerce", "b2b", "institucija", "ostalo"
]
# `unreachable`: sajt se ne otvara ni posle drugog pokušaja, pa ide u listu „Ne rade" (Z-20).
# `excluded`: administrator je tražio da se sajt ne skenira; u izveštaju je samo njihov broj.
DomainStatus = Literal["scanned", "partial", "failed", "unreachable", "excluded"]

# JSON izveštaj: dodato polje podiže drugi broj, a obrisano ili promenjeno prvi (README).
SCHEMA_VERSION = "2.0"
SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
INDUSTRIES: tuple[str, ...] = typing.get_args(Industry)
CATEGORIES: tuple[str, ...] = typing.get_args(Category)


# --------------------------------------------------------------------------- #
# Generička (de)serijalizacija
# --------------------------------------------------------------------------- #
def to_jsonable(obj: Any) -> Any:
    """Pretvara dataclass stablo u strukturu koju `json.dump` ume da zapiše."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def _coerce(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        for arg in args:
            if dataclasses.is_dataclass(arg) and isinstance(value, dict):
                return from_dict(arg, value)
        return _coerce(args[0], value) if len(args) == 1 else value
    if origin in (list, tuple):
        args = typing.get_args(tp)
        item_tp = args[0] if args else Any
        return [_coerce(item_tp, v) for v in value]
    if origin is dict:
        args = typing.get_args(tp)
        val_tp = args[1] if len(args) == 2 else Any
        return {k: _coerce(val_tp, v) for k, v in value.items()}
    if origin is Literal:
        return value
    if dataclasses.is_dataclass(tp) and isinstance(value, dict):
        return from_dict(tp, value)
    return value


def from_dict(cls: Any, data: dict[str, Any]) -> Any:
    """Rekonstruiše dataclass iz rečnika; nepoznata polja se ignorišu."""
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _coerce(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)


# --------------------------------------------------------------------------- #
# Nivo 1 — SiteSnapshot (§3.1, §3.2)
# --------------------------------------------------------------------------- #
@dataclass
class Tls:
    valid: bool = True
    error: str | None = None


@dataclass
class Entry:
    """Dohvatanje početne strane: ono što se zna i kad stranica nije stigla."""

    requested_url: str
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    status: int | None = None
    elapsed_ms: int | None = None
    tls: Tls = field(default_factory=Tls)
    error_kind: str | None = None
    error_detail: str | None = None


@dataclass
class RobotsInfo:
    status: int | None = None
    body: str | None = None
    disallow: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SitemapInfo:
    status: int | None = None
    url: str | None = None
    urls: list[str] = field(default_factory=list)
    nested_count: int = 0
    depth_reached: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass
class OpenGraph:
    title: str | None = None
    description: str | None = None
    image: str | None = None
    url: str | None = None


@dataclass
class PageSnapshot:
    url: str
    final_url: str | None = None
    status: int | None = None
    redirect_hops: int = 0
    elapsed_ms: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    html_bytes: int = 0
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    canonical_normalized: str | None = None
    og: OpenGraph = field(default_factory=OpenGraph)
    lang: str | None = None
    hreflang: list[str] = field(default_factory=list)
    h1_count_raw: int = 0
    text_sample: str = ""
    text_length: int = 0
    raw_html: str | None = None  # samo za početnu stranu (§3.2)
    error_kind: str | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200


@dataclass
class Soft404Probe:
    url: str
    status: int | None = None
    final_url: str | None = None
    text_sample: str = ""
    error: str | None = None


@dataclass
class Soft404:
    probes: list[Soft404Probe] = field(default_factory=list)


@dataclass
class SnapshotError:
    stage: str
    kind: str
    detail: str


@dataclass
class Budget:
    """Potrošnja tvrdog budžeta po domenu (§4.2)."""

    max_requests: int = 0
    requests_made: int = 0
    elapsed_ms: int = 0
    exhausted: bool = False
    aborted_reason: str | None = None


@dataclass
class SiteSnapshot:
    domain: str
    industry: str = "ostalo"
    fetched_at: str = ""
    scanner_version: str = __version__
    entry: Entry | None = None
    robots: RobotsInfo = field(default_factory=RobotsInfo)
    sitemap: SitemapInfo = field(default_factory=SitemapInfo)
    pages: list[PageSnapshot] = field(default_factory=list)
    soft404: Soft404 = field(default_factory=Soft404)
    sample_source: Literal["sitemap", "links", "none"] = "none"
    budget: Budget = field(default_factory=Budget)
    errors: list[SnapshotError] = field(default_factory=list)
    # Kad je ulaz pokušan, u UTC-u. Drugi pokušaj postoji samo kad je prvi izgledao kao da sajt
    # ne radi (Z-20); snapshot je tada iz drugog.
    entry_attempts: list[str] = field(default_factory=list)
    # Interne veze iz sirovog HTML-a početne (do 200); provera duplikata broji adrese sajta (Z-21).
    home_links: list[str] = field(default_factory=list)

    @property
    def home(self) -> PageSnapshot | None:
        """Početna strana je po konstrukciji prva u uzorku."""
        return self.pages[0] if self.pages else None

    def entry_unreachable(self) -> str | None:
        """`dns` ili `no_response` kad ovaj pokušaj ulaza pokazuje da sajt ne radi, inače `None`.

        Sigurno je samo ovo: ime ne postoji u DNS-u ili nema adresu, ili TCP veza nije
        uspostavljena ni na https ni na http. Privremen DNS, prekinuto TLS rukovanje, bilo kakav
        HTTP odgovor i blokada privatne adrese to nisu, jer sajt možda radi, samo ga mi nismo
        videli (Z-20).
        """
        entry = self.entry
        if entry is None or entry.status is not None:
            return None
        if entry.error_kind in ("dns_nxdomain", "dns_nodata"):
            return "dns"
        sheme = [e.kind for e in self.errors if e.stage == "entry"]
        return "no_response" if sheme == ["no_connection", "no_connection"] else None


# --------------------------------------------------------------------------- #
# Nivo 2 — BrowserSnapshot (§3.3)
# --------------------------------------------------------------------------- #
@dataclass
class NetworkStats:
    """Mrežni saobraćaj početne. Prag i rečenica za klijenta gledaju samo zahteve započete
    pre `load` glavnog dokumenta (Z-24); ukupne vrednosti su informativne.
    """

    request_count: int = 0
    total_bytes: int = 0
    bytes_by_type: dict[str, int] = field(default_factory=dict)
    unmeasured_responses: int = 0
    requests_at_load: int = 0
    bytes_at_load: int = 0
    bytes_by_type_at_load: dict[str, int] = field(default_factory=dict)
    unmeasured_at_load: int = 0


@dataclass
class TimingStats:
    dom_content_loaded_ms: int | None = None
    load_ms: int | None = None
    reached: Literal["load", "domcontentloaded", "timeout", "error"] = "error"


@dataclass
class OversizedImage:
    src: str
    natural: list[int] = field(default_factory=list)
    client: list[int] = field(default_factory=list)
    ratio: float = 0.0
    est_waste_kb: float = 0.0


@dataclass
class DomStats:
    h1_count: int = 0
    images_total: int = 0
    images_without_alt_attr: int = 0
    images_empty_alt: int = 0
    oversized_images: list[OversizedImage] = field(default_factory=list)
    images_unmeasured: int = 0
    # Interne veze iz renderovanog DOM-a (do 200) i koliko ih ima; `None` = nisu beležene (1.x).
    internal_links: list[str] = field(default_factory=list)
    internal_links_total: int | None = None
    # Stranica kakvu čita čitač ekrana (Z-25): `lang` i vidljiv tekst posle JS-a, do 4000 znakova.
    # `text_length` je `None` kad nisu beleženi (1.x).
    lang: str | None = None
    text_sample: str = ""
    text_length: int | None = None


@dataclass
class ConsoleStats:
    errors: int = 0
    warnings: int = 0
    samples: list[str] = field(default_factory=list)


@dataclass
class BrowserSnapshot:
    domain: str
    url: str = ""
    fetched_at: str = ""
    scanner_version: str = __version__
    browser_version: str = ""
    status: Literal["ok", "partial", "failed"] = "failed"
    network: NetworkStats = field(default_factory=NetworkStats)
    timing: TimingStats = field(default_factory=TimingStats)
    dom: DomStats = field(default_factory=DomStats)
    console: ConsoleStats = field(default_factory=ConsoleStats)
    errors: list[SnapshotError] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Rezultati provera (§3.4, §3.5, §3.6)
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    domain: str
    check_id: str
    level: int
    category: str
    severity: str
    # Samo podaci: brojevi, logičke vrednosti, URL-ovi, tehnički kodovi, sirove greške i
    # tekst sa sajta. Rečenicu pravi `skener.messages` pri prikazu, na jeziku izveštaja.
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_urls: list[str] = field(default_factory=list)
    weight: float = 0.0
    # Kad provera ima više oblika rečenice, npr. težina sa videom i bez njega.
    variant: str | None = None


@dataclass
class Reason:
    """Zašto nešto nije provereno ili zašto domen ide na nivo 2: kod i podaci, bez rečenice.

    Rečenicu pravi `skener.messages.reason` na jeziku izveštaja, isto kao za nalaz.
    """

    code: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    check_id: str
    status: CheckStatus
    reason: Reason | None = None
    findings: list[Finding] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status in ("unknown", "not_applicable") and not self.reason:
            raise ValueError(f"{self.check_id}: `{self.status}` bez `reason` je bug (§3.4)")
        if self.status != "finding" and self.findings:
            raise ValueError(f"{self.check_id}: nalazi postoje a status nije `finding`")
        if self.status == "finding" and not self.findings:
            raise ValueError(f"{self.check_id}: status `finding` bez ijednog nalaza")


@dataclass
class Unknown:
    check_id: str
    reason: Reason


@dataclass
class DomainReport:
    domain: str
    industry: str = "ostalo"
    final_url: str | None = None
    status: DomainStatus = "scanned"
    # Zašto je `partial`: `budget`, `unknown` ili oba (Z-22). Prazno za ostale statuse.
    partial_causes: list[Literal["budget", "unknown"]] = field(default_factory=list)
    level2_ran: bool = False
    escalation_reasons: list[Reason] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    # Isti oblik kao `unknowns`, ali ne pravi `partial`: provera nema šta da proveri (Z-21).
    not_applicable: list[Unknown] = field(default_factory=list)
    total_score: float = 0.0
    max_finding_weight: float = 0.0
    rank: int = 0  # 0 = nije rangiran (`unreachable`, `failed`)
    scanned_at: str = ""
    # Zašto je `failed`, za listu „Nije skenirano". Za `unreachable` razlog je nalaz `infra.unreachable`.
    reason: Reason | None = None

    @property
    def rank_key(self) -> tuple[float, float]:
        """§9.4: prvo najteži pojedinačni nalaz, pa tek onda zbir."""
        return (self.max_finding_weight, self.total_score)

    @property
    def top_findings(self) -> list[Finding]:
        """Tri nalaza koja staju u mejl (§9.4)."""
        return self.findings[:3]


# --------------------------------------------------------------------------- #
# Prolaz kao celina: rezultat i događaji napretka (skener.pipeline)
# --------------------------------------------------------------------------- #
@dataclass
class Event:
    """Napredak prolaza. Web worker iz njega pravi traku napretka, a CLI ga loguje."""

    kind: Literal["phase_started", "phase_finished", "domain_finished"]
    phase: Literal["level1", "level2", "recheck"]
    total: int
    done: int = 0
    domain: str | None = None
    status: str | None = None


@dataclass
class ScanResult:
    """Ceo prolaz: metapodaci, zbir po statusu i rangirani izveštaji.

    Serijalizovan je to JSON izveštaj, pa redosled polja određuje i redosled ključeva, a
    šema je u `skener/schema/report-2.json`.
    """

    schema_version: str = SCHEMA_VERSION
    scanner_version: str = __version__
    started_at: str = ""
    finished_at: str = ""
    duration_s: dict[str, float] = field(default_factory=dict)
    # sha256 konfiguracije koja utiče na rezultat; isti otisak = isti pragovi
    config_digest: str = ""
    environment: dict[str, str | None] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    # Izlazni kriterijumi (§7, Z-22): udeo domena koji rade sa potrošenim budžetom, i za svaku
    # proveru udeo `unknown`-a među domenima koji rade i na kojima je pokrenuta.
    budget_share: float = 0.0
    unknown_share: dict[str, float] = field(default_factory=dict)
    ranked: list[DomainReport] = field(default_factory=list)
    unreachable: list[DomainReport] = field(default_factory=list)
    not_scanned: list[DomainReport] = field(default_factory=list)  # `failed`; izuzeti su samo broj


# --------------------------------------------------------------------------- #
# Ulazni red iz domains.csv (§4.1)
# --------------------------------------------------------------------------- #
@dataclass
class DomainInput:
    domain: str
    industry: str = "ostalo"
    note: str = ""
