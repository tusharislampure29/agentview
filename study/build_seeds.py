"""Build a reproducible seed list from the Tranco top-sites ranking.

Tranco (https://tranco-list.eu) publishes a research-grade ranking that averages
several providers over a 30-day window, so it's stable and citable — unlike the
day-to-day Alexa/Cloudflare lists. We pin an explicit ``list_id`` in the seed
file's header so the exact sample can be regenerated months later.

Usage:
    python study/build_seeds.py --count 1000 -o study/seeds/tranco_top1000.txt
    python study/build_seeds.py --count 1000 --skip-infra -o study/seeds/content1000.txt
"""
from __future__ import annotations

import argparse
import sys

import httpx

LATEST_API = "https://tranco-list.eu/api/lists/date/latest"
DOWNLOAD = "https://tranco-list.eu/download/{list_id}/{count}"

# Pure infrastructure / CDN / API / DNS hosts that never serve a browsable page.
# Skipping them (opt-in) focuses the sample on sites a human or agent would
# actually read. Suffix match on the registrable domain.
_INFRA_SUFFIXES = {
    "gtld-servers.net", "root-servers.net", "nstld.com", "akadns.net",
    "akamai.net", "akamaiedge.net", "akamaized.net", "edgekey.net", "edgesuite.net",
    "fastly.net", "fbcdn.net", "cloudfront.net", "gstatic.com", "googleapis.com",
    "googleusercontent.com", "amazonaws.com", "azureedge.net",
    "windows.net", "trafficmanager.net", "cloudflare-dns.com", "in-addr.arpa",
    "1e100.net", "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "gvt1.com", "gvt2.com", "ntp.org", "office365.com",
}


def resolve_latest_list_id() -> str:
    r = httpx.get(LATEST_API, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.json()["list_id"]


def fetch_ranking(list_id: str, count: int) -> list[tuple[int, str]]:
    # Tranco caps some download sizes; ask for a margin so infra-filtering still
    # leaves us `count` domains.
    ask = min(count * 2, 1_000_000)
    url = DOWNLOAD.format(list_id=list_id, count=ask)
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    rows: list[tuple[int, str]] = []
    for line in r.text.splitlines():
        rank, _, domain = line.partition(",")
        domain = domain.strip().lower()
        if not domain:
            continue
        try:
            rows.append((int(rank), domain))
        except ValueError:
            continue  # skip a malformed row rather than abort the whole build
    return rows


def is_infra(domain: str) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in _INFRA_SUFFIXES)


def build(count: int, list_id: str | None, skip_infra: bool) -> tuple[str, list[str]]:
    list_id = list_id or resolve_latest_list_id()
    ranking = fetch_ranking(list_id, count)
    domains: list[str] = []
    for _, domain in ranking:
        if skip_infra and is_infra(domain):
            continue
        domains.append(domain)
        if len(domains) >= count:
            break
    return list_id, domains


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a Tranco-based seed list for the agentview study.")
    p.add_argument("--count", type=int, default=1000, help="number of domains (default 1000)")
    p.add_argument("--list-id", help="pin a specific Tranco list id (default: latest)")
    p.add_argument("--skip-infra", action="store_true",
                   help="drop pure CDN/API/DNS infrastructure domains")
    p.add_argument("-o", "--output", required=True, help="seed file to write")
    args = p.parse_args(argv)

    list_id, domains = build(args.count, args.list_id, args.skip_infra)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(f"# Tranco top sites — list_id={list_id} "
                 f"(https://tranco-list.eu/list/{list_id})\n")
        fh.write(f"# count={len(domains)} skip_infra={args.skip_infra}\n")
        for d in domains:
            fh.write(d + "\n")
    print(f"wrote {len(domains)} domains to {args.output} (Tranco list {list_id})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
