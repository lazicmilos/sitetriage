"""Komandna linija (§11): argumenti, ulazni CSV, logovanje i izveštaji.

Prolaz vodi `sitetriage.pipeline`; CLI ne dodiruje ni mrežu ni logiku.
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
from sitetriage.config import ConfigError, get, load_config
from sitetriage.inputs import InputError, read_domain_list, read_exclusions
from sitetriage.messages import LANGS, catalog, templates
from sitetriage.models import DomainInput, Event, ScanResult
from sitetriage.report import csv_out, html_out, json_out

log = logging.getLogger("sitetriage")

PRIMER = """
primeri:
  sitetriage scan domains.example.csv --out izvestaj/
  sitetriage scan domains.csv --level 1 --concurrency 4 --only institucija.example
  sitetriage recheck snapshots/ --out izvestaj/        # bez mreže, za kalibraciju pragova
  sitetriage record moji-domeni.csv --out snimci/
  sitetriage explain seo.canonical.duplicate
  sitetriage explain --all --markdown > provere.md
"""


# --------------------------------------------------------------------------- #
# Logovanje (§11.3): JSON linije na stderr, polje `domain` u svakom zapisu
# --------------------------------------------------------------------------- #
class JsonLines(logging.Formatter):
    # „Z" u vremenu tvrdi UTC; podrazumevano je lokalno vreme, pa bi van Docker-a svaki
    # red bio pomeren za vremensku zonu mašine (BUG-012).
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
    """`--debug-domain`: kad se jedan sajt ponaša čudno, ne želiš log od 200 domena."""

    def __init__(self, domain: str) -> None:
        super().__init__()
        self.domain = domain

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.DEBUG:
            return True
        return getattr(record, "domain", None) == self.domain


FAZE = {"level1": "nivo 1", "level2": "nivo 2", "level2_light": "nivo 2 lagano"}


def log_event(event: Event) -> None:
    """Brojač „43/200" za prolaz koji traje minutima. `recheck` traje sekundu i ne treba mu."""
    if event.kind == "domain_finished" and event.phase in FAZE:
        faza = FAZE[event.phase]
        log.info("%s: %d/%d gotovo", faza, event.done, event.total, extra={"domain": event.domain})


def setup_logging(debug_domain: str | None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLines())
    if debug_domain:
        handler.addFilter(OnlyDomain(debug_domain))
    root = logging.getLogger("sitetriage")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug_domain else logging.INFO)


# --------------------------------------------------------------------------- #
# Ulaz
# --------------------------------------------------------------------------- #
def _ceo_broj(najmanje: int):
    """Tip za argparse: ceo broj ≥ `najmanje`. Nula mesta u semaforu zaustavlja prolaz."""

    def parse(tekst: str) -> int:
        try:
            broj = int(tekst)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{tekst!r} nije ceo broj") from None
        if broj < najmanje:
            raise argparse.ArgumentTypeError(f"mora biti bar {najmanje}, a jeste {broj}")
        return broj

    return parse


def read_domains(path: Path, only: Sequence[str] = ()) -> list[DomainInput]:
    """Lista iz fajla (`sitetriage.inputs`); upozorenja idu u log, a `--only` sužava listu."""
    rows, warnings = read_domain_list(Path(path).read_bytes(), str(path))
    for warning in warnings:
        red = f"red {warning.row}: " if warning.row else ""
        log.warning("%s%s", red, warning.message, extra={"domain": warning.domain})
    if only:
        wanted = {d.lower() for d in only}
        rows = [r for r in rows if r.domain.lower() in wanted]
        if not rows:
            raise InputError(f"{path}: nijedan domen iz --only nije na listi")
    return rows


