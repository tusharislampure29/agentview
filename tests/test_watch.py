"""Offline tests for the longitudinal watch (cloaking canary).

Reports are built by hand and the analyzer is a plain function, so the snapshot
reduction, the change diff, and the state round-trip are all tested with no network.
"""
from __future__ import annotations

from agentview.models import (
    AgentFile, Divergence, Finding, FindingType, Severity, SiteReport, Verdict,
)
from agentview.watch import (
    Snapshot, diff_snapshots, load_state, save_state, snapshot_from_report, watch_once,
)


def _report(url, verdict, findings=None, agent_files=None, divergences=None) -> SiteReport:
    return SiteReport(url=url, verdict=verdict, findings=findings or [],
                      agent_files=agent_files or [], divergences=divergences or [])


def _finding(ftype=FindingType.INJECTION_PHRASE) -> Finding:
    return Finding(ftype, Severity.HIGH, "gptbot", snippet="ignore previous instructions")


def _divergent(identity="gptbot") -> Divergence:
    return Divergence(identity=identity, similarity=0.2, length_ratio=1.5,
                      status_differs=False, redirect_differs=False)


def test_snapshot_reduces_a_report():
    rep = _report(
        "https://x.test", Verdict.ADVERSARIAL,
        findings=[_finding()],
        agent_files=[AgentFile(path="/llms.txt", present=True, findings=[_finding(FindingType.MANIPULATION_DIRECTIVE)])],
        divergences=[_divergent("gptbot"), _divergent("claudebot")],
    )
    snap = snapshot_from_report(rep)
    assert snap.verdict == "adversarial"
    assert snap.finding_types["injection_phrase"] == 1
    assert snap.finding_types["manipulation_directive"] == 1
    assert snap.agent_files == ["/llms.txt"]
    assert snap.agent_file_findings == 1
    assert snap.divergent_bots == ["claudebot", "gptbot"]  # sorted


def test_diff_detects_verdict_escalation():
    old = Snapshot("u", "identical")
    new = Snapshot("u", "adversarial")
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "verdict" and changes[0].escalation is True


def test_diff_marks_de_escalation_as_not_an_escalation():
    changes = diff_snapshots(Snapshot("u", "adversarial"), Snapshot("u", "identical"))
    assert changes[0].escalation is False


def test_diff_detects_new_finding_type():
    old = Snapshot("u", "benign_divergence", finding_types={})
    new = Snapshot("u", "benign_divergence", finding_types={"invisible_unicode": 1})
    changes = diff_snapshots(old, new)
    assert any(c.kind == "findings" and c.escalation for c in changes)


def test_diff_detects_new_agent_file_and_findings():
    old = Snapshot("u", "identical", agent_files=[], agent_file_findings=0)
    new = Snapshot("u", "identical", agent_files=["/llms.txt"], agent_file_findings=2)
    kinds = {(c.kind, c.escalation) for c in diff_snapshots(old, new)}
    assert ("agent_files", False) in kinds   # new file appeared
    assert ("agent_files", True) in kinds     # and it carries findings


def test_diff_detects_newly_divergent_bot():
    old = Snapshot("u", "benign_divergence", divergent_bots=["gptbot"])
    new = Snapshot("u", "benign_divergence", divergent_bots=["gptbot", "claudebot"])
    changes = diff_snapshots(old, new)
    assert any("claudebot" in c.detail and c.escalation for c in changes)


def test_diff_empty_when_nothing_changed():
    snap = Snapshot("u", "identical", finding_types={"x": 1}, divergent_bots=["gptbot"])
    assert diff_snapshots(snap, snap) == []


def test_state_round_trips(tmp_path):
    path = str(tmp_path / "state.json")
    state = {"https://x.test": Snapshot("https://x.test", "adversarial",
                                        finding_types={"injection_phrase": 1})}
    save_state(path, state)
    loaded = load_state(path)
    assert loaded["https://x.test"].verdict == "adversarial"
    assert loaded["https://x.test"].finding_types == {"injection_phrase": 1}


def test_load_state_missing_file_is_empty(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) == {}


def test_watch_first_run_baselines_then_detects_change(tmp_path):
    path = str(tmp_path / "state.json")
    verdicts = {"https://x.test": Verdict.IDENTICAL}

    def analyzer(url: str) -> SiteReport:
        return _report(url, verdicts[url])

    first = watch_once(["https://x.test"], path, analyzer)
    assert first.baselined == ["https://x.test"]
    assert first.changes == []

    # the site starts cloaking; the next run should flag an escalation
    verdicts["https://x.test"] = Verdict.ADVERSARIAL
    second = watch_once(["https://x.test"], path, analyzer)
    assert second.baselined == []
    assert len(second.escalations) == 1
    assert "identical -> adversarial" in second.escalations[0].detail


def test_watch_unchanged_site_reports_nothing(tmp_path):
    path = str(tmp_path / "state.json")
    analyzer = lambda url: _report(url, Verdict.IDENTICAL)
    watch_once(["https://x.test"], path, analyzer)
    run = watch_once(["https://x.test"], path, analyzer)
    assert run.unchanged == ["https://x.test"] and run.changes == []


def test_watch_handles_analyzer_failure(tmp_path):
    path = str(tmp_path / "state.json")

    def boom(url: str) -> SiteReport:
        raise RuntimeError("dns failure")

    run = watch_once(["https://x.test"], path, boom)
    assert any(c.kind == "unreachable" for c in run.changes)
