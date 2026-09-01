"""Cloaking-mechanism attribution — *why* does a site serve the bot a different page?

`check` answers *whether* a site cloaks. This answers *how* it decides you're a bot.
A site that serves agents a different page must be keying on something in the
request. By flipping one request attribute at a time from browser-like toward
bot-like — and seeing which flip makes the response diverge from the human
baseline — we can attribute the trigger:

* the **specific crawler name** (e.g. it singles out "GPTBot"),
* any **generic bot User-Agent** (it keys on the substring "bot"),
* a **missing Accept-Language** header (browsers always send one; many bots don't),
* **missing browser client-hints** (Sec-Fetch-*, Upgrade-Insecure-Requests).

Each probe changes exactly one dimension from the human baseline, plus one
"realistic bot" probe that changes all of them — so if no single flip triggers the
cloak but the combined one does, we can say it needs a *combination* of signals.

Like the rest of agentview this is a lower bound: a site that fingerprints via TLS,
IP reputation, or a JavaScript challenge will look "no header-based cloaking" here
even though it cloaks. We say so rather than implying the list is exhaustive.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .diff import divergence
from .fetch import fetch_header_variants_sync
from .identities import HUMAN, by_key
from .models import DIVERGENCE_THRESHOLD, FetchResult

# What a real desktop Chrome sends. Probes start from this and remove/replace parts.
_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": HUMAN.user_agent,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}

# A UA that is clearly a bot but is *not* one of the named AI crawlers — lets us tell
# "keys on the word bot" apart from "keys on the specific crawler name".
_GENERIC_BOT_UA = "Mozilla/5.0 (compatible; ExampleBot/1.0; +https://example.com/bot)"

_CLIENT_HINT_KEYS = ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User",
                     "Sec-Fetch-Dest", "Upgrade-Insecure-Requests")


@dataclass
class Probe:
    key: str
    label: str
    dimension: str          # which single attribute this flips (or "combined")
    headers: dict[str, str]


@dataclass
class AttributionResult:
    url: str
    crawler_key: str                       # the named crawler UA used for the bot probes
    diverged: dict[str, bool] = field(default_factory=dict)   # probe key -> diverged vs human?
    triggers: list[str] = field(default_factory=list)         # human-readable mechanisms
    probes: dict[str, FetchResult] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)      # probe key -> display label
    notes: list[str] = field(default_factory=list)

    @property
    def cloaks(self) -> bool:
        return bool(self.triggers)


def _build_probes(crawler_ua: str) -> list[Probe]:
    def variant(**changes) -> dict[str, str]:
        h = dict(_BROWSER_HEADERS)
        for k, v in changes.items():
            h[k] = v
        return h

    def without(*keys: str, **changes) -> dict[str, str]:
        h = variant(**changes)
        for k in keys:
            h.pop(k, None)
        return h

    return [
        Probe("human", "browser baseline", "none", dict(_BROWSER_HEADERS)),
        Probe("known_crawler_ua", "named crawler UA only", "user_agent_named",
              variant(**{"User-Agent": crawler_ua})),
        Probe("generic_bot_ua", "generic 'bot' UA only", "user_agent_generic",
              variant(**{"User-Agent": _GENERIC_BOT_UA})),
        Probe("no_accept_language", "no Accept-Language only", "accept_language",
              without("Accept-Language")),
        Probe("no_client_hints", "no browser client-hints only", "client_hints",
              without(*_CLIENT_HINT_KEYS)),
        Probe("realistic_bot", "named crawler UA + no client-hints/Accept-Language",
              "combined",
              without("Accept-Language", *_CLIENT_HINT_KEYS, **{"User-Agent": crawler_ua})),
    ]


def _diverged(human: FetchResult, other: FetchResult) -> bool:
    if not other.ok:
        # A failure only counts as divergence if the human fetch itself succeeded.
        return human.ok
    d = divergence(human, other)
    return d.similarity < DIVERGENCE_THRESHOLD or d.status_differs or d.redirect_differs


def _infer(diverged: dict[str, bool]) -> list[str]:
    """Map which probes diverged to human-readable trigger(s)."""
    triggers: list[str] = []
    named = diverged.get("known_crawler_ua", False)
    generic = diverged.get("generic_bot_ua", False)

    if named and generic:
        triggers.append("a generic bot User-Agent (any UA containing a bot token)")
    elif named and not generic:
        triggers.append("the specific crawler name in the User-Agent "
                        "(a generic bot UA is served the human page)")
    elif generic and not named:
        triggers.append("a bot-like User-Agent (but not this specific crawler name)")

    if diverged.get("no_accept_language"):
        triggers.append("a missing Accept-Language header")
    if diverged.get("no_client_hints"):
        triggers.append("missing browser client-hint headers (Sec-Fetch-*, "
                        "Upgrade-Insecure-Requests)")

    # If nothing single-dimensional fired but the realistic bot did, it's a combo.
    if not triggers and diverged.get("realistic_bot"):
        triggers.append("a combination of bot signals (no single header flip triggers it)")
    return triggers


def attribute(url: str, crawler: str = "gptbot", timeout: float = 20.0,
              request_guard=None) -> AttributionResult:
    """Probe ``url`` to attribute what request attribute a cloaking site keys on."""
    ident = by_key(crawler)
    crawler_ua = ident.user_agent if ident else _GENERIC_BOT_UA
    probes = _build_probes(crawler_ua)
    variants = {p.key: p.headers for p in probes}
    fetched = fetch_header_variants_sync(url, variants, timeout=timeout,
                                         request_guard=request_guard)

    result = AttributionResult(url=url, crawler_key=crawler, probes=fetched,
                               labels={p.key: p.label for p in probes})
    human = fetched.get("human")
    if human is None or not human.ok:
        result.notes.append("no successful browser-baseline fetch to compare against")
        return result

    for p in probes:
        if p.key == "human":
            continue
        fr = fetched.get(p.key)
        result.diverged[p.key] = _diverged(human, fr) if fr else False

    result.triggers = _infer(result.diverged)
    if not result.triggers:
        result.notes.append("no User-Agent/header-based cloaking detected — the site may "
                            "still fingerprint via TLS, IP reputation, or a JS challenge, "
                            "which this prober cannot see")
    return result


def attribution_to_dict(r: AttributionResult) -> dict:
    return {
        "url": r.url,
        "crawler": r.crawler_key,
        "cloaks": r.cloaks,
        "triggers": r.triggers,
        "diverged": r.diverged,
        "probes": {
            k: {"ok": fr.ok, "status": fr.status, "content_length": fr.content_length,
                "error": fr.error}
            for k, fr in r.probes.items()
        },
        "notes": r.notes,
    }
