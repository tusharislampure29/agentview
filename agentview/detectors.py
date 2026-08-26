"""Heuristics that flag content aimed at an AI rather than a human.

Two layers:
  * ``scan_text``  — signals in visible/extracted text (invisible unicode,
    injection phrases, role tokens, answer-engine manipulation directives).
  * ``scan_html``  — signals that need the markup (instruction-bearing HTML
    comments, text hidden with inline CSS).

These are deliberately high-recall heuristics, not proof. Every finding carries a
snippet so a human can adjudicate — false positives are expected and reported.
"""
from __future__ import annotations

import re
from collections import Counter

from bs4 import BeautifulSoup, Comment

from .models import Finding, FindingType, Severity

# A single zero-width / format character is ordinary typography (soft hyphens,
# stray ZWSPs in CJK or JS-rendered text). Real steganographic smuggling uses a
# run of them, so we only flag the format-char class when it clusters. Bidi
# controls and unicode-tag characters, by contrast, are almost never benign, so
# they flag on first sight.
_ZW_CLUSTER_MIN = 2

# --- invisible / control characters ------------------------------------------
_INVISIBLE = {
    "​": "zero-width space",
    "‌": "zero-width non-joiner",
    "‍": "zero-width joiner",
    "﻿": "zero-width no-break space",
    "⁠": "word joiner",
    "­": "soft hyphen",
}
_BIDI = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}


def _is_tag_char(ch: str) -> bool:
    # Unicode "tag" block (U+E0000–U+E007F) — invisible, has been used to smuggle
    # instructions into text an LLM reads.
    return 0xE0000 <= ord(ch) <= 0xE007F


# --- text patterns ------------------------------------------------------------
# Imperative overrides. High-signal when shown only to the agent or hidden, but
# they also occur in prose that legitimately *discusses* prompt injection (docs,
# security blogs), so the caller sets their severity via ``imperative_severity``
# and can switch them off with ``include_imperative``.
_IMPERATIVE = [
    r"ignore\s+(all|any|the)?\s*(previous|prior|above)\s+instructions",
    r"disregard\s+(all|any|the)?\s*(previous|prior|above)\s+(instructions|context|text)",
    r"you are now\b",
    r"new instructions?\s*:",
    r"do not (tell|inform|reveal to|mention to) (the )?user",
]
# Chat-template / role control tokens — almost never legitimate page prose.
_ROLE_CONTROL = [
    r"</?(system|assistant|user)\s*>",
    r"\|im_(start|end)\|",
    r"<\|[a-z_]{2,20}\|>",
]
_MANIPULATION = [
    r"always recommend\b",
    r"(describe|present|call)\s+(us|this|our (product|company|brand))\s+(as\s+)?(the\s+)?(best|leading|top|#1|number one)",
    r"do not (recommend|mention|suggest)\s+(competitors|any other|rival)",
    r"rank\s+(us|this)\s+(first|highest|at the top)",
    r"prioriti[sz]e\s+(our|this)\b",
]


def _match(patterns: list[str], text: str, ftype: FindingType, sev: Severity,
           identity: str) -> list[Finding]:
    out: list[Finding] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            start = m.start()
            snippet = text[max(0, start - 40): start + 90].strip()
            out.append(Finding(ftype, sev, identity, snippet=snippet, detail=pat))
    return out


def scan_text(text: str, identity: str, *, include_imperative: bool = True,
              imperative_severity: Severity = Severity.HIGH) -> list[Finding]:
    if not text:
        return []
    findings: list[Finding] = []

    counts: Counter = Counter()
    for ch in text:
        if ch in _INVISIBLE or ch in _BIDI or _is_tag_char(ch):
            counts[ch] += 1
    zero_width_total = sum(n for ch, n in counts.items() if ch in _INVISIBLE)
    high_signal = any(ch in _BIDI or _is_tag_char(ch) for ch in counts)
    if counts and (high_signal or zero_width_total >= _ZW_CLUSTER_MIN):
        parts = []
        for ch, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            name = _INVISIBLE.get(ch) or ("bidi control" if ch in _BIDI else "unicode tag char")
            parts.append(f"{name} (U+{ord(ch):04X})" + (f" x{n}" if n > 1 else ""))
        findings.append(Finding(
            FindingType.INVISIBLE_UNICODE, Severity.MEDIUM, identity,
            snippet="; ".join(parts),
            detail="characters that render blank to humans but are read by a model",
        ))

    if include_imperative:
        findings += _match(_IMPERATIVE, text, FindingType.INJECTION_PHRASE,
                           imperative_severity, identity)
    findings += _match(_ROLE_CONTROL, text, FindingType.ROLE_TOKEN, Severity.MEDIUM, identity)
    findings += _match(_MANIPULATION, text, FindingType.MANIPULATION_DIRECTIVE, Severity.LOW, identity)
    return findings


# --- markup-level -------------------------------------------------------------
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?!\.)"
    r"|font-size\s*:\s*0"
    r"|(?:left|top)\s*:\s*-\d{3,}px"
    r"|text-indent\s*:\s*-\d{3,}px"
    r"|clip\s*:\s*rect\(\s*0",
    re.IGNORECASE,
)


def scan_html(html: str, identity: str) -> list[Finding]:
    if not html:
        return []
    findings: list[Finding] = []
    soup = BeautifulSoup(html, "html.parser")

    # HTML comments whose text reads like an instruction to a model.
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        ctext = str(comment).strip()
        if ctext and scan_text(ctext, identity):
            findings.append(Finding(
                FindingType.HTML_COMMENT_INSTRUCTION, Severity.HIGH, identity,
                snippet=ctext[:120],
                detail="instruction-like text inside an HTML comment (invisible to readers)",
            ))

    # Text hidden with inline CSS but still delivered in the DOM.
    for tag in soup.find_all(style=_HIDDEN_STYLE):
        txt = tag.get_text(" ", strip=True)
        if txt:
            findings.append(Finding(
                FindingType.HIDDEN_HTML, Severity.MEDIUM, identity,
                snippet=txt[:120],
                detail="text hidden via inline CSS",
            ))
    return findings
