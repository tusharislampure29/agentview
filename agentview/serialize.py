"""Serialize a :class:`SiteReport` to plain JSON-ready dicts.

Kept separate from the CLI because three callers need it — the CLI, the study
runner, and the demo API — and they must all emit the exact same record shape so
one dataset schema describes them all.
"""
from __future__ import annotations

from .models import Finding, SiteReport


def finding_dict(f: Finding) -> dict:
    return {"type": f.type.value, "severity": f.severity.value,
            "identity": f.identity, "snippet": f.snippet, "detail": f.detail}


def report_to_dict(report: SiteReport) -> dict:
    return {
        "url": report.url,
        "verdict": report.verdict.value,
        "fetches": {
            k: {"ok": v.ok, "status": v.status, "final_url": v.final_url,
                "redirects": v.redirects, "bytes": v.content_length,
                "elapsed_ms": v.elapsed_ms, "error": v.error,
                **({"rendered": True} if v.rendered else {})}
            for k, v in report.fetches.items()
        },
        "divergences": [vars(d) for d in report.divergences],
        "findings": [finding_dict(f) for f in report.findings],
        "agent_files": [
            {"path": af.path, "present": af.present, "status": af.status,
             "bytes": af.content_length, "error": af.error,
             "findings": [finding_dict(f) for f in af.findings]}
            for af in report.agent_files
        ],
        "notes": report.notes,
    }
