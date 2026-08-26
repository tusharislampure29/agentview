"""Turn a SiteReport into the demo's HTML: a side-by-side, diff-highlighted view
of what a human sees vs what an AI agent is served, plus a findings panel.

The diff is word-level (SequenceMatcher over whitespace-delimited tokens) so the
highlighting lands on readable phrases, not individual characters.
"""
from __future__ import annotations

import html
import re
from difflib import SequenceMatcher

from ..diff import similarity
from ..identities import by_key
from ..models import DIVERGENCE_THRESHOLD, FetchResult, Severity, SiteReport, Verdict

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
  <span>human <b>{_status(human)}</b> · {human.content_length:,}B</span>
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