def read_excluded(config: dict, args: argparse.Namespace) -> list[str]:
    """Domeni iz `[identitet] izuzeti` i iz `--exclude`; oba važe."""
    domeni: list[str] = []
    for putanja in (get(config, "identitet.izuzeti"), getattr(args, "exclude", None)):
        if not putanja:
            continue
        if not Path(putanja).is_file():
            raise InputError(f"{putanja}: fajl sa izuzetim domenima ne postoji")
        domeni += read_exclusions(Path(putanja).read_bytes())
    return domeni


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.concurrency:
        # Oba zajedno: više domena u radu nego slotova znači da budžet domena opet
        # teče dok čeka u redu.
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
    # CSV i HTML dobijaju sve domene; HTML ih sam deli na rangirane, „Ne rade" i „Nije skenirano".
    reports = result.ranked + result.unreachable + result.not_scanned
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}

    if "csv" in formats:
        csv_out.write_findings(out / "findings.csv", reports, bom=args.csv_bom, lang=args.lang)
        csv_out.write_summary(out / "summary.csv", reports, bom=args.csv_bom)
    if "html" in formats:
        html_out.write(
            out / "index.html",
            reports,
            config,
            duration_s=result.duration_s["total"],
            excluded=result.summary.get("excluded", 0),
            lang=args.lang,
        )
    if "json" in formats:
        json_out.write(out / "report.json", result)

    nalaza = sum(len(r.findings) for r in reports)
    print(f"\n{len(reports)} domena · {nalaza} nalaza · izlaz u {out}/", file=sys.stderr)
    for report in result.ranked[:10]:
        top = report.findings[0].check_id if report.findings else "—"
        print(
            f"  {report.rank:>3}. {report.domain:<28} skor {report.total_score:>7.1f}"
            f"  najteži {report.max_finding_weight:>5.1f}  {top}",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- #
# recheck — glavno oruđe pri kalibraciji (§11.1)
# --------------------------------------------------------------------------- #
def cmd_recheck(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    _emit(pipeline.recheck(Path(args.snapshots), config, on_event=log_event), config, args)
    return 0


# --------------------------------------------------------------------------- #
# record — snima fixture-e (§12.2)
# --------------------------------------------------------------------------- #
def cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    targets = read_domains(Path(args.domains), args.only)
    out = Path(args.out)
    excluded = read_excluded(config, args)
    broj = asyncio.run(pipeline.record(targets, config, out_dir=out, level=args.level, excluded=excluded))
    print(f"snimljeno {broj} snapshota u {out}/", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# explain — izveštaj upotrebljiv za nekog ko nisi ti (§11.1)
# --------------------------------------------------------------------------- #
def cmd_explain(args: argparse.Namespace) -> int:
    registry.load_all()
    specs = sorted(registry.REGISTRY.values(), key=lambda s: (s.level, s.check_id))

    if args.all:
        if args.markdown:
            print("| `check_id` | Nivo | Kategorija | Ozbiljnost | Prag |")
            print("|---|---|---|---|---|")
            for spec in specs:
                print(
                    f"| `{spec.check_id}` | {spec.level} | {spec.category} | "
                    f"{spec.base_severity} | {spec.threshold} |"
                )
        else:
            for spec in specs:
                print(f"{spec.check_id:32} nivo {spec.level}  {spec.base_severity:8} {spec.threshold}")
        return 0

    spec = registry.REGISTRY.get(args.check_id)
    if spec is None:
        blizu = [s.check_id for s in specs if args.check_id in s.check_id]
        raise SystemExit(
            f"nepoznata provera: {args.check_id}"
            + (f"\nda li si mislio: {', '.join(blizu)}" if blizu else "\nsve: sitetriage explain --all")
        )

    print(f"{spec.check_id}\n{'=' * len(spec.check_id)}")
    print(f"nivo:        {spec.level}")
    print(f"kategorija:  {spec.category}")
    print(f"ozbiljnost:  {spec.base_severity}")
    print(f"prag:        {spec.threshold}")
    print(f"traži:       {', '.join(spec.requires) or '—'}")
    print(f"\n{spec.description}")
    for lang in LANGS:
        client, tech = templates(spec.check_id, lang)
        print(f"\nrečenica za klijenta ({lang}):\n  {client}")
        print(f"tehnička formulacija ({lang}):\n  {tech}")
        for variant in catalog(lang).FINDINGS[spec.check_id].get("variants", {}):
            print(f"varijanta {variant} ({lang}):\n  {templates(spec.check_id, lang, variant)[0]}")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sitetriage",
        description="Rangira domene po tome koji zaslužuju pun ručni audit. Čita, nikad ne piše.",
        epilog=PRIMER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"sitetriage {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--config", metavar="FILE", help="TOML koji se spaja preko skener.toml")
        sub.add_argument("--out", default="out", metavar="DIR", help="gde idu izveštaji (podrazumevano: out)")
        sub.add_argument(
            "--format", default="html,csv,json", help="html, csv, json ili više njih (podrazumevano: sva tri)"
        )
        sub.add_argument("--csv-bom", action="store_true", help="UTF-8 sa BOM-om, za Excel")
        sub.add_argument(
            "--lang", choices=LANGS, default="sr", help="jezik rečenica i izveštaja (podrazumevano: sr)"
        )
        sub.add_argument("--debug-domain", metavar="DOMAIN", help="DEBUG log samo za taj domen")

    scan = subparsers.add_parser("scan", help="pun prolaz nad listom domena")
    scan.add_argument("domains", metavar="DOMAINS.csv", help="CSV sa kolonama domain,industry,note")
    scan.add_argument("--level", choices=["1", "2", "auto"], default="auto", help="podrazumevano: auto")
    scan.add_argument(
        "--concurrency",
        type=_ceo_broj(1),
        metavar="N",
        help="globalni semafor i domena odjednom (podrazumevano iz skener.toml)",
    )
    scan.add_argument("--max-level2", type=_ceo_broj(0), metavar="N", help="gornji limit za nivo 2 (60)")
    scan.add_argument(
        "--snapshots", metavar="DIR", help="gde se pišu snapshoti (podrazumevano: OUT/snapshots)"
    )
    scan.add_argument(
        "--only", action="append", default=[], metavar="DOMAIN", help="samo ovaj domen; može više puta"
    )
    scan.add_argument("--exclude", metavar="FILE", help="domeni koji se ne skeniraju, jedan po redu")
    add_common(scan)
    scan.set_defaults(func=cmd_scan)

    recheck = subparsers.add_parser(
        "recheck", help="ponovo pokreće provere nad sačuvanim snapshotima, bez mreže"
    )
    recheck.add_argument("snapshots", metavar="SNAPSHOTS_DIR")
    add_common(recheck)
    recheck.set_defaults(func=cmd_recheck)

    record = subparsers.add_parser("record", help="snima snapshote kao fixture-e")
    record.add_argument("domains", metavar="DOMAINS.csv")
    record.add_argument("--out", required=True, metavar="DIR")
    record.add_argument("--level", choices=["1", "2", "auto"], default="auto")
    record.add_argument("--only", action="append", default=[], metavar="DOMAIN")
    record.add_argument("--exclude", metavar="FILE")
    record.add_argument("--config", metavar="FILE")
    record.add_argument("--debug-domain", metavar="DOMAIN")
    record.set_defaults(func=cmd_record)

    explain = subparsers.add_parser("explain", help="šta provera radi, koji joj je prag")
    explain.add_argument("check_id", nargs="?", metavar="CHECK_ID")
    explain.add_argument("--all", action="store_true", help="sve provere")
    explain.add_argument("--markdown", action="store_true", help="tabela za README (uz --all)")
    explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "explain" and not args.all and not args.check_id:
        parser.error("navedi CHECK_ID ili --all")
    setup_logging(getattr(args, "debug_domain", None))
    try:
        return args.func(args)
    except ConfigError as exc:
        raise SystemExit(f"greška u konfiguraciji: {exc}") from exc
    except InputError as exc:
        raise SystemExit(str(exc)) from exc
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
