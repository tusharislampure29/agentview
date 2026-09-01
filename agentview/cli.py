"""Command line:
  `agentview check <url>`    — compare one URL across the human + AI identities
  `agentview why <url>`      — attribute *how* a cloaking site detects the bot
  `agentview guard <url>`    — sanitize a page for safe LLM ingestion (defense)
  `agentview efficacy <url>` — test whether the cloak actually manipulates a real LLM
  `agentview watch <input>`  — track sites over time and alert when one starts cloaking
  `agentview scan <file>`    — batch a URL list into a JSONL dataset
  `agentview stats <jsonl>`  — aggregate a dataset into headline statistics
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .analyze import analyze_url
from .attribution import attribute, attribution_to_dict
from .efficacy import (
    DEFAULT_QUESTION, EfficacyUnavailable, efficacy_result_to_dict,
    measure_efficacy, resolve_model,
)
from .fetch import fetch_all_identities_sync
from .guard import guard_result_to_dict, sanitize
from .identities import AI_IDENTITIES, HUMAN, by_key
from .models import DIVERGENCE_THRESHOLD, Severity, SiteReport, Verdict
from .render import INSTALL_HINT, Renderer, is_available, render_with_playwright
from .serialize import report_to_dict
from .stats import summarize
from .watch import WatchRun, watch_once

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


def _normalize_url(url: str) -> str:
    """Accept a bare host (``example.com``) as well as a full URL — a user typing
    `agentview check example.com` should just work, like scan/watch already do."""
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else "https://" + url


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
    # utf-8-sig: a URL list saved by Notepad or PowerShell often has a UTF-8 BOM;
    # reading as plain utf-8 would glue "﻿" onto the first URL and silently
    # break it. utf-8-sig strips a leading BOM and is identical otherwise.
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip().lstrip("﻿")
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
    url = _normalize_url(args.url)
    renderer = _resolve_renderer(args)
    report = analyze_url(url, timeout=args.timeout,
                         include_agent_files=not args.skip_agent_files,
                         renderer=renderer)
    if args.format == "json":
        print(json.dumps(report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    if args.html:
        _write_html_report(report, url, args.html)
    return 0


_GUARD_DEFAULT_IDENTITY = "chatgpt-user"


def _print_guard(url: str, ident_label: str, fr, r) -> None:
    print(f"\n  agentview guard — {url}")
    print(f"  fetched as: {ident_label}  [status {fr.status}, {fr.content_length}B]\n")
    print(f"  sanitized: {r.original_text_len} -> {r.clean_text_len} chars "
          f"({r.invisible_chars_removed} invisible char(s), "
          f"{r.hidden_blocks_removed} hidden block(s), {r.comments_removed} comment(s) seen)")

    if r.removed:
        print(f"\n  removed {len(r.removed)} item(s) aimed at the model:")
        for x in r.removed:
            print(f"   [{x.kind:>20}] {x.snippet[:100]}")
    if r.flagged:
        print(f"\n  flagged {len(r.flagged)} suspicious visible item(s) — left in place "
              f"(use --aggressive to redact):")
        for x in r.flagged:
            print(f"   [{x.kind:>20}] {x.snippet[:100]}")
    if r.is_clean:
        print("\n  clean — nothing agent-targeted found.")

    preview = r.text[:500]
    print("\n  clean text preview:")
    print(f"   {preview}{' …' if len(r.text) > 500 else ''}\n")


def cmd_guard(args: argparse.Namespace) -> int:
    url = _normalize_url(args.url)
    ident = by_key(args.as_identity)
    if ident is None:
        print(f"\n  unknown identity '{args.as_identity}'. Options: "
              f"{', '.join(i.key for i in AI_IDENTITIES)}\n", file=sys.stderr)
        return 2
    fetches = fetch_all_identities_sync(url, identities=[ident], timeout=args.timeout)
    fr = fetches[ident.key]
    if not fr.ok:
        print(f"\n  fetch failed ({fr.error})\n", file=sys.stderr)
        return 1

    r = sanitize(fr.html, aggressive=args.aggressive)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(r.text)
        print(f"  wrote {r.clean_text_len} chars of clean text -> {args.output}", file=sys.stderr)

    if args.format == "json":
        payload = {"url": url, "fetched_as": ident.key, **guard_result_to_dict(r)}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not args.output:
        _print_guard(url, ident.label, fr, r)
    return 0


def _print_attribution(r) -> None:
    print(f"\n  agentview why — {r.url}")
    print(f"  probed with crawler UA: {r.crawler_key}\n")
    if r.cloaks:
        print("  this site serves the bot a different page. it keys on:")
        for t in r.triggers:
            print(f"   • {t}")
    else:
        print("  no User-Agent / header-based cloaking detected.")

    print("\n  probe divergence vs the browser baseline:")
    for key, diverged in r.diverged.items():
        label = r.labels.get(key, key)
        flag = "  <-- different" if diverged else "  same"
        print(f"   [{key:>18}] {label:<40}{flag}")

    for note in r.notes:
        print(f"\n  note: {note}")
    print()


def cmd_why(args: argparse.Namespace) -> int:
    r = attribute(_normalize_url(args.url), crawler=args.crawler, timeout=args.timeout)
    if args.format == "json":
        print(json.dumps(attribution_to_dict(r), indent=2, ensure_ascii=False))
    else:
        _print_attribution(r)
    return 0


def _efficacy_inputs(args: argparse.Namespace) -> tuple[str, str, str]:
    """Return (label, human_text, ai_text) for either the built-in demo or a live URL."""
    if args.demo:
        from .demo.sample import _AI_HTML, _HUMAN_HTML, SAMPLE_URL
        from .diff import html_to_text
        return (SAMPLE_URL, html_to_text(_HUMAN_HTML), html_to_text(_AI_HTML))

    ident = by_key(args.as_identity)
    if ident is None:
        raise SystemExit(f"unknown identity '{args.as_identity}'")
    url = _normalize_url(args.url)
    fetches = fetch_all_identities_sync(url, identities=[HUMAN, ident], timeout=args.timeout)
    human, ai = fetches[HUMAN.key], fetches[ident.key]
    if not human.ok or not ai.ok:
        raise SystemExit(f"fetch failed (human ok={human.ok}, {ident.key} ok={ai.ok})")
    return (url, human.text, ai.text)


def _print_efficacy(label: str, r) -> None:
    print(f"\n  agentview efficacy — {label}")
    if not r.tested:
        print(f"  {r.note}\n")
        return
    verdict = "INJECTION WORKED" if r.injection_succeeded else "no effect"
    print(f"  result: {verdict} — {r.note}")
    if r.goal_tokens:
        print(f"  payload tried to plant: {', '.join(r.goal_tokens)}")
    if r.leaked_tokens:
        print(f"  surfaced only in the AI-view answer: {', '.join(r.leaked_tokens)}")
    print(f"\n  question: {r.question}")
    print(f"\n  answer from the HUMAN view:\n   {r.human_answer.strip()}")
    print(f"\n  answer from the AI view:\n   {r.ai_answer.strip()}\n")


def cmd_efficacy(args: argparse.Namespace) -> int:
    if not args.demo and not args.url:
        print("\n  provide a URL, or use --demo for the built-in synthetic example\n",
              file=sys.stderr)
        return 2
    try:
        model = resolve_model(args.provider, args.model, timeout=args.timeout)
    except EfficacyUnavailable as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 2

    label, human_text, ai_text = _efficacy_inputs(args)
    question = args.question or DEFAULT_QUESTION
    try:
        r = measure_efficacy(human_text, ai_text, model, question=question)
    except Exception as exc:  # noqa: BLE001 — surface API/network failures cleanly
        print(f"\n  model call failed: {type(exc).__name__}: {exc}\n", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"target": label, **efficacy_result_to_dict(r)},
                         indent=2, ensure_ascii=False))
    else:
        _print_efficacy(label, r)
    return 0


def _watch_urls(input_arg: str) -> list[str]:
    if os.path.isfile(input_arg):
        return _load_urls(input_arg)
    return [input_arg if input_arg.startswith("http") else "https://" + input_arg]


def _print_watch(run: WatchRun, state_path: str, total: int) -> None:
    print(f"\n  agentview watch — {total} site(s), state: {state_path}\n")
    print(f"  baselined (first seen): {len(run.baselined)}")
    print(f"  unchanged:              {len(run.unchanged)}")
    print(f"  changed:                {len({c.url for c in run.changes})}")
    if run.changes:
        print("\n  changes since last run:")
        for c in run.changes:
            mark = "  !! ESCALATION" if c.escalation else "  •           "
            print(f"   {mark}  {c.url}\n                    {c.detail}")
    elif not run.baselined:
        print("\n  no changes.")
    print()


def cmd_watch(args: argparse.Namespace) -> int:
    urls = _watch_urls(args.input)

    def analyzer(url: str):
        return analyze_url(url, timeout=args.timeout,
                           include_agent_files=not args.skip_agent_files)

    run = watch_once(urls, args.state, analyzer)

    if args.format == "json":
        print(json.dumps({
            "state": args.state,
            "baselined": run.baselined,
            "unchanged": run.unchanged,
            "changes": [{"url": c.url, "kind": c.kind, "detail": c.detail,
                         "escalation": c.escalation} for c in run.changes],
        }, indent=2, ensure_ascii=False))
    else:
        _print_watch(run, args.state, len(urls))

    if args.fail_on_escalation and run.escalations:
        return 3
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
    # utf-8-sig so a hand-edited dataset saved with a BOM still parses (a BOM on
    # the first line would otherwise make json.loads choke).
    with open(path, encoding="utf-8-sig") as fh:
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

    guard = sub.add_parser(
        "guard",
        help="sanitize a page for safe LLM ingestion (strip agent-targeted payloads)")
    guard.add_argument("url")
    guard.add_argument("--as", dest="as_identity", default=_GUARD_DEFAULT_IDENTITY,
                       metavar="IDENTITY",
                       help=f"AI identity to fetch as (default: {_GUARD_DEFAULT_IDENTITY}); "
                            f"one of: {', '.join(i.key for i in AI_IDENTITIES)}")
    guard.add_argument("--aggressive", action="store_true",
                       help="also redact visible injection phrases / manipulation directives, "
                            "not just flag them")
    guard.add_argument("--format", choices=["text", "json"], default="text")
    guard.add_argument("--timeout", type=float, default=20.0)
    guard.add_argument("-o", "--output", metavar="PATH",
                       help="write only the clean text to PATH (for piping into a model)")
    guard.set_defaults(func=cmd_guard)

    why = sub.add_parser(
        "why",
        help="attribute how a cloaking site detects the bot (which request signal it keys on)")
    why.add_argument("url")
    why.add_argument("--crawler", default="gptbot", metavar="KEY",
                     help=f"named crawler UA to probe with (default: gptbot); "
                          f"one of: {', '.join(i.key for i in AI_IDENTITIES)}")
    why.add_argument("--format", choices=["text", "json"], default="text")
    why.add_argument("--timeout", type=float, default=20.0)
    why.set_defaults(func=cmd_why)

    eff = sub.add_parser(
        "efficacy",
        help="test whether a page's cloak actually manipulates a real LLM's answer")
    eff.add_argument("url", nargs="?", help="URL to test (omit and use --demo for the built-in example)")
    eff.add_argument("--demo", action="store_true",
                     help="run against the built-in synthetic cloaked page (no crawling)")
    eff.add_argument("--provider", choices=["auto", "openai", "anthropic"], default="auto",
                     help="which model API to use (default: auto-detect from env keys)")
    eff.add_argument("--model", metavar="NAME", help="model name (provider default otherwise)")
    eff.add_argument("--question", metavar="Q", help="the user question posed to the model")
    eff.add_argument("--as", dest="as_identity", default="chatgpt-user", metavar="IDENTITY",
                     help="AI identity to fetch the AI view as (default: chatgpt-user)")
    eff.add_argument("--format", choices=["text", "json"], default="text")
    eff.add_argument("--timeout", type=float, default=30.0)
    eff.set_defaults(func=cmd_efficacy)

    watch = sub.add_parser(
        "watch",
        help="track a URL (or a file of URLs) over time; report/alert on new cloaking")
    watch.add_argument("input", help="a URL, or a file with one URL per line")
    watch.add_argument("--state", default=".agentview-watch.json", metavar="PATH",
                       help="JSON snapshot file (default: .agentview-watch.json)")
    watch.add_argument("--timeout", type=float, default=20.0)
    watch.add_argument("--skip-agent-files", action="store_true",
                       help="don't fetch llms.txt / agents.json")
    watch.add_argument("--fail-on-escalation", action="store_true",
                       help="exit 3 if any site escalated (for cron/CI alerting)")
    watch.add_argument("--format", choices=["text", "json"], default="text")
    watch.set_defaults(func=cmd_watch)

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
