"""Data schemas and lossless serialization.

The module is pure: no network, no disk. Every schema is a `dataclass`, and `to_jsonable`
and `from_dict` work generically over the type annotations, so adding a field to a schema
needs no hand-written (de)serialization.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Literal

from sitetriage import __version__

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["seo", "social", "i18n", "infra", "perf", "a11y", "qa"]
# `not_applicable`: the check has nothing to check on this site; a reason is required (ADR-015).
CheckStatus = Literal["ok", "finding", "unknown", "not_applicable"]
Industry = Literal[
    "hotel", "restaurant", "healthcare", "ecommerce", "b2b", "institution", "other"
]
# `unreachable`: the site does not open even after a second attempt, so it goes to the
# "unreachable" list (ADR-013).
# `excluded`: the administrator asked for the site not to be scanned; the report shows only
# how many there are.
DomainStatus = Literal["scanned", "partial", "failed", "unreachable", "excluded"]

# JSON report: an added field raises the minor number, a removed or changed one the major (ADR-011).
SCHEMA_VERSION = "3.0"
SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
INDUSTRIES: tuple[str, ...] = typing.get_args(Industry)
CATEGORIES: tuple[str, ...] = typing.get_args(Category)
# Content languages that `i18n.lang.mismatch` has a detector for (`sitetriage/checks/i18n.py`). A
# profile turns them on through `thresholds.i18n.content_languages` (ADR-023).
CONTENT_LANGUAGES: tuple[str, ...] = ("sr",)
# Languages of sentences and reports (`report.lang`, `--lang`); each has a catalog in
# `sitetriage/messages/`.
REPORT_LANGUAGES: tuple[str, ...] = ("en", "sr")


# --------------------------------------------------------------------------- #
# Generic (de)serialization
# --------------------------------------------------------------------------- #
def to_jsonable(obj: Any) -> Any:
    """Turns a dataclass tree into a structure that `json.dump` can write."""
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
    """Rebuilds a dataclass from a dict; unknown fields are ignored."""
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _coerce(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)


# --------------------------------------------------------------------------- #
# Level 1: SiteSnapshot
# --------------------------------------------------------------------------- #
@dataclass
class Tls:
    valid: bool = True
    error: str | None = None


@dataclass
class Entry:
    """The fetch of the home page: what is known even when the page did not arrive."""

    requested_url: str
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    status: int | None = None
    elapsed_ms: int | None = None
    tls: Tls = field(default_factory=Tls)
    error_kind: str | None = None
    error_detail: str | None = None


@dataclass
class HostVariant:
    """One of the other three URLs of the final origin (http/https × www/without www), ADR-014."""

    url: str
    status: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    canonical: str | None = None
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
    # Body longer than `http.max_body_kb`: only the start was read, so `html_bytes` is a lower bound,
    # and a check that reads the whole HTML does not know what comes after the limit.
    truncated: bool = False
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
    raw_html: str | None = None  # home page only; otherwise snapshots grow
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
    """Use of the hard per-domain budget (requests and seconds from `[http]`)."""

    max_requests: int = 0
    requests_made: int = 0
    elapsed_ms: int = 0
    exhausted: bool = False
    aborted_reason: str | None = None


@dataclass
class SiteSnapshot:
    domain: str
    industry: str = "other"
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
    # When the entry was attempted, in UTC. A second attempt exists only when the first looked
    # like the site is unreachable (ADR-013); the snapshot then comes from the second.
    entry_attempts: list[str] = field(default_factory=list)
    # Internal links from the raw HTML of the home page (up to 200); the duplicate checks count
    # the site's URLs (ADR-015).
    home_links: list[str] = field(default_factory=list)
    # `None` = not fetched: a snapshot from before host canonicalization (ADR-014), an entry with
    # an IP address or a port, or the home page did not arrive.
    host_variants: list[HostVariant] | None = None

    @property
    def home(self) -> PageSnapshot | None:
        """The home page is first in the sample by construction."""
        return self.pages[0] if self.pages else None

    def entry_unreachable(self) -> str | None:
        """`dns` or `no_response` when this entry attempt shows the site is unreachable, else `None`.

        Only this is certain: the name does not exist in DNS or has no address, or no TCP
        connection was established over either https or http. A temporary DNS failure, a broken
        TLS handshake, any HTTP response and a blocked private address are not, because the site
        may be working and we just did not see it (ADR-013).
        """
        entry = self.entry
        if entry is None or entry.status is not None:
            return None
        if entry.error_kind in ("dns_nxdomain", "dns_nodata"):
            return "dns"
        schemes = [e.kind for e in self.errors if e.stage == "entry"]
        return "no_response" if schemes == ["no_connection", "no_connection"] else None


# --------------------------------------------------------------------------- #
# Level 2: BrowserSnapshot
# --------------------------------------------------------------------------- #
@dataclass
class NetworkStats:
    """Network traffic of the home page. The threshold and the client sentence look only at
    requests started before the main document's `load` (ADR-016); the totals are informative.
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
    # Internal links from the rendered DOM (up to 200) and how many there are; `None` = not recorded (1.x).
    internal_links: list[str] = field(default_factory=list)
    internal_links_total: int | None = None
    # The page as a screen reader reads it (ADR-017): `lang` and the visible text after JS, up to
    # 4000 characters. `text_length` is `None` when they were not recorded (1.x).
    lang: str | None = None
    text_sample: str = ""
    text_length: int | None = None
    # `<head>` after JS; level 1 reads these from the raw HTML. Recorded only, for now: to see how
    # many sites set them with JavaScript, which would make seo.*.missing false. `None` = not
    # recorded, "" = absent.
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None


