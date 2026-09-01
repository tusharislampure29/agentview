"""Offline tests for CLI input parsing — notably robustness to a UTF-8 BOM.

A URL list or dataset saved by Notepad or PowerShell (`Set-Content -Encoding utf8`)
carries a leading BOM. Read as plain utf-8, that BOM glues onto the first line and
silently breaks the first URL / first JSON record. These pin the utf-8-sig fix.
"""
from __future__ import annotations

from agentview.cli import _load_records, _load_urls, _normalize_url


def test_normalize_url_adds_scheme_for_bare_host():
    assert _normalize_url("example.com") == "https://example.com"
    assert _normalize_url("  example.com/path  ") == "https://example.com/path"
    # already-schemed URLs are left alone
    assert _normalize_url("http://x.com") == "http://x.com"
    assert _normalize_url("https://x.com") == "https://x.com"


def test_load_urls_strips_utf8_bom(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_bytes(b"\xef\xbb\xbfhttps://example.com\nexample.org\n# a comment\n\n")
    urls = _load_urls(str(p))
    assert urls == ["https://example.com", "https://example.org"]
    assert not any("﻿" in u for u in urls)  # BOM never leaks into a URL


def test_load_urls_without_bom_and_scheme_prefixing(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text("https://a.com\nb.com\n", encoding="utf-8")
    assert _load_urls(str(p)) == ["https://a.com", "https://b.com"]


def test_load_records_strips_utf8_bom(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_bytes(b'\xef\xbb\xbf{"url":"https://a.com","verdict":"identical"}\n'
                  b'{"url":"https://b.com","verdict":"benign_divergence"}\n')
    recs = _load_records(str(p))
    assert [r["verdict"] for r in recs] == ["identical", "benign_divergence"]
