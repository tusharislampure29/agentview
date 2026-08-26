"""Fetch one URL under every identity, concurrently and under identical conditions."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

import httpx

from .diff import html_to_text
from .identities import IDENTITIES, Identity
from .models import FetchResult

DEFAULT_TIMEOUT = 20.0
# Cap stored HTML so a pathological page can't blow up memory during a batch scan.
_MAX_HTML = 2_000_000

# An optional per-request URL check. Called for *every* request httpx makes,
# including redirect hops, before it goes out; raising aborts that request. The
# demo passes one to keep redirects from reaching internal addresses (SSRF).
RequestGuard = Callable[[str], None]


def _hooks(guard: RequestGuard | None) -> dict:
    if guard is None:
        return {}

    async def _check(request: httpx.Request) -> None:
        # The guard does a blocking DNS lookup; keep it off the event loop.
        await asyncio.get_running_loop().run_in_executor(None, guard, str(request.url))

    return {"request": [_check]}


async def _fetch_one(client: httpx.AsyncClient, url: str, identity: Identity,
                     timeout: float) -> FetchResult:
    headers = {
        "User-Agent": identity.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        **identity.extra_headers,
    }
    start = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        html = resp.text[:_MAX_HTML]
        return FetchResult(
            identity=identity.key,
            url=url,
            ok=True,
            status=resp.status_code,
            final_url=str(resp.url),
            redirects=len(resp.history),
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            html=html,
            text=html_to_text(html),
            content_length=len(resp.content),
        )
    except Exception as exc:  # noqa: BLE001 — record every failure mode, never raise
        return FetchResult(
            identity=identity.key, url=url, ok=False,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )


async def fetch_all_identities(url: str, identities: list[Identity] | None = None,
                               timeout: float = DEFAULT_TIMEOUT,
                               request_guard: RequestGuard | None = None) -> dict[str, FetchResult]:
    ids = identities or IDENTITIES
    # A fresh client per URL means no cookies or connection state carry between
    # identities — the only thing that varies is the User-Agent.
    async with httpx.AsyncClient(verify=True, event_hooks=_hooks(request_guard)) as client:
        results = await asyncio.gather(*(_fetch_one(client, url, i, timeout) for i in ids))
    return {r.identity: r for r in results}


def fetch_all_identities_sync(url: str, **kwargs) -> dict[str, FetchResult]:
    return asyncio.run(fetch_all_identities(url, **kwargs))