@dataclass
class ConsoleStats:
    errors: int = 0
    warnings: int = 0
    samples: list[str] = field(default_factory=list)


@dataclass
class NetworkProfile:
    """The simulated connection level 2 measures under (ADR-010): the same number on every machine."""

    download_mbps: float
    upload_mbps: float
    latency_ms: float


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
    # `None`: a snapshot from before the network profile (ADR-010), measured on the real connection
    network_profile: NetworkProfile | None = None
    # The real connection measured before level 2, in Mb/s (ADR-018); `None`: the measurement
    # failed or was not done
    link_mbps: float | None = None
    # Level 2 duration without waiting in the loading queue, the same as the hard limit measures
    # (ADR-020); `None`: a snapshot from before this field was recorded
    elapsed_ms: int | None = None
    # A site beyond `max_level2`: measured without the profile and without the loading queue, so
    # load time was not measured (BUG-020)
    light: bool = False


# --------------------------------------------------------------------------- #
# Check results
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    domain: str
    check_id: str
    level: int
    category: str
    severity: str
    # Data only: numbers, booleans, URLs, technical codes, raw errors and text from the site.
    # `sitetriage.messages` builds the sentence at display time, in the report language (ADR-009).
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_urls: list[str] = field(default_factory=list)
    weight: float = 0.0
    # When a check has several forms of the sentence, e.g. page weight with video and without.
    variant: str | None = None


@dataclass
class Reason:
    """Why something was not checked or why a domain goes to level 2: a code and data, no sentence.

    `sitetriage.messages.reason` builds the sentence in the report language, as for a finding.
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
            raise ValueError(f"{self.check_id}: `{self.status}` without a `reason` is a bug")
        if self.status != "finding" and self.findings:
            raise ValueError(f"{self.check_id}: there are findings but the status is not `finding`")
        if self.status == "finding" and not self.findings:
            raise ValueError(f"{self.check_id}: status `finding` without a single finding")


@dataclass
class Unknown:
    check_id: str
    reason: Reason


@dataclass
class DomainReport:
    domain: str
    industry: str = "other"
    final_url: str | None = None
    status: DomainStatus = "scanned"
    # Why it is `partial`: `budget`, `unknown` or both (ADR-015). Empty for the other statuses.
    partial_causes: list[Literal["budget", "unknown"]] = field(default_factory=list)
    level2_ran: bool = False
    escalation_reasons: list[Reason] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    # Same shape as `unknowns`, but does not make the domain `partial`: the check has nothing to
    # check (ADR-015).
    not_applicable: list[Unknown] = field(default_factory=list)
    total_score: float = 0.0
    max_finding_weight: float = 0.0
    rank: int = 0  # 0 = not ranked (`unreachable`, `failed`)
    scanned_at: str = ""
    # Why it is `failed`, for the "not scanned" list. For `unreachable` the reason is the
    # `infra.unreachable` finding.
    reason: Reason | None = None

    @property
    def rank_key(self) -> tuple[float, float]:
        """The heaviest single finding first; the total only breaks ties.

        A site with one disaster is a better lead than one with ten trifles.
        """
        return (self.max_finding_weight, self.total_score)

    @property
    def top_findings(self) -> list[Finding]:
        """The three findings that fit in the suggested email."""
        return self.findings[:3]


# --------------------------------------------------------------------------- #
# The run as a whole: the result and progress events (sitetriage.pipeline)
# --------------------------------------------------------------------------- #
@dataclass
class Event:
    """Progress of a run. The web worker turns it into a progress bar, the CLI logs it."""

    kind: Literal["phase_started", "phase_finished", "domain_finished"]
    phase: Literal["level1", "level2", "level2_light", "recheck"]
    total: int
    done: int = 0
    domain: str | None = None
    status: str | None = None


@dataclass
class ScanResult:
    """The whole run: metadata, a summary by status and the ranked reports.

    Serialized, it is the JSON report, so the field order is also the key order; the schema is
    `sitetriage/schema/report-3.json`.
    """

    schema_version: str = SCHEMA_VERSION
    scanner_version: str = __version__
    started_at: str = ""
    finished_at: str = ""
    duration_s: dict[str, float] = field(default_factory=dict)
    # sha256 of the configuration that affects the result; same digest = same thresholds
    config_digest: str = ""
    # the profile merged over the defaults (`--profile` or `profile` in the config, ADR-023); None = none
    profile: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    # Exit criteria (ADR-015): the share of working domains that exhausted their budget, and for
    # each check the share of `unknown` among the working domains it ran on.
    budget_share: float = 0.0
    unknown_share: dict[str, float] = field(default_factory=dict)
    ranked: list[DomainReport] = field(default_factory=list)
    unreachable: list[DomainReport] = field(default_factory=list)
    not_scanned: list[DomainReport] = field(default_factory=list)  # `failed`; excluded ones are only a count


# --------------------------------------------------------------------------- #
# An input row from domains.csv
# --------------------------------------------------------------------------- #
@dataclass
class DomainInput:
    domain: str
    industry: str = "other"
    note: str = ""
