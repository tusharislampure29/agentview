"""The demo's HTML shell + CSS. One page: a URL box and a results panel.

Kept as plain strings (no template engine) so the demo has the same lean
dependency surface as the rest of the project — FastAPI + uvicorn and nothing more.
"""
from __future__ import annotations

import html
from urllib.parse import quote

EXAMPLES = [
    "https://en.wikipedia.org/wiki/Prompt_injection",
    "https://www.reddit.com/r/programming/",
    "https://stackoverflow.com",
    "https://www.nytimes.com",
]

_CSS = """
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
