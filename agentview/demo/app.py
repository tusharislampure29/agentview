"""FastAPI demo — paste a URL, see it as a human vs as an AI agent, side by side.

Run it:  python -m agentview.demo         (or: uvicorn agentview.demo.app:app)

Because the server fetches a *user-supplied* URL, it is a classic SSRF surface.
Defence in depth:
  * the target host is validated up front (must resolve only to globally-routable
    addresses — no loopback/private/link-local/CGNAT/reserved space), and
  * the same check is attached as a request hook on every HTTP request the engine
    makes, so a redirect to an internal address is caught and refused too.
A residual DNS-rebinding window remains (the guard resolves a name, then httpx
resolves it again to connect); this demo is meant for local or trusted-network
deployment. Each client IP is also rate-limited.

For a public deployment, set ``AGENTVIEW_PUBLIC=1`` (see DEPLOY.md): it caps the
number of concurrent analyses (each one fans out ~15 outbound requests), tightens
the per-IP rate, and sheds load with a 503 rather than letting fan-out pile up. A
strict Content-Security-Policy is sent on every response. Even so, exposing an
arbitrary-URL fetcher to the internet carries the DNS-rebinding risk above; run it
behind the platform's egress controls, or lock it to the built-in examples.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse

from fastapi import FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from ..analyze import analyze_url
from ..serialize import report_to_dict
from .render import render_result
from .sample import sample_report
from .templates import render_page

app = FastAPI(title="agentview", docs_url=None, redoc_url=None)

# Per-fetch timeout for the interactive demo — tighter than the CLI/study default
# so the page stays responsive even when a target is slow.
DEMO_TIMEOUT = 12.0

# Only honour X-Forwarded-For when the server is behind a proxy you trust; without
# that, a client can spoof the header and defeat the rate limiter.
_TRUST_XFF = os.environ.get("AGENTVIEW_TRUST_XFF") == "1"

# Public-deployment hardening — opt in with AGENTVIEW_PUBLIC=1 (see DEPLOY.md).
# A single analysis fans out ~15 outbound GETs, so an open instance needs a hard
# ceiling on how many run at once and a tighter per-IP rate than a local run.
_PUBLIC = os.environ.get("AGENTVIEW_PUBLIC") == "1"
_MAX_CONCURRENCY = int(os.environ.get("AGENTVIEW_MAX_CONCURRENCY", "4" if _PUBLIC else "16"))
_BUSY_WAIT = 3.0        # seconds to wait for a free analysis slot before shedding load
_analysis_slots = asyncio.Semaphore(_MAX_CONCURRENCY)

_RATE: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60.0
_RATE_MAX = int(os.environ.get("AGENTVIEW_RATE_MAX", "6" if _PUBLIC else "12"))  # per IP / min
_RATE_SWEEP_EVERY = 500
_rate_calls = 0


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Lock the response down: the demo ships zero JavaScript and no remote assets,
    so a strict CSP costs nothing and blocks a whole class of injection."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    return resp


async def _analyze(target: str):
    """Run one analysis under the global concurrency cap. Returns ``None`` if every
    slot is busy for longer than ``_BUSY_WAIT`` so the caller can shed load instead
    of letting outbound fan-out pile up without bound."""
    try:
        await asyncio.wait_for(_analysis_slots.acquire(), timeout=_BUSY_WAIT)
    except asyncio.TimeoutError:
        return None
    try:
        return await run_in_threadpool(analyze_url, target, DEMO_TIMEOUT, True, _ssrf_guard)
    finally:
        _analysis_slots.release()


class UnsafeTargetError(Exception):
    """Raised by the request hook to abort a fetch aimed at a non-public address."""


def _client_ip(request: Request) -> str:
    if _TRUST_XFF:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _rate_ok(ip: str) -> bool:
    global _rate_calls
    now = time.monotonic()
    hits = [t for t in _RATE[ip] if now - t < _RATE_WINDOW]
    hits.append(now)
    _RATE[ip] = hits
    # Periodically drop IPs that have gone quiet so the table can't grow unbounded.
    _rate_calls += 1
    if _rate_calls % _RATE_SWEEP_EVERY == 0:
        for k in [k for k, v in _RATE.items() if not v or now - v[-1] >= _RATE_WINDOW]:
            del _RATE[k]
    return len(hits) <= _RATE_MAX


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Reject anything that isn't http(s) to a host that resolves *only* to
    globally-routable addresses — the SSRF gate. ``is_global`` is False for
    loopback/private/link-local/CGNAT/reserved/multicast/unspecified space."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "Only http/https URLs are supported."
    host = parsed.hostname
    if not host:
        return False, "Could not parse a hostname."
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return False, "Host does not resolve."
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # IPv4-mapped IPv6 (::ffff:a.b.c.d) can hide a private v4 — unwrap it.
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_reserved:
            return False, "Refusing to fetch a private / internal address."
    return True, ""


def _ssrf_guard(url: str) -> None:
    """Request-hook form of the gate: raise to abort a fetch (incl. a redirect)."""
    ok, why = is_safe_public_url(url)
    if not ok:
        raise UnsafeTargetError(why)


def _normalize(url: str) -> str:
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else "https://" + url


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, url: str | None = Query(default=None),
                demo: str | None = Query(default=None)):
    if demo:
        return HTMLResponse(render_page("(built-in synthetic example)",
                                        render_result(sample_report())))
    if not url:
        return HTMLResponse(render_page())

    target = _normalize(url)
    ok, why = is_safe_public_url(target)
    if not ok:
        return HTMLResponse(render_page(target, f'<div class="verdict verdict-error">'
                                                f'<b>blocked</b> — {why}</div>'))
    if not _rate_ok(_client_ip(request)):
        return HTMLResponse(render_page(target, '<div class="verdict verdict-error">'
                                                '<b>slow down</b> — rate limit reached, '
                                                'try again in a minute.</div>'))
    report = await _analyze(target)
    if report is None:
        return HTMLResponse(render_page(target, '<div class="verdict verdict-error">'
                                                '<b>server busy</b> — too many analyses in '
                                                'flight, try again in a moment.</div>'),
                            status_code=503)
    return HTMLResponse(render_page(target, render_result(report)))


@app.get("/api/check")
async def api_check(request: Request, url: str = Query(...)):
    """JSON endpoint — same engine, machine-readable output."""
    target = _normalize(url)
    ok, why = is_safe_public_url(target)
    if not ok:
        return JSONResponse({"error": why}, status_code=400)
    if not _rate_ok(_client_ip(request)):
        return JSONResponse({"error": "rate limit reached"}, status_code=429)
    report = await _analyze(target)
    if report is None:
        return JSONResponse({"error": "server busy, retry shortly"}, status_code=503)
    return JSONResponse(report_to_dict(report))


@app.get("/healthz")
async def healthz():
    return {"ok": True}
