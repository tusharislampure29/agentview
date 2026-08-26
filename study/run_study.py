"""Run the prevalence study over a seed list, with bounded site-level concurrency.

The `agentview scan` CLI is deliberately one-site-at-a-time (kind to any single
host). For a study over hundreds of sites that's too slow, so this runner fans
out across *different* hosts with a **process** pool — we still only ever issue
one site's worth of requests to any given host at a time, so no host is hammered.
Processes (not threads) because the work is CPU-bound: each site parses eight HTML
documents with a pure-Python parser, and the GIL would otherwise serialize that.

Results stream to JSONL as each site finishes (resumable: re-running skips URLs
already present in the output file). Then it prints the headline stats.

Usage:
    python study/run_study.py study/seeds/tranco_top500.txt \
        -o study/results/tranco_top500.jsonl --concurrency 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from agentview.analyze import analyze_url
from agentview.serialize import report_to_dict
from agentview.stats import summarize


def load_urls(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line if line.startswith("http") else "https://" + line)
    return urls


def already_done(path: str) -> set[str]:
    done: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line)["url"])
                    except (ValueError, KeyError):
                        pass
    except FileNotFoundError:
        pass
    return done


def _scan_one(url: str, timeout: float, include_agent_files: bool) -> dict:
    try:
        report = analyze_url(url, timeout=timeout, include_agent_files=include_agent_files)
        return report_to_dict(report)
    except Exception as exc:  # noqa: BLE001 — one bad site must not kill the batch
        return {"url": url, "verdict": "error", "error": f"{type(exc).__name__}: {exc}"}


def run(seed: str, output: str, concurrency: int, timeout: float,
        include_agent_files: bool, limit: int | None) -> None:
    urls = load_urls(seed)
    if limit:
        urls = urls[:limit]
    done = already_done(output)
    todo = [u for u in urls if u not in done]
    print(f"  {len(urls)} urls, {len(done)} already done, {len(todo)} to scan "
          f"(concurrency={concurrency})", file=sys.stderr)

    start = time.perf_counter()
    completed = 0
    with open(output, "a", encoding="utf-8") as out, \
            ProcessPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_scan_one, u, timeout, include_agent_files): u for u in todo}
        for fut in as_completed(futures):
            record = fut.result()
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            completed += 1
            rate = completed / max(time.perf_counter() - start, 1e-6)
            eta = (len(todo) - completed) / rate if rate else 0
            print(f"\r  {completed}/{len(todo)}  ({rate:.1f}/s, ETA {eta/60:.1f} min)  "
                  f"{record['url'][:48]:<48}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the agentview prevalence study.")
    p.add_argument("seed", help="seed file (one domain/URL per line)")
    p.add_argument("-o", "--output", required=True, help="output JSONL path (appended, resumable)")
    p.add_argument("--concurrency", type=int, default=min(os.cpu_count() or 4, 12),
                   help="concurrent worker processes (default: min(cpus, 12))")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--skip-agent-files", action="store_true")
    p.add_argument("--limit", type=int, help="only scan the first N urls")
    p.add_argument("--no-stats", action="store_true", help="don't print stats at the end")
    args = p.parse_args(argv)

    run(args.seed, args.output, args.concurrency, args.timeout,
        not args.skip_agent_files, args.limit)

    if not args.no_stats:
        with open(args.output, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        summary = summarize(records)
        print(f"\n  HEADLINE: {summary['sites_serving_agents_differently']} of "
              f"{summary['analyzed']} sites ({summary['pct_serving_agents_differently']}%) "
              f"serve AI agents a different response.", file=sys.stderr)
        print(f"  run `agentview stats {args.output}` for the full breakdown.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
