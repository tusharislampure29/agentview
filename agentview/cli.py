"""Command line:
  `agentview check <url>`   — compare one URL across the human + AI identities
  `agentview scan <file>`   — batch a URL list into a JSONL dataset
  `agentview stats <jsonl>` — aggregate a dataset into headline statistics
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .analyze import analyze_url
from .identities import AI_IDENTITIES
from .models import DIVERGENCE_THRESHOLD, Severity, SiteReport, Verdict
from .render import INSTALL_HINT, Renderer, is_available, render_with_playwright
from .serialize import report_to_dict
from .stats import summarize

_VERDICT_LABEL = {
    Verdict.IDENTICAL: "IDENTICAL — human and AI see the same page",
    Verdict.BENIGN_DIVERGENCE: "DIVERGENT — AI is served a different page (no adversarial signal)",
    Verdict.MANIPULATIVE: "MANIPULATIVE — AI-only content steers the model's answer",
    Verdict.ADVERSARIAL: "ADVERSARIAL — hidden instructions / injection aimed at the AI",
    Verdict.ERROR: "ERROR — could not compare",
}
_SEV_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}


def _force_utf8() -> None:
    # JSON and page snippets are UTF-8; Windows piped stdout defaults to cp1252.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _print_report(report: SiteReport) -> None:
    print(f"\n  agentview — {report.url}")
    print(f"  verdict: {_VERDICT_LABEL[report.verdict]}\n")

    for key, fr in report.fetches.items():
        if fr.ok:
            print(f"   [{key:>16}] {fr.status}  {fr.content_length:>8}B  "
                  f"{fr.elapsed_ms:>5}ms  ->  {fr.final_url}")
        else:
            print(f"   [{key:>16}] FAILED  {fr.error}")

    if report.divergences:
        print("\n  divergence vs human view:")
        for d in report.divergences:
            flag = "   <-- different" if (
                d.similarity < DIVERGENCE_THRESHOLD or d.status_differs or d.redirect_differs
            ) else ""
            print(f"   {d.identity:>16}: similarity {d.similarity:5.2f}  len×{d.length_ratio:.2f}{flag}")

    present_files = [af for af in report.agent_files if af.present]
    if present_files:
        print("\n  agent-instruction files:")
        for af in present_files:
            flag = f"  ({len(af.findings)} finding(s))" if af.findings else ""
            print(f"   {af.path:>24}  {af.content_length:>7}B{flag}")

    findings = list(report.findings) + [f for af in report.agent_files for f in af.findings]
    if findings:
        print("\n  findings:")
        for f in sorted(findings, key=lambda x: _SEV_ORDER[x.severity]):
            print(f"   [{f.severity.value.upper():>6}] {f.type.value} "
                  f"({f.identity}): {f.snippet[:100]}")

    for note in report.notes:
        print(f"   note: {note}")
    print()


def _load_urls(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line if line.startswith("http") else "https://" + line)
    return urls


def _resolve_renderer(args: argparse.Namespace) -> Renderer | None:
    """Turn the --render flag into a renderer, or exit with a helpful message if the
    optional browser dependency isn't installed."""
    if not getattr(args, "render", False):
        return None
    if not is_available():
        print(f"\n  --render requested but unavailable.\n  {INSTALL_HINT}\n",
              file=sys.stderr)
        raise SystemExit(2)
    return render_with_playwright


def _write_html_report(report: SiteReport, url: str, path: str) -> None:
    from datetime import datetime

    from .htmlview import standalone_report
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    subtitle = f"generated {stamp} · agentview {__version__}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(standalone_report(report, url, subtitle))
    print(f"  wrote HTML report -> {path}", file=sys.stderr)


