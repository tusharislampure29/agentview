"""Offline tests for the shared HTML view + the standalone `--html` report."""
from __future__ import annotations

from agentview.analyze import analyze_fetches
from agentview.demo.sample import sample_report
from agentview.diff import html_to_text
from agentview.htmlview import render_result, standalone_report
from agentview.models import FetchResult


def _fr(identity: str, html: str, rendered: bool = False, status: int = 200) -> FetchResult:
    return FetchResult(
        identity=identity, url="https://x.test", ok=True, status=status,
        final_url="https://x.test", html=html, text=html_to_text(html),
        content_length=len(html), rendered=rendered,
    )


def test_standalone_report_is_self_contained():
    doc = standalone_report(sample_report(), "https://vpn-review.test")
    assert doc.startswith("<!doctype html>")
    assert "<style>" in doc                       # CSS is inline — no external asset
    assert "http" not in doc.split("<style>")[1].split("</style>")[0]  # no remote urls in CSS
    assert "verdict-adversarial" in doc           # the sample's verdict banner
    assert "TurboShield" in doc                   # the injected brand shows in the AI column
    assert "vpn-review.test" in doc               # the subject URL is shown


def test_standalone_report_includes_subtitle():
    doc = standalone_report(sample_report(), "https://x.test", subtitle="generated 2026-01-01")
    assert "generated 2026-01-01" in doc


def test_render_result_labels_a_rendered_human_baseline():
    body = "<p>" + "real independent review content " * 20 + "</p>"
    report = analyze_fetches(
        "https://x.test",
        {"human": _fr("human", body, rendered=True), "gptbot": _fr("gptbot", body)},
    )
    assert "rendered DOM" in render_result(report)
