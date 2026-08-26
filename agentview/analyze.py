"""Combine fetch + diff + detectors into one SiteReport with a single Verdict.

Core principle: a finding only counts if it is **differential** — content the
site shows an AI agent but *not* the human. Text that's hidden (or invisible, or
instruction-like) but served identically to humans and bots is normal page
plumbing, not agent-targeting, so it is subtracted out. This is what keeps the
false-positive rate honest.
"""
from __future__ import annotations

from typing import Callable

from .agentfiles import fetch_agent_files
from .detectors import scan_html, scan_text
from .diff import ai_only_text, divergence
from .fetch import fetch_all_identities_sync
from .identities import AI_IDENTITIES
from .models import (
    DIVERGENCE_THRESHOLD, AgentFile, FetchResult, Finding, FindingType, Severity,
    SiteReport, Verdict,
)

# Human visible text shorter than this can't serve as a diff baseline: everything
# in the AI view would look "AI-only" and every ordinary phrase would false-flag.
_MIN_BASELINE_CHARS = 200


def _sig(f: Finding) -> tuple:
    """Identity-independent signature, so a signal in the human view can cancel
    the same signal in an AI view."""
    return (f.type, f.snippet, f.detail)


def analyze_fetches(url: str, fetches: dict[str, FetchResult],
                    agent_files: list[AgentFile] | None = None) -> SiteReport:
    """Pure function over already-collected fetches — no network, easy to test."""
    report = SiteReport(url=url, fetches=fetches, agent_files=agent_files or [])
    human = fetches.get("human")

    # Baseline: markup-level signals the human is *also* served. Anything in here
    # is not agent-targeted and gets subtracted from every AI view.
    human_baseline: set[tuple] = set()
    if human and human.ok:
        human_baseline = {_sig(f) for f in scan_html(human.html, "human")}

    # A thin human view (empty page, JS-only shell) can't anchor a text diff. But
    # a page that is merely *short* is fine as long as the AI view mostly mirrors
    # it — the risky case is thin AND low-similarity, where the human shares almost
    # nothing with the AI page, so every phrase in it would look "AI-only".
    human_thin = bool(human and human.ok and len(human.text) < _MIN_BASELINE_CHARS)
    skipped_thin = False

    any_divergent = False
    for ai in AI_IDENTITIES:
        fr = fetches.get(ai.key)
        if fr is None:
            continue
        if not fr.ok:
            if human and human.ok:
                report.notes.append(f"{ai.key}: fetch failed ({fr.error})")
            continue

        if human and human.ok:
            d = divergence(human, fr)
            report.divergences.append(d)
            if d.similarity < DIVERGENCE_THRESHOLD or d.status_differs or d.redirect_differs:
                any_divergent = True
            # Scan exactly the visible text shown to the agent but not the human.
            # Skip only when the human baseline is thin AND subtracting it removed
            # almost nothing (ai_only ≈ the whole AI page) — that's a JS-shell/empty
            # baseline where every phrase would look "AI-only". A short page the AI
            # extends with an injection still has most of itself subtracted, so it
            # is scanned and caught.
            ai_only = ai_only_text(human.text, fr.text)
            if human_thin and fr.text and len(ai_only) >= 0.9 * len(fr.text):
                skipped_thin = True
            else:
                report.findings += scan_text(ai_only, ai.key)

        # Markup-level signals unique to this AI view (not in the human baseline).
        for f in scan_html(fr.html, ai.key):
            if _sig(f) not in human_baseline:
                report.findings.append(f)

    if skipped_thin:
        report.notes.append("human baseline too thin to diff visible text for some "
                            "AI views; text-level findings may be undercounted")

    report.verdict = _verdict(report, human, any_divergent)
    return report


def _verdict(report: SiteReport, human: FetchResult | None, any_divergent: bool) -> Verdict:
    if human is None or not human.ok:
        report.notes.append("no successful human fetch to compare against")
        return Verdict.ERROR
    # An agent-instruction file (llms.txt, agents.json) is agent-facing by
    # definition, so its findings count toward the verdict alongside the
    # differential page findings.
    all_findings = report.findings + [f for af in report.agent_files for f in af.findings]
    if any(f.severity is Severity.HIGH for f in all_findings):
        return Verdict.ADVERSARIAL
    if any(f.type is FindingType.MANIPULATION_DIRECTIVE for f in all_findings):
        return Verdict.MANIPULATIVE
    if any_divergent or all_findings:
        return Verdict.BENIGN_DIVERGENCE
    return Verdict.IDENTICAL


def analyze_url(url: str, timeout: float = 20.0, include_agent_files: bool = True,
                request_guard: Callable[[str], None] | None = None) -> SiteReport:
    fetches = fetch_all_identities_sync(url, timeout=timeout, request_guard=request_guard)
    agent_files = (fetch_agent_files(url, timeout=min(timeout, 15.0), request_guard=request_guard)
                   if include_agent_files else [])
    return analyze_fetches(url, fetches, agent_files)
