"""Optional JS-rendered human baseline (headless Chromium via Playwright).

Why this exists
---------------
agentview's core compares *raw served HTML*. That is honest but blind in one
direction: a modern site renders itself with JavaScript, so the HTML a person
actually reads is the **post-JS DOM**, not the shell the server first sends. Two
real situations slip past a raw-HTML baseline:

1. **SPA shells.** A React/Vue site serves everyone a near-empty shell and paints
   the content client-side. Raw-HTML human and raw-HTML bot both look empty, so a
   diff sees nothing — even if the site cloaks.
2. **JS that removes bot-bait.** A page ships an injected/hidden block in its raw
   HTML but a script strips it before a human ever sees it. A raw-HTML baseline
   *also* contains that block, so the differential rule wrongly cancels it. A
   rendered baseline does not — the block correctly surfaces as agent-only.

So the "human" view can optionally be a real headless-Chromium render: the DOM a
person sees after JS runs. The AI views stay raw HTML, because that is what the
crawlers actually consume — GPTBot, ClaudeBot and friends do not execute
JavaScript. That asymmetry (rendered human vs raw bot) is exactly the real-world
comparison, and it makes the differential detection *stronger*, not noisier.

Design constraints
------------------
* **Optional.** Playwright is a heavy dependency (a browser binary). The engine
  must import and run with only ``httpx`` + ``beautifulsoup4``; this module
  lazy-imports Playwright and degrades with a clear message if it is absent.
* **Consistent text.** The rendered DOM is reduced to visible text with the *same*
  :func:`html_to_text` normalizer used everywhere else, so an identical DOM yields
  identical text and never invents a spurious diff.
* **Testable offline.** Everything downstream takes an injectable ``Renderer``
  callable, so the swap-in logic is unit-tested with a fake renderer and no
  browser. The Playwright path is exercised via an opt-in integration marker.

Note: this is a CLI power-feature. It is intentionally *not* wired into the public
web demo — rendering an attacker-supplied URL in a real browser is a far larger
SSRF/abuse surface than a plain HTTP GET.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .diff import html_to_text
from .identities import HUMAN
from .models import FetchResult

# Best-effort wait (ms) for client-side rendering to settle after the initial DOM
# is parsed. Many live sites never reach true network-idle (analytics, polling),
# so this is a cap we happily hit, not a requirement.
_NETWORKIDLE_CAP_MS = 8_000


@dataclass
class RenderedPage:
    """The outcome of rendering one URL in a headless browser."""
    ok: bool
    html: str = ""
    text: str = ""
    status: int | None = None
    final_url: str | None = None
    elapsed_ms: int = 0
    error: str | None = None


# A renderer takes (url, timeout_seconds) and returns a RenderedPage. Injectable so
# the analysis layer can be tested with a fake and never needs a real browser.
Renderer = Callable[[str, float], RenderedPage]


class RendererUnavailable(RuntimeError):
    """Raised when a real render is requested but Playwright/Chromium is missing."""


def is_available() -> bool:
    """True if Playwright is importable (the browser binary is checked at launch)."""
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


INSTALL_HINT = (
    'JS rendering needs Playwright + Chromium. Install with:\n'
    '    pip install "agentview[render]"\n'
    '    python -m playwright install chromium'
)


def render_with_playwright(url: str, timeout: float = 20.0) -> RenderedPage:
    """Render ``url`` as a human would see it: launch headless Chromium under the
    human User-Agent, wait for client-side rendering to settle, and return the
    post-JS DOM plus its visible text.

    Raises :class:`RendererUnavailable` if Playwright isn't installed. Any other
    failure (navigation error, timeout) is captured in ``RenderedPage.error`` with
    ``ok=False`` — a render failure must never abort the wider analysis.
    """
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError as exc:  # pragma: no cover - exercised via is_available()
        raise RendererUnavailable(INSTALL_HINT) from exc

    start = time.perf_counter()
    timeout_ms = int(timeout * 1000)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=HUMAN.user_agent,
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                page = context.new_page()
                resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Give client-side rendering a beat; best-effort, capped.
                try:
                    page.wait_for_load_state(
                        "networkidle", timeout=min(timeout_ms, _NETWORKIDLE_CAP_MS)
                    )
                except PlaywrightTimeoutError:
                    pass
                html = page.content()
                return RenderedPage(
                    ok=True,
                    html=html,
                    text=html_to_text(html),
                    status=resp.status if resp else None,
                    final_url=page.url,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                )
            finally:
                browser.close()
    except RendererUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — surface any render failure as data
        name = type(exc).__name__
        return RenderedPage(
            ok=False,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            error=f"{name}: {exc}",
        )


def rendered_human_result(url: str, rendered: RenderedPage) -> FetchResult:
    """Wrap a successful render as a ``human`` FetchResult so it drops straight into
    the existing pipeline in place of the raw-HTML human view."""
    return FetchResult(
        identity=HUMAN.key,
        url=url,
        ok=rendered.ok,
        status=rendered.status,
        final_url=rendered.final_url or url,
        redirects=0,
        elapsed_ms=rendered.elapsed_ms,
        html=rendered.html,
        text=rendered.text,
        content_length=len(rendered.html.encode("utf-8", "ignore")),
        error=rendered.error,
        rendered=True,
    )
