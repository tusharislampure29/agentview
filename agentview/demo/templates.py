"""The demo's HTML shell. One page: a URL box and a results panel.

Kept as plain strings (no template engine) so the demo has the same lean
dependency surface as the rest of the project — FastAPI + uvicorn and nothing more.
The visual style (``CSS``) and the results panel itself (:func:`render_result`)
live in :mod:`agentview.htmlview`, shared with the CLI's ``--html`` report.
"""
from __future__ import annotations

import html
from urllib.parse import quote

from ..htmlview import CSS as _CSS

EXAMPLES = [
    "https://en.wikipedia.org/wiki/Prompt_injection",
    "https://www.reddit.com/r/programming/",
    "https://stackoverflow.com",
    "https://www.nytimes.com",
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agentview — the web your AI actually reads</title>
<meta name="description" content="Paste a URL. See it as a human and as an AI agent, side by side.">
<style>{css}</style></head>
<body>
<header><div class="wrap">
  <h1><span class="av">agentview</span> — the web your AI actually reads</h1>
  <p class="tag">Sites can tell an AI crawler apart from you and serve it a different —
  sometimes poisoned — page. Paste a URL to see both views side by side.</p>
  <form action="/" method="get">
    <input type="url" name="url" placeholder="https://example.com/article" value="{value}"
           autofocus required>
    <button type="submit">Compare</button>
  </form>
  <div class="chips">{examples}</div>
</div></header>
<main>
  <div class="legend">
    <span><i class="sw" style="background:#ffe3e3"></i> content only the AI is served</span>
    <span><i class="sw" style="background:#e6f4ea"></i> content only the human is served</span>
  </div>
  {result}
</main>
</body></html>"""


def _example_chips() -> str:
    featured = ('<a class="chip chip-featured" href="/?demo=cloaking">'
                '★ live example (synthetic)</a>')
    rest = "".join(
        f'<a class="chip" href="/?url={quote(u, safe="")}">{html.escape(u.split("://")[1][:38])}</a>'
        for u in EXAMPLES
    )
    return featured + rest


def render_page(value: str = "", result_html: str = "") -> str:
    return PAGE.format(css=_CSS, examples=_example_chips(),
                       value=html.escape(value, quote=True), result=result_html)
