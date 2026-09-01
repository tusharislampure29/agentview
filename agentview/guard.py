"""agentview guard — sanitize page content *before* it reaches an LLM.

agentview's measurement side answers "does this site serve agents something
different?" The guard is the defensive side, and the reason the project is a tool
rather than only a study: given HTML your own agent is about to drop into a model's
context (a web-browsing tool, a RAG ingest, an RSS-to-LLM pipeline), it strips the
payloads that target the model and hands back clean text plus a report of exactly
what it removed.

What it removes by default is the content that is **delivered to the model but
withheld from a human** — invisible-unicode smuggling, CSS-hidden blocks,
instruction-bearing HTML comments — plus chat-template control tokens that try to
break out of the surrounding prompt framing. Those are unambiguous: a human never
sees them, so they are not page content, they are aimed at the reader-that-is-a-model.

Injection *phrases* in visible prose ("ignore previous instructions") are a
different case: they also appear in legitimate writing *about* prompt injection
(docs, security blogs, this very file). So the guard **flags** them but leaves them
in place, unless you opt into ``aggressive`` mode — that way a security article
isn't gutted while a smuggled payload still gets stripped.

The whole module is pure and dependency-light (bs4, stdlib): ``sanitize(html)`` is
a plain function, easy to drop into a pipeline and easy to test offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment

# Reuse the *exact* detection patterns and character sets the scanner uses, so the
# guard and the measurement side can never drift apart — one source of truth for
# "what is agent-targeted content".
from .detectors import (
    _HIDDEN_STYLE, _IMPERATIVE, _MANIPULATION, _ROLE_CONTROL,
    char_name, is_smuggling_char, scan_text,
)
from .diff import _STRIP_TAGS, _WS, html_to_text
from .models import FindingType

REDACTION = "[removed by agentview]"


@dataclass
class Removal:
    """One thing the guard stripped, with enough context to audit the decision."""
    kind: str          # invisible_unicode | hidden_html | html_comment | control_token | ...
    snippet: str       # what was removed (truncated)
    reason: str


@dataclass
class Flag:
    """Suspicious *visible* content the guard left in place for the caller to judge."""
    kind: str
    snippet: str


@dataclass
class GuardResult:
    """The sanitized text plus a full account of what changed."""
    text: str
    removed: list[Removal] = field(default_factory=list)
    flagged: list[Flag] = field(default_factory=list)
    invisible_chars_removed: int = 0
    hidden_blocks_removed: int = 0
    comments_removed: int = 0
    original_text_len: int = 0
    clean_text_len: int = 0

    @property
    def is_clean(self) -> bool:
        """True when nothing dangerous was removed or flagged."""
        return not self.removed and not self.flagged

    @property
    def modified(self) -> bool:
        """True when the guard changed the text at all."""
        return bool(self.removed)


def _redact(text: str, patterns: list[str]) -> tuple[str, list[str]]:
    """Replace every match of any pattern with the redaction marker; return the
    cleaned text and the raw snippets that were removed."""
    hits: list[str] = []

    def repl(m: re.Match) -> str:
        hits.append(m.group(0))
        return REDACTION

    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    return text, hits


def _strip_invisible(text: str) -> tuple[str, int, str]:
    """Drop every smuggling character; return (clean_text, count, sample_names)."""
    kept: list[str] = []
    removed = 0
    names: list[str] = []
    for ch in text:
        if is_smuggling_char(ch):
            removed += 1
            label = f"{char_name(ch)} (U+{ord(ch):04X})"
            if label not in names and len(names) < 6:
                names.append(label)
        else:
            kept.append(ch)
    return "".join(kept), removed, "; ".join(names)


def sanitize(html: str, *, aggressive: bool = False) -> GuardResult:
    """Sanitize a page's HTML into text safe to feed an LLM.

    Always removed: non-content tags (script/style/…), HTML comments, CSS-hidden
    blocks, invisible/control unicode, and chat-template control tokens.

    Visible injection phrases and answer-engine manipulation directives are
    *flagged* by default and *redacted* when ``aggressive=True``.
    """
    result = GuardResult(text="")
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    # 1. Non-content tags never belong in a model's context.
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()

    # 2. HTML comments: invisible to readers, useless to a model, a classic vector.
    #    Remove them all; surface the ones that carried instruction-like text.
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        ctext = str(comment).strip()
        result.comments_removed += 1
        if ctext and scan_text(ctext, "guard"):
            result.removed.append(Removal(
                "html_comment", ctext[:160],
                "instruction-like text inside an HTML comment (invisible to readers)",
            ))
        comment.extract()

    # 3. CSS-hidden blocks: text delivered to the model but hidden from the human.
    for tag in soup.find_all(style=_HIDDEN_STYLE):
        txt = tag.get_text(" ", strip=True)
        if txt:
            result.hidden_blocks_removed += 1
            result.removed.append(Removal(
                "hidden_html", txt[:160], "text hidden from humans via inline CSS",
            ))
        tag.decompose()

    text = _WS.sub(" ", soup.get_text(separator=" ")).strip()

    # 4. Invisible / control unicode surviving in the visible text.
    text, n_invisible, sample = _strip_invisible(text)
    if n_invisible:
        result.invisible_chars_removed = n_invisible
        result.removed.append(Removal(
            "invisible_unicode", sample,
            f"{n_invisible} character(s) that render blank to a human but are read by a model",
        ))

    # 5. Chat-template control tokens — almost never legitimate prose; always redact.
    text, control_hits = _redact(text, _ROLE_CONTROL)
    for snip in control_hits:
        result.removed.append(Removal("control_token", snip[:160],
                                      "chat-template control token"))

    # 6. Visible injection phrases + manipulation directives: flag, or redact if asked.
    if aggressive:
        text, imp_hits = _redact(text, _IMPERATIVE)
        for snip in imp_hits:
            result.removed.append(Removal("injection_phrase", snip[:160],
                                          "imperative override (redacted in aggressive mode)"))
        text, man_hits = _redact(text, _MANIPULATION)
        for snip in man_hits:
            result.removed.append(Removal("manipulation_directive", snip[:160],
                                          "answer-engine steering (redacted in aggressive mode)"))
    else:
        for f in scan_text(text, "guard"):
            if f.type is FindingType.INJECTION_PHRASE:
                result.flagged.append(Flag("injection_phrase", f.snippet[:160]))
            elif f.type is FindingType.MANIPULATION_DIRECTIVE:
                result.flagged.append(Flag("manipulation_directive", f.snippet[:160]))

    result.text = text.strip()
    # Baseline is the *visible* text (scripts/styles already excluded), so the
    # before→after delta reflects sanitized content, not markup we'd drop anyway.
    result.original_text_len = len(html_to_text(html))
    result.clean_text_len = len(result.text)
    return result


def guard_result_to_dict(r: GuardResult) -> dict:
    """JSON-serializable view for the CLI and for programmatic callers."""
    return {
        "clean_text": r.text,
        "is_clean": r.is_clean,
        "modified": r.modified,
        "stats": {
            "original_text_len": r.original_text_len,
            "clean_text_len": r.clean_text_len,
            "invisible_chars_removed": r.invisible_chars_removed,
            "hidden_blocks_removed": r.hidden_blocks_removed,
            "comments_removed": r.comments_removed,
            "removed_count": len(r.removed),
            "flagged_count": len(r.flagged),
        },
        "removed": [{"kind": x.kind, "snippet": x.snippet, "reason": x.reason} for x in r.removed],
        "flagged": [{"kind": x.kind, "snippet": x.snippet} for x in r.flagged],
    }
