"""Shared HTML presentation: turn a :class:`SiteReport` into a side-by-side,
diff-highlighted view of what a human sees vs what an AI agent is served.

This lives at the package root, not under ``demo/``, because two callers need it
and neither should depend on the other:

* the **web demo** wraps :func:`render_result` in an interactive page, and
* ``agentview check --html`` wraps it in a self-contained file via
  :func:`standalone_report`.

It depends only on the standard library plus the engine's own diff helpers — no
FastAPI, no template engine — so importing it never pulls in the demo extra.

The diff is word-level (SequenceMatcher over whitespace-delimited tokens) so the
highlighting lands on readable phrases, not individual characters.
"""
from __future__ import annotations

import html
import re
from difflib import SequenceMatcher

from .diff import similarity
from .identities import by_key
from .models import DIVERGENCE_THRESHOLD, FetchResult, Severity, SiteReport, Verdict

_TOKEN = re.compile(r"\S+\s*")
# Cap how much text we paint into the page so a giant article stays responsive.
_MAX_DISPLAY = 24_000

VERDICT_BLURB = {
    Verdict.IDENTICAL: ("identical", "The agent and a human see the same page."),
    Verdict.BENIGN_DIVERGENCE: ("different", "The agent is served a different page — "
                                "but nothing here is aimed at steering the model."),
    Verdict.MANIPULATIVE: ("manipulative", "The agent-only content is written to steer "
                           "the model's answer (answer-engine manipulation)."),
    Verdict.ADVERSARIAL: ("adversarial", "The agent is served hidden instructions / "
                          "injection a human never sees."),
    Verdict.ERROR: ("error", "Couldn't fetch a human baseline to compare against."),
}

_SEV_CLASS = {
    Severity.HIGH: "sev-high", Severity.MEDIUM: "sev-med",
    Severity.LOW: "sev-low", Severity.INFO: "sev-info",
}

# The single source of truth for the visual style, shared by the demo shell and the
# standalone report. Kept as a plain string so there's no template-engine dependency.
CSS = """
:root{--bg:#0f1420;--panel:#fff;--ink:#1c2330;--muted:#5b6472;--line:#e2e6ec;
--accent:#4361ee;--aionly:#ffe3e3;--aiink:#9b1c1c;--humanonly:#e6f4ea;--humanink:#1c6b32;}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--ink);background:#f4f6f9;line-height:1.5}
header{background:var(--bg);color:#fff;padding:34px 20px 30px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
h1{margin:0;font-size:26px;letter-spacing:-.3px}
h1 .av{color:#8ea2ff}
.tag{margin:8px 0 0;color:#b8c0d0;font-size:15px;max-width:720px}
.tag code{background:#1c2330;padding:1px 6px;border-radius:4px;color:#c9d2e4}
form{display:flex;gap:10px;margin:22px 0 8px}
input[type=url]{flex:1;padding:13px 15px;font-size:15px;border:1px solid #2a3345;border-radius:9px;
background:#1a2130;color:#fff}
input[type=url]::placeholder{color:#7a8399}
button{padding:13px 22px;font-size:15px;font-weight:600;border:0;border-radius:9px;
background:var(--accent);color:#fff;cursor:pointer}
button:hover{background:#3350d6}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.chip{font-size:12.5px;color:#c3ccdd;text-decoration:none;background:#1c2330;padding:5px 10px;
border:1px solid #2a3345;border-radius:20px}
.chip:hover{border-color:#4a5570;color:#fff}
.chip-featured{background:#2a2050;border-color:#5a4bd0;color:#c9c0ff}
.chip-featured:hover{border-color:#8ea2ff;color:#fff}
main{max-width:1080px;margin:26px auto 60px;padding:0 20px}
.verdict{display:flex;align-items:baseline;gap:12px;padding:14px 16px;border-radius:10px;
font-size:15px;margin-bottom:14px;border:1px solid var(--line);background:#fff}
.vlabel{font-weight:800;letter-spacing:.5px;font-size:13px;padding:3px 9px;border-radius:6px;color:#fff}
.verdict-identical .vlabel{background:#3fa34d}.verdict-identical{border-left:5px solid #3fa34d}
.verdict-different .vlabel,.verdict-benign_divergence .vlabel{background:#e0a800}
.verdict-different{border-left:5px solid #e0a800}
.verdict-manipulative .vlabel{background:#b5179e}.verdict-manipulative{border-left:5px solid #b5179e}
.verdict-adversarial .vlabel{background:#7209b7}.verdict-adversarial{border-left:5px solid #7209b7}
.verdict-error{border-left:5px solid #d1495b;color:#7a2230}
.meta{display:flex;gap:20px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:14px}
.meta b{color:var(--ink)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.colhead{font-size:13px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.4px}
.pane{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;height:420px;
overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:13.5px;color:#333}
.ai-only{background:var(--aionly);color:var(--aiink);border-radius:3px;padding:0 2px;font-weight:600}
.human-only{background:var(--humanonly);color:var(--humanink);border-radius:3px;padding:0 2px}
.blocked{color:#b5179e;font-weight:600}
.none{color:var(--muted);font-style:italic}
h3{margin:26px 0 8px;font-size:16px}
table.findings{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);
border-radius:10px;overflow:hidden;font-size:13px}
.findings th{text-align:left;background:#f0f2f6;padding:8px 10px;color:var(--muted);font-weight:600}
.findings td{padding:8px 10px;border-top:1px solid var(--line);vertical-align:top}
.findings .sev{font-weight:700;text-transform:uppercase;font-size:11px}
.sev-high .sev{color:#7209b7}.sev-med .sev{color:#d1495b}.sev-low .sev{color:#e0a800}
.sev-info .sev{color:var(--muted)}
.ftype{font-family:ui-monospace,Menlo,Consolas,monospace}
.fwhere{color:var(--muted)}.fsnip{color:#333}
.findings .none{padding:14px;text-align:center}
.foot{color:var(--muted);font-size:12.5px;margin-top:16px;line-height:1.6}
.foot code{background:#eceef2;padding:1px 5px;border-radius:4px}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--muted);margin:2px 0 16px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:14px;height:14px;border-radius:3px;display:inline-block}
"""

