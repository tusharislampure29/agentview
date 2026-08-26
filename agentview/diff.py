"""Turn raw HTML into comparable visible text and measure how two views differ."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

from .models import Divergence, FetchResult

_WS = re.compile(r"\s+")
# SequenceMatcher is roughly quadratic; cap the compared text so a batch scan of
# thousands of pages stays fast. 40k chars of visible text is a very long page.
_MAX_CHARS = 40_000

_STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")


def html_to_text(html: str) -> str:
    """Visible text only: scripts/styles removed, whitespace collapsed."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    return _WS.sub(" ", soup.get_text(separator=" ")).strip()


def similarity(a: str, b: str) -> float:
    """Visible-text similarity in [0, 1] (1.0 == identical)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:_MAX_CHARS], b[:_MAX_CHARS], autojunk=False).ratio()


def ai_only_text(human_text: str, ai_text: str) -> str:
    """The chunks present in the AI view but absent from the human view — i.e.
    exactly the content a site reveals only to an agent. This is where injected
    or manipulative instructions surface."""
    sm = SequenceMatcher(None, human_text[:_MAX_CHARS], ai_text[:_MAX_CHARS], autojunk=False)
    extra = [ai_text[j1:j2] for tag, _, _, j1, j2 in sm.get_opcodes() if tag in ("insert", "replace")]
    return " ".join(s.strip() for s in extra if s.strip())


def divergence(human: FetchResult, ai: FetchResult) -> Divergence:
    human_len = max(len(human.text), 1)
    return Divergence(
        identity=ai.identity,
        similarity=round(similarity(human.text, ai.text), 4),
        length_ratio=round(len(ai.text) / human_len, 4),
        status_differs=(human.status != ai.status),
        redirect_differs=(human.final_url != ai.final_url),
    )
