"""HTML izveštaj (§10.2): jedan samostalan fajl, bez spoljnih zavisnosti.

Bez CDN-a i bez template fajla — CSS i ono malo JS-a stoje ovde, pa se izveštaj
otvara i bez mreže, a paket nema šta da pakuje pored koda.

Ozbiljnost se ne prepoznaje samo po boji: svaka nosi i oznaku i znak, da se
razlikuje u sivim tonovima i kod daltonista (§10.2).
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from pathlib import Path

from skener import __version__
from skener.config import get
from skener.messages import reason as razlog
from skener.messages import render as poruka
from skener.messages import text
from skener.models import DomainReport
from skener.score import RADE, partial_shares

# Znak i boje po ozbiljnosti; oznaka („KRITIČNO") dolazi iz kataloga jezika.
OZBILJNOST = {
    "critical": ("▲", "#7f1d1d", "#fee2e2"),
    "high": ("●", "#9a3412", "#ffedd5"),
    "medium": ("◆", "#854d0e", "#fef9c3"),
    "low": ("▪", "#1e3a8a", "#dbeafe"),
}

CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#111827; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb; --accent:#1d4ed8; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#0b0f19; --fg:#e5e7eb; --muted:#9ca3af; --line:#1f2937; --card:#111827; --accent:#60a5fa; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
  font:15px/1.6 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; }
.wrap { max-width:1100px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 4px; }
h2 { font-size:18px; margin:32px 0 12px; }
.sub { color:var(--muted); margin:0 0 24px; }
.cards { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:28px; }
.card { flex:1 1 140px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:12px 14px; }
.card b { display:block; font-size:22px; }
.card span { color:var(--muted); font-size:13px; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; padding:1px 7px; border-radius:999px; font-size:11px;
  font-weight:700; letter-spacing:.03em; border:1px solid currentColor; white-space:nowrap; }
details { background:var(--card); border:1px solid var(--line); border-radius:10px;
  margin-bottom:10px; padding:0; }
summary { cursor:pointer; padding:12px 14px; display:flex; gap:10px; align-items:baseline;
  flex-wrap:wrap; }
summary::marker { color:var(--muted); }
summary .domain { font-weight:700; }
summary .meta { color:var(--muted); font-size:13px; }
.body { padding:0 14px 14px; }
.finding { border-top:1px solid var(--line); padding:12px 0; }
.finding p { margin:6px 0; }
.tech { color:var(--muted); font-size:13px; font-family:ui-monospace, "SF Mono", Menlo, monospace; }
.evidence { font-family:ui-monospace, "SF Mono", Menlo, monospace; font-size:12px;
  background:var(--bg); border:1px solid var(--line); border-radius:6px;
  padding:6px 8px; overflow-x:auto; margin:6px 0 0; }
a { color:var(--accent); }
button { font:inherit; padding:7px 12px; border-radius:8px; border:1px solid var(--line);
  background:var(--bg); color:var(--fg); cursor:pointer; }
button:hover { border-color:var(--accent); color:var(--accent); }
.unknowns { margin-top:12px; font-size:13px; color:var(--muted); }
footer { margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:13px; }
"""

JS = """
const LABELS = __LABELS__;
document.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-draft]');
  if (!button) return;
  const text = button.getAttribute('data-draft');
  const done = () => { button.textContent = LABELS.copied; setTimeout(() => {
    button.textContent = LABELS.copy; }, 1800); };
  if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done, fallback); }
  else fallback();
  function fallback() {
    const area = document.createElement('textarea');
    area.value = text; document.body.appendChild(area); area.select();
    try { document.execCommand('copy'); done(); } finally { area.remove(); }
  }
});
"""


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _badge(severity: str, lang: str) -> str:
    glyph, fg, bg = OZBILJNOST.get(severity, ("?", "#374151", "#e5e7eb"))
    label = text(f"severity_{severity}", lang) if severity in OZBILJNOST else "?"
    return f'<span class="tag" style="color:{fg};background:{bg}">{glyph} {_e(label)}</span>'


def _ne_radi(report: DomainReport):
    return next(f for f in report.findings if f.check_id == "infra.unreachable")


def email_draft(report: DomainReport, lang: str = "sr") -> str:
    """Tri rečenice od tri najteža nalaza — toliko staje u mejl (§9.4).

    Sajt koji ne radi dobija svoj nacrt, bez „primetio sam sledeće probleme" (Z-20).
    """
    if report.status == "unreachable":
        recenica = poruka(_ne_radi(report), lang).client
        return text("draft_unreachable", lang, domain=report.domain, recenica=recenica)
    if not report.findings:
        return text("draft_clean", lang, domain=report.domain)
    lines = [f"{i}. {poruka(f, lang).client}" for i, f in enumerate(report.top_findings, start=1)]
    opening = text("draft_opening", lang, domain=report.domain)
    return opening + "\n\n".join(lines) + text("draft_closing", lang)


