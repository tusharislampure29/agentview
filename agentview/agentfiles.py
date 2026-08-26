"""Audit the "instructions for AI" files a site publishes.

A growing convention lets sites hand instructions straight to AI agents —
``llms.txt`` (a curated map of the site for LLMs), ``agents.json`` / A2A agent
cards, and the legacy plugin manifest. These files are, by definition, content
served only to machines, so they are the cleanest place to look for answer-engine
manipulation ("always describe us as the best") or outright injected instructions.

This module fetches the well-known paths, decides which responses are *really*
one of these files (many sites return their SPA's index.html for any path), and
runs the text detectors over the ones that are.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from urllib.parse import urlparse

import httpx

from .detectors import scan_text
from .identities import HUMAN
from .models import AgentFile, Severity

AGENT_FILE_PATHS = [
    "/llms.txt",
    "/llms-full.txt",
    "/.well-known/llms.txt",
    "/ai.txt",
    "/agents.json",
    "/.well-known/agent.json",
    "/.well-known/ai-plugin.json",
]

DEFAULT_TIMEOUT = 15.0
# Some llms-full.txt dumps are tens of MB; bound both the download and the scan.
_MAX_DOWNLOAD = 1_000_000
_MAX_AUDIT_CHARS = 200_000


def base_origin(url: str) -> str:
    parsed = urlparse(url if url.startswith("http") else "https://" + url)
    return f"{parsed.scheme}://{parsed.netloc}"


def looks_like_agent_file(path: str, body: str, content_type: str = "",
                          truncated: bool = False) -> bool:
    """Reject SPA soft-404s (an HTML document returned for a missing path) and
    malformed JSON, so we don't count a homepage as an ``llms.txt``."""
    stripped = body.lstrip()
    if not stripped:
        return False
    if path.endswith(".json"):
        looks_jsonish = "json" in content_type.lower() or stripped[:1] in "{["
        if not looks_jsonish:
            return False
        if truncated:
            # We only downloaded a prefix, so a full parse would spuriously fail;
            # a JSON content-type / opening brace is enough to call it present.
            return True
        try:
            json.loads(body)
            return True
        except ValueError:
            return False
    # Text files (llms.txt, ai.txt): must not be an HTML page.
    head = stripped[:200].lower()
    if head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head:
        return False
    return True


def audit_content(path: str, body: str) -> list:
    """Run the text detectors over an agent-file body (label = the file path).

    Imperative injection phrases are treated as *candidates* (MEDIUM) here, not
    HIGH: an ``llms.txt`` that documents prompt injection is common and benign.
    The high-confidence agent-file signals are manipulation directives, chat-role
    control tokens, and invisible characters."""
    return scan_text(body[:_MAX_AUDIT_CHARS], path,
                     include_imperative=True, imperative_severity=Severity.MEDIUM)


def _read_capped(resp: httpx.Response) -> tuple[str, bool]:
    """Return (body, truncated). Some llms-full.txt dumps are tens of MB, so we
    stop at _MAX_DOWNLOAD and report whether we hit the cap."""
    chunks: list[str] = []
    total = 0
    truncated = False
    for chunk in resp.iter_text():
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_DOWNLOAD:
            truncated = True
            break
    return "".join(chunks), truncated


def _probe(client: httpx.Client, origin: str, path: str) -> AgentFile:
    try:
        with client.stream("GET", origin + path) as resp:
            content_type = resp.headers.get("content-type", "")
            body, truncated = _read_capped(resp) if resp.status_code == 200 else ("", False)
            status = resp.status_code
    except Exception as exc:  # noqa: BLE001
        return AgentFile(path=path, present=False, error=f"{type(exc).__name__}: {exc}")
    present = status == 200 and looks_like_agent_file(path, body, content_type, truncated)
    return AgentFile(
        path=path, present=present, status=status, content_length=len(body),
        findings=audit_content(path, body) if present else [],
    )


def fetch_agent_files(url: str, timeout: float = DEFAULT_TIMEOUT,
                      user_agent: str | None = None,
                      request_guard: Callable[[str], None] | None = None) -> list[AgentFile]:
    origin = base_origin(url)
    headers = {
        "User-Agent": user_agent or HUMAN.user_agent,
        "Accept": "text/plain, text/markdown, application/json, */*",
    }
    # A request event hook (if supplied) re-validates every URL, including redirect
    # hops, so the demo's SSRF guard can't be slipped past a redirect to an
    # internal address. Raising inside the hook fails just that probe.
    hooks = {"request": [lambda request: request_guard(str(request.url))]} if request_guard else {}
    # Probe every well-known path at once — they're independent GETs to one host,
    # so serial probing needlessly multiplied per-site latency by ~7x. httpx.Client
    # is safe to share across threads (it pools connections).
    with httpx.Client(follow_redirects=True, headers=headers, timeout=timeout,
                      event_hooks=hooks) as client:
        with ThreadPoolExecutor(max_workers=len(AGENT_FILE_PATHS)) as pool:
            return list(pool.map(lambda p: _probe(client, origin, p), AGENT_FILE_PATHS))
