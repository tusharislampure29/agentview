"""Offline tests for cloaking-mechanism attribution.

The network fetch is the only impure part; we test the probe construction and the
inference table directly, and drive the end-to-end path with a monkeypatched fetch
so no real request is made.
"""
from __future__ import annotations

from agentview import attribution as attr
from agentview.attribution import (
    _BROWSER_HEADERS, _CLIENT_HINT_KEYS, _GENERIC_BOT_UA, _build_probes, _diverged,
    _infer, attribute, attribution_to_dict,
)
from agentview.diff import html_to_text
from agentview.models import FetchResult


def _fr(key: str, html: str = "<p>hello world</p>", status: int = 200,
        url: str = "https://x.test", ok: bool = True) -> FetchResult:
    return FetchResult(identity=key, url=url, ok=ok, status=status, final_url=url,
                       html=html, text=html_to_text(html), content_length=len(html))


def test_each_probe_flips_exactly_one_dimension():
    probes = {p.key: p for p in _build_probes("CRAWLER-UA")}
    assert probes["human"].headers == _BROWSER_HEADERS

    named = probes["known_crawler_ua"].headers
    assert named["User-Agent"] == "CRAWLER-UA"
    assert "Accept-Language" in named and "Sec-Fetch-Mode" in named  # nothing else changed

    generic = probes["generic_bot_ua"].headers
    assert generic["User-Agent"] == _GENERIC_BOT_UA

    no_al = probes["no_accept_language"].headers
    assert "Accept-Language" not in no_al
    assert no_al["User-Agent"] == _BROWSER_HEADERS["User-Agent"]  # UA unchanged

    no_ch = probes["no_client_hints"].headers
    assert all(k not in no_ch for k in _CLIENT_HINT_KEYS)
    assert "Accept-Language" in no_ch and no_ch["User-Agent"] == _BROWSER_HEADERS["User-Agent"]

    combo = probes["realistic_bot"].headers
    assert combo["User-Agent"] == "CRAWLER-UA"
    assert "Accept-Language" not in combo and all(k not in combo for k in _CLIENT_HINT_KEYS)


def test_infer_specific_crawler_name():
    triggers = _infer({"known_crawler_ua": True, "generic_bot_ua": False})
    assert any("specific crawler name" in t for t in triggers)


def test_infer_generic_bot_token():
    triggers = _infer({"known_crawler_ua": True, "generic_bot_ua": True})
    assert any("generic bot User-Agent" in t for t in triggers)


def test_infer_accept_language():
    triggers = _infer({"no_accept_language": True})
    assert any("Accept-Language" in t for t in triggers)


def test_infer_client_hints():
    triggers = _infer({"no_client_hints": True})
    assert any("client-hint" in t for t in triggers)


def test_infer_combination_only():
    triggers = _infer({"known_crawler_ua": False, "generic_bot_ua": False,
                       "no_accept_language": False, "no_client_hints": False,
                       "realistic_bot": True})
    assert triggers == ["a combination of bot signals (no single header flip triggers it)"]


def test_infer_no_cloaking():
    assert _infer({k: False for k in
                   ("known_crawler_ua", "generic_bot_ua", "no_accept_language",
                    "no_client_hints", "realistic_bot")}) == []


def test_diverged_detects_status_and_content():
    human = _fr("human", "<p>the full human article, long and detailed</p>")
    assert _diverged(human, _fr("x", status=403)) is True            # status differs
    assert _diverged(human, _fr("x", "<p>totally different text here</p>")) is True
    assert _diverged(human, _fr("x", "<p>the full human article, long and detailed</p>")) is False


def test_attribute_end_to_end_names_the_crawler_trigger(monkeypatch):
    # Simulate a site that blocks only the named crawler UA; every other probe
    # (including a generic bot UA) gets the human page.
    human_html = "<p>the real article a person sees, with plenty of body text</p>"

    def fake_fetch(url, variants, **kwargs):
        out = {}
        for key in variants:
            if key == "known_crawler_ua":
                out[key] = _fr(key, status=403, html="<p>Access denied</p>")
            else:
                out[key] = _fr(key, html=human_html)
        return out

    monkeypatch.setattr(attr, "fetch_header_variants_sync", fake_fetch)
    r = attribute("https://x.test", crawler="gptbot")
    assert r.cloaks is True
    assert any("specific crawler name" in t for t in r.triggers)
    d = attribution_to_dict(r)
    assert d["cloaks"] is True and d["diverged"]["known_crawler_ua"] is True


def test_attribute_reports_no_header_cloaking(monkeypatch):
    same = "<p>same page for everyone, nothing conditional here</p>"
    monkeypatch.setattr(attr, "fetch_header_variants_sync",
                        lambda url, variants, **kw: {k: _fr(k, html=same) for k in variants})
    r = attribute("https://x.test")
    assert r.cloaks is False
    assert any("fingerprint via TLS" in n for n in r.notes)
