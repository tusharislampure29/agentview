"""Aggregate a set of per-site records (as emitted by the CLI) into the
study's headline statistics. Pure functions over plain dicts, so the same code
summarizes a live run or an existing dataset file — and is easy to unit-test.
"""
from __future__ import annotations

from collections import Counter

from .identities import AI_IDENTITIES
from .models import DIVERGENCE_THRESHOLD


def human_ok(record: dict) -> bool:
    h = record.get("fetches", {}).get("human")
    return bool(h and h.get("ok") and (h.get("status") or 0) < 400)


def _ai_status(record: dict, identity: str) -> int:
    fetch = record.get("fetches", {}).get(identity) or {}
    return fetch.get("status") or 0


def is_divergent(record: dict) -> bool:
    """True if at least one AI identity was served materially different content —
    whether by an outright block or by an altered 200 page."""
    for d in record.get("divergences", []):
        if (d.get("similarity", 1.0) < DIVERGENCE_THRESHOLD
                or d.get("status_differs") or d.get("redirect_differs")):
            return True
    return False


def blocks_agents(record: dict) -> bool:
    """At least one AI identity got an error status (>=400) that the human did not."""
    return any(d.get("status_differs") and _ai_status(record, d.get("identity", "")) >= 400
               for d in record.get("divergences", []))


def alters_content(record: dict) -> bool:
    """The scarier slice: at least one AI identity was served a *successful* (2xx/3xx)
    page whose visible text materially differs from the human's — not just a block."""
    for d in record.get("divergences", []):
        if _ai_status(record, d.get("identity", "")) >= 400:
            continue
        if d.get("similarity", 1.0) < DIVERGENCE_THRESHOLD or d.get("redirect_differs"):
            return True
    return False


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def summarize(records: list[dict]) -> dict:
    total = len(records)
    analyzed = [r for r in records if human_ok(r)]
    n = len(analyzed)

    verdicts = Counter(r.get("verdict", "error") for r in records)
    divergent = [r for r in analyzed if is_divergent(r)]
    blocking = [r for r in analyzed if blocks_agents(r)]
    altering = [r for r in analyzed if alters_content(r)]
    # Sites carrying an agent-directed manipulation/injection signal (the scary
    # slice), counted over the analyzed set for a consistent denominator.
    manip_adv = [r for r in analyzed
                 if r.get("verdict") in ("manipulative", "adversarial")]

    per_bot: dict[str, dict] = {}
    for ident in AI_IDENTITIES:
        key = ident.key
        served_same = blocked = different = failed = denom = 0
        for r in analyzed:
            fetch = r.get("fetches", {}).get(key)
            if fetch is None:
                continue
            denom += 1
            if not fetch.get("ok"):
                failed += 1
                continue
            status = fetch.get("status") or 0
            div = next((d for d in r.get("divergences", []) if d.get("identity") == key), None)
            if status >= 400:
                blocked += 1
            elif div and (div.get("similarity", 1.0) < DIVERGENCE_THRESHOLD
                          or div.get("redirect_differs")):
                different += 1
            else:
                served_same += 1
        per_bot[key] = {
            "label": ident.label, "denom": denom, "served_same": served_same,
            "blocked": blocked, "different_content": different, "failed": failed,
            "pct_blocked": _pct(blocked, denom),
        }

    sites_with_af = sites_with_findings = sites_with_manip = 0
    by_path: Counter = Counter()
    for r in analyzed:
        present = [a for a in r.get("agent_files", []) if a.get("present")]
        if present:
            sites_with_af += 1
        has_finding = has_manip = False
        for a in present:
            by_path[a.get("path", "?")] += 1
            for f in a.get("findings", []):
                has_finding = True
                if f.get("type") == "manipulation_directive":
                    has_manip = True
        sites_with_findings += int(has_finding)
        sites_with_manip += int(has_manip)

    finding_types: Counter = Counter()
    for r in analyzed:
        for f in r.get("findings", []):
            finding_types[f.get("type", "?")] += 1
        for a in r.get("agent_files", []):
            for f in a.get("findings", []):
                finding_types[f.get("type", "?")] += 1

    return {
        "total_urls": total,
        "analyzed": n,
        "errors": total - n,
        "verdicts": dict(verdicts),
        "sites_serving_agents_differently": len(divergent),
        "pct_serving_agents_differently": _pct(len(divergent), n),
        "sites_blocking_agents": len(blocking),
        "pct_blocking_agents": _pct(len(blocking), n),
        "sites_altering_content": len(altering),
        "pct_altering_content": _pct(len(altering), n),
        "sites_manipulative_or_adversarial": len(manip_adv),
        "pct_manipulative_or_adversarial": _pct(len(manip_adv), n),
        "per_bot": per_bot,
        "agent_files": {
            "sites_with_any": sites_with_af,
            "pct_with_any": _pct(sites_with_af, n),
            "sites_with_findings": sites_with_findings,
            "sites_with_manipulation": sites_with_manip,
            "by_path": dict(by_path),
        },
        "finding_types": dict(finding_types),
    }