def render(
    reports: Sequence[DomainReport],
    config: dict,
    *,
    duration_s: float | None = None,
    excluded: int = 0,
    lang: str = "sr",
) -> str:
    def t(key: str, **values) -> str:
        return _e(text(key, lang, **values))

    def sa(status: str) -> list[DomainReport]:
        return [r for r in reports if r.status == status]

    # Rangiranje je samo za sajtove koji rade; ostali imaju svoje odeljke (Z-20).
    ranked = [r for r in reports if r.status in RADE]
    level2 = sum(1 for r in reports if r.level2_ran)
    generated = reports[0].scanned_at if reports else ""

    cards = [
        (t("card_domains"), len(reports)),
        (t("card_scanned"), len(sa("scanned"))),
        (t("card_partial"), len(sa("partial"))),
        (t("card_unreachable"), len(sa("unreachable"))),
        (t("card_failed"), len(sa("failed"))),
        (t("card_level2"), level2),
    ]
    if excluded:
        cards.append((t("card_excluded"), excluded))
    if duration_s is not None:
        trajanje = f"{duration_s:.1f} s" if duration_s < 10 else f"{duration_s:.0f} s"
        cards.append((t("card_duration"), trajanje))

    speed = get(config, "thresholds.perf.mobile_speed_mbps")
    overhead = get(config, "report.mobile_overhead_s")
    assumption = text(
        "assumption_html", lang, speed=_e(speed), mb_per_s=_e(round(speed / 8, 2)), overhead=_e(overhead)
    )
    labels = {"copy": text("copy_draft", lang), "copied": text("copied", lang)}
    js = JS.replace("__LABELS__", json.dumps(labels, ensure_ascii=False))
    headers = (
        f'<th class="num">#</th><th>{t("col_domain")}</th><th>{t("col_industry")}</th>'
        f'<th class="num">{t("col_score")}</th>\n'
        f'<th>{t("col_worst")}</th><th class="num">{t("col_findings")}</th>'
        f'<th>{t("col_level2")}</th><th>{t("col_status")}</th>'
    )

    return f"""<!doctype html>
<html lang="{_e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t("page_title")}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>{t("heading")}</h1>
<p class="sub">{t("run_of", generated=generated, version=__version__)}</p>

<div class="cards">
{"".join(f'<div class="card"><b>{_e(v)}</b><span>{k}</span></div>' for k, v in cards)}
</div>
{_shares(reports, lang)}
<h2>{t("ranked")}</h2>
<p class="sub">{t("ranked_note")}</p>
<table>
<thead><tr>
{headers}
</tr></thead>
<tbody>
{"".join(_row(r, lang) for r in ranked)}
</tbody></table>
{_unreachable(sa("unreachable"), lang)}{_not_scanned(sa("failed"), excluded, lang)}
<h2>{t("by_domain")}</h2>
{"".join(_details(r, lang) for r in ranked)}

<footer>
<p>{assumption}</p>
<p>{text("read_only_html", lang)}</p>
</footer>
</div>
<script>{js}</script>
</body></html>
"""


def _row(report: DomainReport, lang: str) -> str:
    top = report.findings[0] if report.findings else None
    return (
        f'<tr><td class="num">{report.rank}</td>'
        f"<td><b>{_e(report.domain)}</b></td>"
        f"<td>{_e(report.industry)}</td>"
        f'<td class="num">{report.total_score:g}</td>'
        f"<td>{(_badge(top.severity, lang) + ' ' + _e(top.check_id)) if top else '—'}</td>"
        f'<td class="num">{len(report.findings)}</td>'
        f"<td>{_e(text('yes' if report.level2_ran else 'no', lang))}</td>"
        f"<td>{_e(report.status)}</td></tr>"
    )


def _shares(reports: Sequence[DomainReport], lang: str) -> str:
    """Oba uzroka `partial`-a posebno, kao izlazni kriterijumi iz §7 (Z-22)."""
    budzet, po_proveri = partial_shares(reports)
    rows = "".join(
        f'<tr><td>{_e(check_id)}</td><td class="num">{_e(text("percent", lang, udeo=udeo * 100))}</td></tr>'
        for check_id, udeo in sorted(po_proveri.items(), key=lambda kv: (-kv[1], kv[0]))
        if udeo
    )
    table = (
        f'<details class="unknowns"><summary>{_e(text("share_unknown", lang))}</summary>'
        f"<table><thead><tr><th>{_e(text('col_check', lang))}</th>"
        f'<th class="num">{_e(text("col_share", lang))}</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></details>"
        if rows
        else ""
    )
    return f'<p class="sub">{_e(text("share_budget", lang, udeo=budzet * 100))}</p>\n{table}\n'