def cmd_check(args: argparse.Namespace) -> int:
    renderer = _resolve_renderer(args)
    report = analyze_url(args.url, timeout=args.timeout,
                         include_agent_files=not args.skip_agent_files,
                         renderer=renderer)
    if args.format == "json":
        print(json.dumps(report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    if args.html:
        _write_html_report(report, args.url, args.html)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    renderer = _resolve_renderer(args)
    urls = _load_urls(args.input)
    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    counts: dict[str, int] = {}
    try:
        for i, url in enumerate(urls, 1):
            try:
                report = analyze_url(url, timeout=args.timeout,
                                     include_agent_files=not args.skip_agent_files,
                                     renderer=renderer)
                record = report_to_dict(report)
                counts[report.verdict.value] = counts.get(report.verdict.value, 0) + 1
            except Exception as exc:  # noqa: BLE001 — one bad URL must not stop the batch
                record = {"url": url, "verdict": "error", "error": str(exc)}
                counts["error"] = counts.get("error", 0) + 1
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"\r  scanned {i}/{len(urls)}", end="", file=sys.stderr, flush=True)
    finally:
        if args.output:
            out.close()

    total = sum(counts.values()) or 1
    print(f"\n\n  done — {sum(counts.values())} urls", file=sys.stderr)
    for verdict, count in sorted(counts.items()):
        print(f"   {verdict:>18}: {count:>5}  ({100 * count / total:.1f}%)", file=sys.stderr)
    return 0


def _load_records(path: str) -> list[dict]:
    records: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


_VERDICT_ORDER = ["adversarial", "manipulative", "benign_divergence", "identical", "error"]


def _print_stats(s: dict) -> None:
    print(f"\n  agentview — study summary")
    print(f"  urls scanned:        {s['total_urls']}")
    print(f"  analyzed (human OK): {s['analyzed']}     ({s['errors']} could not be compared)\n")

    print("  ── HEADLINE ─────────────────────────────────────────────")
    print(f"   {s['sites_serving_agents_differently']} of {s['analyzed']} sites "
          f"({s['pct_serving_agents_differently']}%) serve AI agents a different response "
          f"than a human.")
    print("   spectrum:")
    print(f"     • block the agent (4xx/5xx):        {s['sites_blocking_agents']:>5}  "
          f"({s['pct_blocking_agents']}%)")
    print(f"     • serve an altered 200 page:        {s['sites_altering_content']:>5}  "
          f"({s['pct_altering_content']}%)   <- the interesting slice\n")

    print("  verdicts:")
    for v in _VERDICT_ORDER:
        if v in s["verdicts"]:
            print(f"     {v:>18}  {s['verdicts'][v]:>6}")
    print()

    print("  per AI crawler (of sites that answered it):")
    print(f"     {'crawler':>28}  {'same':>5} {'diff':>5} {'block':>6} {'fail':>5}  {'%block':>7}")
    for ident in AI_IDENTITIES:
        b = s["per_bot"].get(ident.key)
        if not b:
            continue
        print(f"     {ident.label[:28]:>28}  {b['served_same']:>5} {b['different_content']:>5} "
              f"{b['blocked']:>6} {b['failed']:>5}  {b['pct_blocked']:>6}%")
    print()

    af = s["agent_files"]
    print("  agent-instruction files (llms.txt / agents.json / …):")
    print(f"     sites publishing any:   {af['sites_with_any']:>5}  ({af['pct_with_any']}%)")
    print(f"     …with any finding:      {af['sites_with_findings']:>5}")
    print(f"     …with manipulation:     {af['sites_with_manipulation']:>5}")
    if af["by_path"]:
        for path, n in sorted(af["by_path"].items(), key=lambda kv: -kv[1]):
            print(f"       {path:<26} {n:>5}")
    print()

    if s["finding_types"]:
        print("  finding types (across page + agent files):")
        for ftype, n in sorted(s["finding_types"].items(), key=lambda kv: -kv[1]):
            print(f"     {ftype:>26}  {n:>5}")
    print()


def _stats_markdown(s: dict) -> str:
    lines = [
        "# agentview — study summary",
        "",
        f"- **URLs scanned:** {s['total_urls']}",
        f"- **Analyzed (human fetch OK):** {s['analyzed']} ({s['errors']} could not be compared)",
        "",
        "## Headline",
        "",
        f"**{s['sites_serving_agents_differently']} of {s['analyzed']} sites "
        f"({s['pct_serving_agents_differently']}%) serve AI agents a different response than a human.**",
        "",
        "| how they differ | sites | % of analyzed |",
        "| --- | ---: | ---: |",
        f"| block the agent (4xx/5xx) | {s['sites_blocking_agents']} | {s['pct_blocking_agents']}% |",
        f"| serve an altered 200 page | {s['sites_altering_content']} | {s['pct_altering_content']}% |",
        "",
        "## Verdicts",
        "",
        "| verdict | sites |",
        "| --- | ---: |",
    ]
    lines += [f"| {v} | {s['verdicts'][v]} |" for v in _VERDICT_ORDER if v in s["verdicts"]]
    lines += [
        "",
        "## Per AI crawler",
        "",
        "| crawler | served same | different | blocked | failed | % blocked |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for ident in AI_IDENTITIES:
        b = s["per_bot"].get(ident.key)
        if b:
            lines.append(f"| {ident.label} | {b['served_same']} | {b['different_content']} | "
                         f"{b['blocked']} | {b['failed']} | {b['pct_blocked']}% |")
    af = s["agent_files"]
    lines += [
        "",
        "## Agent-instruction files",
        "",
        f"- Sites publishing any (llms.txt / agents.json / …): **{af['sites_with_any']}** "
        f"({af['pct_with_any']}%)",
        f"- …with any finding: **{af['sites_with_findings']}**",
        f"- …with a manipulation directive: **{af['sites_with_manipulation']}**",
    ]
    if s["finding_types"]:
        lines += ["", "## Finding types", "", "| type | count |", "| --- | ---: |"]
        lines += [f"| {t} | {n} |" for t, n in
                  sorted(s["finding_types"].items(), key=lambda kv: -kv[1])]
    return "\n".join(lines) + "\n"


def cmd_stats(args: argparse.Namespace) -> int:
    summary = summarize(_load_records(args.input))
    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        print(_stats_markdown(summary), end="")
    else:
        _print_stats(summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentview",
        description="See the web the way an AI agent sees it — and measure where it differs.",
    )
    p.add_argument("--version", action="version", version=f"agentview {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="compare one URL across human + AI identities")
    check.add_argument("url")
    check.add_argument("--format", choices=["text", "json"], default="text")
    check.add_argument("--timeout", type=float, default=20.0)
    check.add_argument("--skip-agent-files", action="store_true",
                       help="don't fetch llms.txt / agents.json")
    check.add_argument("--render", action="store_true",
                       help="use a JS-rendered (headless Chromium) human baseline "
                            "— catches SPA/JS cloaking; needs the [render] extra")
    check.add_argument("--html", metavar="PATH",
                       help="also write a self-contained HTML report to PATH")
    check.set_defaults(func=cmd_check)

    scan = sub.add_parser("scan", help="batch-scan a file of URLs into a JSONL dataset")
    scan.add_argument("input", help="file with one URL per line")
    scan.add_argument("-o", "--output", help="output JSONL path (default: stdout)")
    scan.add_argument("--timeout", type=float, default=20.0)
    scan.add_argument("--skip-agent-files", action="store_true",
                      help="don't fetch llms.txt / agents.json")
    scan.add_argument("--render", action="store_true",
                      help="use a JS-rendered (headless Chromium) human baseline "
                           "(slower; needs the [render] extra)")
    scan.set_defaults(func=cmd_scan)

    stats = sub.add_parser("stats", help="aggregate a JSONL dataset into headline statistics")
    stats.add_argument("input", help="JSONL file produced by `agentview scan`")
    stats.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    stats.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
