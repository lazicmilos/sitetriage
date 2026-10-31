"""HTML report: one self-contained file, without external dependencies.

No CDN and no template file: the CSS and the little JS there is live here, so the report
opens without a network, and the package has nothing to ship besides the code.

Severity is not shown by colour alone: each one also carries a label and a glyph, so it can
be told apart in greyscale and by colour-blind readers.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from pathlib import Path

from sitetriage import __version__
from sitetriage.config import get
from sitetriage.messages import number, text
from sitetriage.messages import reason as render_reason
from sitetriage.messages import render as render_message
from sitetriage.models import DomainReport
from sitetriage.score import RADE, partial_shares

# Glyph and colours by severity; the label ("KRITIČNO", "CRITICAL") comes from the language catalog.
SEVERITY = {
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
    glyph, fg, bg = SEVERITY.get(severity, ("?", "#374151", "#e5e7eb"))
    label = text(f"severity_{severity}", lang) if severity in SEVERITY else "?"
    return f'<span class="tag" style="color:{fg};background:{bg}">{glyph} {_e(label)}</span>'


def _unreachable_finding(report: DomainReport):
    return next(f for f in report.findings if f.check_id == "infra.unreachable")


def email_draft(report: DomainReport, lang: str = "sr") -> str:
    """Three sentences from the three heaviest findings: that is what fits in an email.

    An unreachable site gets its own draft, without "I noticed the following problems" (ADR-013).
    """
    if report.status == "unreachable":
        sentence = render_message(_unreachable_finding(report), lang).client
        return text("draft_unreachable", lang, domain=report.domain, sentence=sentence)
    if not report.findings:
        return text("draft_clean", lang, domain=report.domain)
    lines = [f"{i}. {render_message(f, lang).client}" for i, f in enumerate(report.top_findings, start=1)]
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

    def with_status(status: str) -> list[DomainReport]:
        return [r for r in reports if r.status == status]

    # Ranking is only for working sites; the others have their own sections (ADR-013).
    ranked = [r for r in reports if r.status in RADE]
    level2 = sum(1 for r in reports if r.level2_ran)
    generated = reports[0].scanned_at if reports else ""

    cards = [
        (t("card_domains"), len(reports)),
        (t("card_scanned"), len(with_status("scanned"))),
        (t("card_partial"), len(with_status("partial"))),
        (t("card_unreachable"), len(with_status("unreachable"))),
        (t("card_failed"), len(with_status("failed"))),
        (t("card_level2"), level2),
    ]
    if excluded:
        cards.append((t("card_excluded"), excluded))
    if duration_s is not None:
        duration = number(duration_s, lang) if duration_s < 10 else f"{duration_s:.0f}"
        cards.append((t("card_duration"), f"{duration} s"))

    speed = get(config, "network_profile.download_mbps")
    overhead = get(config, "report.mobile_overhead_s")
    # Numbers, not text: the language formatter writes them with a comma or a point.
    assumption = text("assumption_html", lang, speed=speed, mb_per_s=round(speed / 8, 2), overhead=overhead)
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
{_unreachable(with_status("unreachable"), lang)}{_not_scanned(with_status("failed"), excluded, lang)}
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
        f'<td class="num">{number(report.total_score, lang)}</td>'
        f"<td>{(_badge(top.severity, lang) + ' ' + _e(top.check_id)) if top else '—'}</td>"
        f'<td class="num">{len(report.findings)}</td>'
        f"<td>{_e(text('yes' if report.level2_ran else 'no', lang))}</td>"
        f"<td>{_e(report.status)}</td></tr>"
    )


def _shares(reports: Sequence[DomainReport], lang: str) -> str:
    """Both causes of `partial` separately, as in the exit criteria (ADR-015)."""
    budget, by_check = partial_shares(reports)
    rows = "".join(
        f'<tr><td>{_e(check_id)}</td><td class="num">{_e(text("percent", lang, share=share * 100))}</td></tr>'
        for check_id, share in sorted(by_check.items(), key=lambda kv: (-kv[1], kv[0]))
        if share
    )
    table = (
        f'<details class="unknowns"><summary>{_e(text("share_unknown", lang))}</summary>'
        f"<table><thead><tr><th>{_e(text('col_check', lang))}</th>"
        f'<th class="num">{_e(text("col_share", lang))}</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></details>"
        if rows
        else ""
    )
    return f'<p class="sub">{_e(text("share_budget", lang, share=budget * 100))}</p>\n{table}\n'


def _unreachable(reports: Sequence[DomainReport], lang: str) -> str:
    if not reports:
        return ""
    copy = _e(text("copy_draft", lang))
    rows = "".join(
        f"<tr><td><b>{_e(r.domain)}</b></td><td>{_e(r.industry)}</td>"
        f"<td>{_e(render_message(_unreachable_finding(r), lang).client)}</td>"
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
        f"<td>{_e(render_reason(r.reason, lang) if r.reason else '—')}</td></tr>"
        for r in reports
    )
    table = (
        f"<table><thead><tr><th>{_e(text('col_domain', lang))}</th><th>{_e(text('col_industry', lang))}</th>"
        f"<th>{_e(text('col_reason', lang))}</th></tr></thead><tbody>{rows}</tbody></table>"
        if reports
        else ""
    )
    excluded_note = (
        f'<p class="sub">{_e(text("excluded_count", lang, count=excluded))}</p>' if excluded else ""
    )
    return f"""
<h2>{_e(text("not_scanned", lang))}</h2>
<p class="sub">{_e(text("not_scanned_note", lang))}</p>
{table}{excluded_note}
"""


def _details(report: DomainReport, lang: str) -> str:
    draft = _e(email_draft(report, lang))
    findings = "".join(_finding(f, lang) for f in report.findings) or (
        f'<p class="finding">{_e(text("no_findings", lang))}</p>'
    )
    unknowns = ""
    if report.unknowns:
        items = "".join(
            f"<li><code>{_e(u.check_id)}</code> — {_e(render_reason(u.reason, lang))}</li>"
            for u in report.unknowns
        )
        heading = _e(text("unknowns", lang, count=len(report.unknowns)))
        unknowns = f'<details class="unknowns"><summary>{heading}</summary><ul>{items}</ul></details>'
    unknowns += "".join(
        f'<p class="tech"><code>{_e(n.check_id)}</code> — '
        f'{_e(text("not_applicable", lang, text=render_reason(n.reason, lang)))}</p>'
        for n in report.not_applicable
    )
    reasons = ""
    if report.escalation_reasons:
        because = "; ".join(render_reason(r, lang) for r in report.escalation_reasons)
        because = _e(text("escalated_because", lang) + because)
        reasons = f'<p class="tech">{because}</p>'
    meta = text(
        "summary_meta",
        lang,
        industry=report.industry,
        score=report.total_score,
        worst=report.max_finding_weight,
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
    message = render_message(finding, lang)
    meta = text("finding_meta", lang, level=finding.level, weight=finding.weight)
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