LEGEND = (
    '<div class="legend">'
    '<span><i class="sw" style="background:#ffe3e3"></i> content only the AI is served</span>'
    '<span><i class="sw" style="background:#e6f4ea"></i> content only the human is served</span>'
    '</div>'
)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text[:_MAX_DISPLAY])


def diff_columns(human_text: str, ai_text: str) -> tuple[str, str]:
    """Return (human_html, ai_html): matching text is plain; text unique to one
    side is wrapped in a highlight span (``ai-only`` is the important one)."""
    h_tok, a_tok = _tokens(human_text), _tokens(ai_text)
    sm = SequenceMatcher(None, h_tok, a_tok, autojunk=False)
    human_parts: list[str] = []
    ai_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        h_seg = html.escape("".join(h_tok[i1:i2]))
        a_seg = html.escape("".join(a_tok[j1:j2]))
        if tag == "equal":
            human_parts.append(h_seg)
            ai_parts.append(a_seg)
        else:  # replace / delete / insert
            if h_seg:
                human_parts.append(f'<span class="human-only">{h_seg}</span>')
            if a_seg:
                ai_parts.append(f'<span class="ai-only">{a_seg}</span>')
    return "".join(human_parts), "".join(ai_parts)


def choose_ai_identity(report: SiteReport) -> str | None:
    """The AI view most worth showing, in priority order:
      1. one that carries a finding (injected/manipulative content),
      2. one served an *altered but non-empty 2xx/3xx page* (the novel case),
      3. the most divergent view overall (usually a block),
      4. any AI view that fetched.
    """
    finding_ids = [f.identity for f in report.findings]
    if finding_ids:
        return finding_ids[0]

    by_similarity = sorted(report.divergences, key=lambda d: d.similarity)
    for d in by_similarity:
        fr = report.fetches.get(d.identity)
        if (fr and fr.ok and (fr.status or 0) < 400 and fr.text
                and d.similarity < DIVERGENCE_THRESHOLD):
            return d.identity  # altered content, not just a block
    for d in by_similarity:
        fr = report.fetches.get(d.identity)
        if fr and fr.ok:
            return d.identity
    for key, fr in report.fetches.items():
        if key != "human" and fr.ok:
            return key
    return None


def _finding_rows(report: SiteReport) -> str:
    rows = []
    page_findings = [(f, "page") for f in report.findings]
    file_findings = [(f, af.path) for af in report.agent_files for f in af.findings]
    for f, where in sorted(page_findings + file_findings,
                           key=lambda p: p[0].severity is not Severity.HIGH):
        rows.append(
            f'<tr class="{_SEV_CLASS[f.severity]}">'
            f'<td class="sev">{f.severity.value}</td>'
            f'<td class="ftype">{html.escape(f.type.value)}</td>'
            f'<td class="fwhere">{html.escape(f.identity)} · {html.escape(where)}</td>'
            f'<td class="fsnip">{html.escape(f.snippet[:200])}</td></tr>'
        )
    if not rows:
        return ('<tr><td colspan="4" class="none">No adversarial signals in the '
                'agent-only content.</td></tr>')
    return "".join(rows)


