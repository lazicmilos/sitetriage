"""Command line: arguments, the input CSV, logging and reports.

`sitetriage.pipeline` runs the scan; the CLI touches neither the network nor the logic
(CONTRIBUTING, "Architecture rules").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from sitetriage import __version__, pipeline
from sitetriage.checks import registry
from sitetriage.config import ConfigError, available_profiles, get, load_config
from sitetriage.inputs import InputError, read_domain_list, read_exclusions
from sitetriage.messages import LANGS, catalog, templates
from sitetriage.models import DomainInput, Event, ScanResult
from sitetriage.report import csv_out, html_out, json_out

log = logging.getLogger("sitetriage")

EXAMPLES = """
examples:
  sitetriage scan domains.example.csv --out report/
  sitetriage scan domains.csv --level 1 --concurrency 4 --only institution.example
  sitetriage scan domains.csv --profile rs --out report/   # sites in Serbia: Serbian content detection
  sitetriage recheck snapshots/ --out report/          # no network, for calibrating thresholds
  sitetriage record my-domains.csv --out snapshots/
  sitetriage explain seo.canonical.duplicate
  sitetriage explain --all --markdown > checks.md
"""


# --------------------------------------------------------------------------- #
# Logging: JSON lines on stderr, with a `domain` field in every record
# --------------------------------------------------------------------------- #
class JsonLines(logging.Formatter):
    # The "Z" in the timestamp claims UTC; the default is local time, so outside Docker every
    # line would be shifted by the machine's time zone (BUG-012).
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "domain": getattr(record, "domain", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class OnlyDomain(logging.Filter):
    """`--debug-domain`: when one site behaves oddly, you do not want a log of 200 domains."""

    def __init__(self, domain: str) -> None:
        super().__init__()
        self.domain = domain

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.DEBUG:
            return True
        return getattr(record, "domain", None) == self.domain


PHASES = {"level1": "level 1", "level2": "level 2", "level2_light": "light level 2"}


def log_event(event: Event) -> None:
    """A "43/200" counter for a run that takes minutes. `recheck` takes a second and needs none."""
    if event.kind == "domain_finished" and event.phase in PHASES:
        phase = PHASES[event.phase]
        log.info("%s: %d/%d done", phase, event.done, event.total, extra={"domain": event.domain})


def setup_logging(debug_domain: str | None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLines())
    if debug_domain:
        handler.addFilter(OnlyDomain(debug_domain))
    root = logging.getLogger("sitetriage")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug_domain else logging.INFO)


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def _int_at_least(minimum: int):
    """argparse type: an integer ≥ `minimum`. A semaphore with zero slots stalls the run."""

    def parse(text: str) -> int:
        try:
            number = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
        if number < minimum:
            raise argparse.ArgumentTypeError(f"must be at least {minimum}, got {number}")
        return number

    return parse


FORMATS = ("html", "csv", "json")


def _formats(text: str) -> list[str]:
    """argparse type for `--format`: a comma-separated, non-empty subset of `FORMATS`.

    Spaces around a name and case do not matter. Anything else is an error: a typo used to write
    no report at all and still end with "output in out/" (BUG-07).
    """
    names = [name.strip().lower() for name in text.split(",")]
    unknown = [name for name in names if name not in FORMATS]
    if unknown:
        shown = ", ".join(repr(name) for name in unknown)
        raise argparse.ArgumentTypeError(
            f"unknown format {shown}; give one or more of {', '.join(FORMATS)}, separated by commas"
        )
    return list(dict.fromkeys(names))


def read_domains(path: Path, only: Sequence[str] = ()) -> list[DomainInput]:
    """The list from a file (`sitetriage.inputs`); warnings go to the log, `--only` narrows the list."""
    rows, warnings = read_domain_list(Path(path).read_bytes(), str(path))
    for warning in warnings:
        row = f"row {warning.row}: " if warning.row else ""
        log.warning("%s%s", row, warning.message, extra={"domain": warning.domain})
    if only:
        wanted = {d.lower() for d in only}
        rows = [r for r in rows if r.domain.lower() in wanted]
        if not rows:
            raise InputError(f"{path}: none of the --only domains is on the list")
    return rows


def read_excluded(config: dict, args: argparse.Namespace) -> list[str]:
    """Domains from `[operator] exclude_file` and from `--exclude`; both apply."""
    domains: list[str] = []
    for path in (get(config, "operator.exclude_file"), getattr(args, "exclude", None)):
        if not path:
            continue
        if not Path(path).is_file():
            raise InputError(f"{path}: the file of excluded domains does not exist")
        domains += read_exclusions(Path(path).read_bytes())
    return domains


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config, profile=args.profile)
    if args.concurrency:
        # Both together: more domains in progress than slots would mean a domain's budget
        # runs again while it waits in the queue.
        config["http"]["concurrency"] = args.concurrency
        config["http"]["domain_concurrency"] = args.concurrency
    if args.max_level2 is not None:
        config["escalation"]["max_level2"] = args.max_level2

    targets = read_domains(Path(args.domains), args.only)
    snapshots_dir = Path(args.snapshots or Path(args.out) / "snapshots")
    result = asyncio.run(
        pipeline.scan(
            targets,
            config,
            level=args.level,
            snapshot_dir=snapshots_dir,
            excluded=read_excluded(config, args),
            on_event=log_event,
        )
    )
    _emit(result, config, args)
    return 0


def _emit(result: ScanResult, config: dict, args: argparse.Namespace) -> None:
    # CSV and HTML get every domain; the HTML splits them into ranked, "unreachable" and "not scanned".
    reports = result.ranked + result.unreachable + result.not_scanned
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    formats = set(args.format)
    lang = args.lang or get(config, "report.lang")

    if "csv" in formats:
        csv_out.write_findings(out / "findings.csv", reports, bom=args.csv_bom, lang=lang)
        csv_out.write_summary(out / "summary.csv", reports, bom=args.csv_bom)
    if "html" in formats:
        html_out.write(
            out / "index.html",
            reports,
            config,
            duration_s=result.duration_s["total"],
            excluded=result.summary.get("excluded", 0),
            lang=lang,
        )
    if "json" in formats:
        json_out.write(out / "report.json", result)

    findings = sum(len(r.findings) for r in reports)
    profile = f"profile {result.profile}" if result.profile else "no profile"
    print(f"\n{len(reports)} domains · {findings} findings · {profile} · output in {out}/", file=sys.stderr)
    for report in result.ranked[:10]:
        top = report.findings[0].check_id if report.findings else "—"
        print(
            f"  {report.rank:>3}. {report.domain:<28} score {report.total_score:>7.1f}"
            f"  worst {report.max_finding_weight:>5.1f}  {top}",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- #
# recheck: the main calibration tool
# --------------------------------------------------------------------------- #
def cmd_recheck(args: argparse.Namespace) -> int:
    config = load_config(args.config, profile=args.profile)
    _emit(pipeline.recheck(Path(args.snapshots), config, on_event=log_event), config, args)
    return 0


# --------------------------------------------------------------------------- #
# record: records fixtures (tests/fixtures/README.md)
# --------------------------------------------------------------------------- #
def cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config, profile=args.profile)
    targets = read_domains(Path(args.domains), args.only)
    out = Path(args.out)
    excluded = read_excluded(config, args)
    count = asyncio.run(pipeline.record(targets, config, out_dir=out, level=args.level, excluded=excluded))
    print(f"recorded {count} snapshots in {out}/", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# explain: a description of each check that someone other than you can use
# --------------------------------------------------------------------------- #
def cmd_explain(args: argparse.Namespace) -> int:
    registry.load_all()
    specs = sorted(registry.REGISTRY.values(), key=lambda s: (s.level, s.check_id))

    if args.all:
        if args.markdown:
            print("| `check_id` | Level | Category | Severity | Threshold |")
            print("|---|---|---|---|---|")
            for spec in specs:
                print(
                    f"| `{spec.check_id}` | {spec.level} | {spec.category} | "
                    f"{spec.base_severity} | {spec.threshold} |"
                )
        else:
            for spec in specs:
                print(f"{spec.check_id:32} level {spec.level}  {spec.base_severity:8} {spec.threshold}")
        return 0

    spec = registry.REGISTRY.get(args.check_id)
    if spec is None:
        similar = [s.check_id for s in specs if args.check_id in s.check_id]
        raise SystemExit(
            f"unknown check: {args.check_id}"
            + (f"\ndid you mean: {', '.join(similar)}" if similar else "\nall: sitetriage explain --all")
        )

    print(f"{spec.check_id}\n{'=' * len(spec.check_id)}")
    print(f"level:       {spec.level}")
    print(f"category:    {spec.category}")
    print(f"severity:    {spec.base_severity}")
    print(f"threshold:   {spec.threshold}")
    print(f"requires:    {', '.join(spec.requires) or '—'}")
    print(f"\n{spec.description}")
    for lang in LANGS:
        client, tech = templates(spec.check_id, lang)
        print(f"\nclient sentence ({lang}):\n  {client}")
        print(f"technical sentence ({lang}):\n  {tech}")
        for variant in catalog(lang).FINDINGS[spec.check_id].get("variants", {}):
            print(f"variant {variant} ({lang}):\n  {templates(spec.check_id, lang, variant)[0]}")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sitetriage",
        description="Ranks domains by which deserve a full manual audit. Reads sites, never writes to them.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"sitetriage {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_config(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--config", metavar="FILE", help="TOML merged over the default config (sitetriage.toml)"
        )
        sub.add_argument(
            "--profile",
            metavar="NAME",
            help=(
                "profile merged between the defaults and --config, e.g. rs (Serbian content detection); "
                "wins over `profile` in --config, an empty NAME means none; "
                f"available: {', '.join(available_profiles())}"
            ),
        )

    def add_common(sub: argparse.ArgumentParser) -> None:
        add_config(sub)
        sub.add_argument("--out", default="out", metavar="DIR", help="where reports go (default: out)")
        sub.add_argument(
            "--format",
            type=_formats,
            default=list(FORMATS),
            metavar="LIST",
            help="html, csv, json or several separated by commas (default: all three)",
        )
        sub.add_argument("--csv-bom", action="store_true", help="UTF-8 with a BOM, for Excel")
        sub.add_argument(
            "--lang",
            choices=LANGS,
            default=None,
            help="language of sentences and reports (default: report.lang, en; the rs profile sets sr)",
        )
        sub.add_argument("--debug-domain", metavar="DOMAIN", help="DEBUG log for this domain only")

    scan = subparsers.add_parser("scan", help="full run over a domain list")
    scan.add_argument("domains", metavar="DOMAINS.csv", help="CSV with the columns domain,industry,note")
    scan.add_argument("--level", choices=["1", "2", "auto"], default="auto", help="default: auto")
    scan.add_argument(
        "--concurrency",
        type=_int_at_least(1),
        metavar="N",
        help="global semaphore and domains at once (default from the config)",
    )
    scan.add_argument(
        "--max-level2", type=_int_at_least(0), metavar="N", help="upper limit for level 2 (60)"
    )
    scan.add_argument(
        "--snapshots", metavar="DIR", help="where snapshots are written (default: OUT/snapshots)"
    )
    scan.add_argument(
        "--only", action="append", default=[], metavar="DOMAIN", help="only this domain; may be repeated"
    )
    scan.add_argument("--exclude", metavar="FILE", help="domains not to scan, one per line")
    add_common(scan)
    scan.set_defaults(func=cmd_scan)

    recheck = subparsers.add_parser(
        "recheck", help="runs the checks again on saved snapshots, without the network"
    )
    recheck.add_argument("snapshots", metavar="SNAPSHOTS_DIR")
    add_common(recheck)
    recheck.set_defaults(func=cmd_recheck)

    record = subparsers.add_parser("record", help="records snapshots as fixtures")
    record.add_argument("domains", metavar="DOMAINS.csv")
    record.add_argument("--out", required=True, metavar="DIR")
    record.add_argument("--level", choices=["1", "2", "auto"], default="auto")
    record.add_argument("--only", action="append", default=[], metavar="DOMAIN")
    record.add_argument("--exclude", metavar="FILE")
    add_config(record)
    record.add_argument("--debug-domain", metavar="DOMAIN")
    record.set_defaults(func=cmd_record)

    explain = subparsers.add_parser("explain", help="what a check does and what its threshold is")
    explain.add_argument("check_id", nargs="?", metavar="CHECK_ID")
    explain.add_argument("--all", action="store_true", help="all checks")
    explain.add_argument("--markdown", action="store_true", help="table for the README (with --all)")
    explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "explain" and not args.all and not args.check_id:
        parser.error("give a CHECK_ID or --all")
    setup_logging(getattr(args, "debug_domain", None))
    try:
        return args.func(args)
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    except InputError as exc:
        raise SystemExit(str(exc)) from exc
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