def _unreachable(reports: Sequence[DomainReport], lang: str) -> str:
    if not reports:
        return ""
    copy = _e(text("copy_draft", lang))
    rows = "".join(
        f"<tr><td><b>{_e(r.domain)}</b></td><td>{_e(r.industry)}</td>"
        f"<td>{_e(poruka(_ne_radi(r), lang).client)}</td>"
        f'<td><button data-draft="{_e(email_draft(r, lang))}">{copy}</button></td></tr>'
        for r in reports
    )
    return f"""
<h2>{_e(text("unreachable", lang))}</h2>
<p class="sub">{_e(text("unreachable_note", lang))}</p>
<table><thead><tr><th>{_e(text("col_domain", lang))}</th><th>{_e(text("col_industry", lang))}</th>
<th>{_e(text("col_reason", lang))}</th><th></th></tr></thead>
<tbody>{rows}</tbody></table>
"""


def _not_scanned(reports: Sequence[DomainReport], excluded: int, lang: str) -> str:
    if not reports and not excluded:
        return ""
    rows = "".join(
        f"<tr><td><b>{_e(r.domain)}</b></td><td>{_e(r.industry)}</td>"
        f"<td>{_e(razlog(r.reason, lang) if r.reason else '—')}</td></tr>"
        for r in reports
    )
    table = (
        f"<table><thead><tr><th>{_e(text('col_domain', lang))}</th><th>{_e(text('col_industry', lang))}</th>"
        f"<th>{_e(text('col_reason', lang))}</th></tr></thead><tbody>{rows}</tbody></table>"
        if reports
        else ""
    )
    izuzeto = f'<p class="sub">{_e(text("excluded_count", lang, count=excluded))}</p>' if excluded else ""
    return f"""
<h2>{_e(text("not_scanned", lang))}</h2>
<p class="sub">{_e(text("not_scanned_note", lang))}</p>
{table}{izuzeto}
"""


def _details(report: DomainReport, lang: str) -> str:
    draft = _e(email_draft(report, lang))
    findings = "".join(_finding(f, lang) for f in report.findings) or (
        f'<p class="finding">{_e(text("no_findings", lang))}</p>'
    )
    unknowns = ""
    if report.unknowns:
        items = "".join(
            f"<li><code>{_e(u.check_id)}</code> — {_e(razlog(u.reason, lang))}</li>" for u in report.unknowns
        )
        naslov = _e(text("unknowns", lang, count=len(report.unknowns)))
        unknowns = f'<details class="unknowns"><summary>{naslov}</summary><ul>{items}</ul></details>'
    unknowns += "".join(
        f'<p class="tech"><code>{_e(n.check_id)}</code> — '
        f'{_e(text("not_applicable", lang, tekst=razlog(n.reason, lang)))}</p>'
        for n in report.not_applicable
    )
    reasons = ""
    if report.escalation_reasons:
        razlozi = "; ".join(razlog(r, lang) for r in report.escalation_reasons)
        razlozi = _e(text("escalated_because", lang) + razlozi)
        reasons = f'<p class="tech">{razlozi}</p>'
    meta = text(
        "summary_meta",
        lang,
        industry=report.industry,
        score=f"{report.total_score:g}",
        worst=f"{report.max_finding_weight:g}",
        findings=len(report.findings),
    )
    return f"""<details>
<summary><span class="domain">#{report.rank} {_e(report.domain)}</span>
<span class="meta">{_e(meta)}</span></summary>
<div class="body">
<p><button data-draft="{draft}">{_e(text("copy_draft", lang))}</button></p>
{reasons}{findings}{unknowns}
</div></details>"""


def _finding(finding, lang: str) -> str:
    urls = "".join(
        f'<div><a href="{_e(u)}" rel="noopener noreferrer nofollow">{_e(u)}</a></div>'
        for u in finding.evidence_urls[:3]
    )
    message = poruka(finding, lang)
    meta = text("finding_meta", lang, level=finding.level, weight=f"{finding.weight:g}")
    return f"""<div class="finding">
<p>{_badge(finding.severity, lang)} <code>{_e(finding.check_id)}</code>
<span class="tech">{_e(meta)}</span></p>
<p>{_e(message.client)}</p>
<p class="tech">{_e(message.tech)}</p>
<pre class="evidence">{_e(json.dumps(finding.evidence, ensure_ascii=False))}</pre>
{urls}</div>"""


def write(path: Path, reports: Sequence[DomainReport], config: dict, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(reports, config, **kwargs), encoding="utf-8")
    return path