def render_result(report: SiteReport) -> str:
    """The inner HTML of the results panel (returned for both full-page and htmx-style
    fragment use)."""
    human = report.fetches.get("human")
    ai_key = choose_ai_identity(report)
    ai = report.fetches.get(ai_key) if ai_key else None
    ai_ident = by_key(ai_key) if ai_key else None
    ai_label = ai_ident.label if ai_ident else "AI agent"

    vclass, vblurb = VERDICT_BLURB[report.verdict]

    if not human or not human.ok:
        return (f'<div class="verdict verdict-error"><b>error</b> — {html.escape(vblurb)}</div>')

    ai_blocked = bool(ai and ai.ok and (ai.status or 0) >= 400)
    ai_served_page = bool(ai and ai.ok and (ai.status or 0) < 400 and ai.text)

    if ai_served_page:
        human_html, ai_html = diff_columns(human.text, ai.text)
        sim = similarity(human.text, ai.text)
        sim_note = f"{sim * 100:.0f}% text overlap"
    elif ai_blocked:
        human_html = html.escape(human.text[:_MAX_DISPLAY])
        ai_html = (f'<div class="blocked"><b>{ai.status}</b> — the site blocks '
                   f'{html.escape(ai_label)} from this page.<br>'
                   f'A human is served the full page on the left; this agent gets '
                   f'an error page (or nothing).</div>')
        sim_note = f"agent blocked ({ai.status})"
    else:
        human_html = html.escape(human.text[:_MAX_DISPLAY])
        err = (ai.error if ai else "no AI fetch")
        ai_html = (f'<div class="blocked">no readable page returned to '
                   f'{html.escape(ai_label)} ({html.escape(str(err))})</div>')
        sim_note = "agent got no page"

    def _status(fr: FetchResult | None) -> str:
        if not fr:
            return "—"
        return str(fr.status) if fr.ok else "fail"

    human_kind = "human · rendered DOM" if (human and human.rendered) else "human"

    note_html = ""
    if report.notes:
        note_html = '<p class="foot">' + "<br>".join(
            html.escape(n) for n in report.notes) + "</p>"

    return f"""
<div class="verdict verdict-{vclass}">
  <span class="vlabel">{vclass.upper()}</span>
  <span class="vblurb">{html.escape(vblurb)}</span>
</div>
<div class="meta">
  <span>{human_kind} <b>{_status(human)}</b> · {human.content_length:,}B</span>
  <span>{html.escape(ai_label)} <b>{_status(ai)}</b> · {ai.content_length if ai else 0:,}B</span>
  <span>{sim_note}</span>
</div>
<div class="cols">
  <div class="col">
    <div class="colhead">What a <b>human</b> sees</div>
    <div class="pane">{human_html or '<span class="none">(empty)</span>'}</div>
  </div>
  <div class="col">
    <div class="colhead">What <b>{html.escape(ai_label)}</b> sees</div>
    <div class="pane">{ai_html or '<span class="none">(empty)</span>'}</div>
  </div>
</div>
<h3>Signals in the agent-only content</h3>
<table class="findings">
  <tr><th>severity</th><th>type</th><th>where</th><th>snippet</th></tr>
  {_finding_rows(report)}
</table>
<p class="foot">Method: one HTTP GET per identity, only the <code>User-Agent</code> varies.
UA-spoofing is a <b>lower bound</b> — sites that fingerprint via TLS/behaviour will
show us the human page anyway. Read-only; public content only.</p>
{note_html}
"""


_REPORT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agentview report — {title}</title>
<style>{css}</style></head>
<body>
<header><div class="wrap">
  <h1><span class="av">agentview</span> report</h1>
  <p class="tag">What <code>{title}</code> serves a human vs an AI agent.{subtitle}</p>
</div></header>
<main>
  {legend}
  {result}
</main>
</body></html>"""


def standalone_report(report: SiteReport, url: str, subtitle: str = "") -> str:
    """A single self-contained HTML file (inline CSS, no external assets, no JS) that
    anyone can open in a browser or attach to a bug report — the same side-by-side
    view the web demo shows, frozen for one URL."""
    sub = f" &nbsp;·&nbsp; {html.escape(subtitle)}" if subtitle else ""
    return _REPORT_PAGE.format(
        title=html.escape(url), css=CSS, subtitle=sub,
        legend=LEGEND, result=render_result(report),
    )
