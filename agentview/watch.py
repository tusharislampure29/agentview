"""Longitudinal watch — a cloaking canary.

A single `check` is a snapshot. But agent cloaking is a *change*: a site that
served everyone the same page yesterday can start poisoning the bot's view today,
silently, on a 200 OK. `watch` turns agentview into a monitor. Point it at a list
of URLs on a schedule; it keeps a small local snapshot of each site's verdict and
signals, and on every run reports only what *changed* since last time — and whether
the change is an **escalation** (the site got more agent-targeting).

That's the alerting primitive nobody had for this threat: run it from cron with
``--fail-on-escalation`` and a site flipping ``identical -> adversarial`` becomes a
nonzero exit you can page on.

State is a plain JSON file (default ``.agentview-watch.json``). The analyzer is
injected, so the diff logic is unit-tested offline with canned reports and never
touches the network.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .models import DIVERGENCE_THRESHOLD, SiteReport

# Ordering of verdicts from benign to hostile, so we can tell an escalation (things
# got worse) from a de-escalation (a site stopped cloaking).
_VERDICT_RANK = {
    "error": 0, "identical": 1, "benign_divergence": 2,
    "manipulative": 3, "adversarial": 4,
}


@dataclass
class Snapshot:
    url: str
    verdict: str
    finding_types: dict[str, int] = field(default_factory=dict)
    agent_files: list[str] = field(default_factory=list)
    agent_file_findings: int = 0
    divergent_bots: list[str] = field(default_factory=list)
    checked_at: str = ""


@dataclass
class Change:
    url: str
    kind: str        # verdict | findings | agent_files | divergence | unreachable
    detail: str
    escalation: bool = False


@dataclass
class WatchRun:
    baselined: list[str] = field(default_factory=list)   # first-seen URLs
    unchanged: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)

    @property
    def escalations(self) -> list[Change]:
        return [c for c in self.changes if c.escalation]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def snapshot_from_report(report: SiteReport) -> Snapshot:
    """Reduce a full SiteReport to the stable signals we track over time."""
    types: dict[str, int] = {}
    for f in report.findings:
        types[f.type.value] = types.get(f.type.value, 0) + 1
    af_findings = 0
    for af in report.agent_files:
        for f in af.findings:
            types[f.type.value] = types.get(f.type.value, 0) + 1
            af_findings += 1
    divergent = [
        d.identity for d in report.divergences
        if d.similarity < DIVERGENCE_THRESHOLD or d.status_differs or d.redirect_differs
    ]
    return Snapshot(
        url=report.url,
        verdict=report.verdict.value,
        finding_types=types,
        agent_files=sorted(af.path for af in report.agent_files if af.present),
        agent_file_findings=af_findings,
        divergent_bots=sorted(divergent),
        checked_at=_now_iso(),
    )


def diff_snapshots(old: Snapshot, new: Snapshot) -> list[Change]:
    """Human-readable changes from ``old`` to ``new`` (empty when nothing tracked moved)."""
    changes: list[Change] = []

    if old.verdict != new.verdict:
        up = _VERDICT_RANK.get(new.verdict, 0) > _VERDICT_RANK.get(old.verdict, 0)
        changes.append(Change(new.url, "verdict",
                              f"verdict {old.verdict} -> {new.verdict}", escalation=up))

    new_types = [t for t in new.finding_types if t not in old.finding_types]
    if new_types:
        changes.append(Change(new.url, "findings",
                              f"new signal type(s): {', '.join(sorted(new_types))}",
                              escalation=True))

    new_files = [p for p in new.agent_files if p not in old.agent_files]
    if new_files:
        changes.append(Change(new.url, "agent_files",
                              f"new agent-instruction file(s): {', '.join(new_files)}"))
    if new.agent_file_findings > old.agent_file_findings:
        changes.append(Change(new.url, "agent_files",
                              f"agent-file findings {old.agent_file_findings} -> "
                              f"{new.agent_file_findings}", escalation=True))

    new_bots = [b for b in new.divergent_bots if b not in old.divergent_bots]
    if new_bots:
        changes.append(Change(new.url, "divergence",
                              f"newly served a different page to: {', '.join(new_bots)}",
                              escalation=True))
    return changes


# --- state file ---------------------------------------------------------------
def load_state(path: str) -> dict[str, Snapshot]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {url: Snapshot(**snap) for url, snap in raw.items()}


def save_state(path: str, state: dict[str, Snapshot]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({url: asdict(snap) for url, snap in state.items()}, fh,
                  indent=2, ensure_ascii=False)


Analyzer = Callable[[str], SiteReport]


def watch_once(urls: list[str], state_path: str, analyzer: Analyzer) -> WatchRun:
    """Analyze each URL, diff against the stored snapshot, persist, and report."""
    state = load_state(state_path)
    run = WatchRun()

    for url in urls:
        try:
            report = analyzer(url)
        except Exception as exc:  # noqa: BLE001 — a bad URL must not sink the batch
            run.changes.append(Change(url, "unreachable", f"analysis failed: {exc}"))
            continue

        new = snapshot_from_report(report)
        old = state.get(url)
        if old is None:
            run.baselined.append(url)
        else:
            diffs = diff_snapshots(old, new)
            if diffs:
                run.changes.extend(diffs)
            else:
                run.unchanged.append(url)
        state[url] = new

    save_state(state_path, state)
    return run
