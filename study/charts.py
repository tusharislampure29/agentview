"""Render the study's headline figures as standalone SVG — no plotting library.

GitHub renders inline SVG in READMEs (scripts stripped, static markup kept), so a
hand-built SVG is crisp at any zoom, diff-friendly, and adds no dependency to a
project whose whole point is a lean HTTP-diff engine. Two figures:

  * spectrum  — how the analyzed sites split across the identical→adversarial axis
  * crawlers  — per-AI-crawler block rate

Usage:
    python study/charts.py study/results/tranco_top500.jsonl --out-dir study/figures
"""
from __future__ import annotations

import argparse
import json
import os

from agentview.identities import AI_IDENTITIES
from agentview.stats import summarize

# Colour ramp from "safe" to "hostile".
_C = {
    "identical": "#3fa34d",
    "benign_divergence": "#e0a800",
    "block": "#e8833a",
    "altered": "#d1495b",
    "manipulative": "#b5179e",
    "adversarial": "#7209b7",
    "bar_bg": "#eef0f3",
    "grid": "#d5d9df",
    "text": "#1c2330",
    "muted": "#5b6472",
}


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _hbars(title: str, subtitle: str, rows: list[tuple[str, float, str, str]],
           width: int = 920) -> str:
    """rows = [(label, value_0_100, colour, right_annotation)]."""
    # pad_r leaves room for the right-hand "N (pct%)" annotation; pad_l for the
    # longest row label. Both were undersized before and clipped the text.
    pad_l, pad_r, pad_t, row_h, gap = 250, 200, 74, 30, 14
    n = len(rows)
    height = pad_t + n * (row_h + gap) + 24
    track_w = width - pad_l - pad_r
    max_v = max((v for _, v, _, _ in rows), default=1.0) or 1.0

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="-apple-system,Segoe UI,Roboto,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="24" y="34" font-size="20" font-weight="700" '
        f'fill="{_C["text"]}">{_esc(title)}</text>',
        f'<text x="24" y="56" font-size="13" fill="{_C["muted"]}">{_esc(subtitle)}</text>',
    ]
    for i, (label, value, colour, annot) in enumerate(rows):
        y = pad_t + i * (row_h + gap)
        bar_w = max(2, int(track_w * (value / max_v)))
        parts += [
            f'<text x="{pad_l - 12}" y="{y + row_h - 9}" text-anchor="end" '
            f'font-size="13" fill="{_C["text"]}">{_esc(label)}</text>',
            f'<rect x="{pad_l}" y="{y}" width="{track_w}" height="{row_h}" rx="5" '
            f'fill="{_C["bar_bg"]}"/>',
            f'<rect x="{pad_l}" y="{y}" width="{bar_w}" height="{row_h}" rx="5" '
            f'fill="{colour}"/>',
            f'<text x="{pad_l + track_w + 10}" y="{y + row_h - 9}" font-size="13" '
            f'font-weight="600" fill="{_C["text"]}">{_esc(annot)}</text>',
        ]
    parts.append("</svg>")
    return "\n".join(parts)


def spectrum_svg(s: dict) -> str:
    """Independent prevalence rates over the analyzed set. Deliberately NOT a
    stacked partition: a site can both block one crawler and serve another an
    altered page, so `block` and `altered` overlap and both sit under `differ`."""
    n = s["analyzed"] or 1
    af = s["agent_files"]
    manip_adv = s["sites_manipulative_or_adversarial"]

    def pct(x: int) -> str:
        return f"{x}  ({100 * x / n:.1f}%)"

    rows = [
        ("serve agents a different response", s["sites_serving_agents_differently"],
         _C["altered"], pct(s["sites_serving_agents_differently"])),
        ("  └ block the agent (4xx/5xx)", s["sites_blocking_agents"],
         _C["block"], pct(s["sites_blocking_agents"])),
        ("  └ altered 200 page", s["sites_altering_content"],
         _C["manipulative"], pct(s["sites_altering_content"])),
        ("publish llms.txt / agents.json", af["sites_with_any"],
         _C["benign_divergence"], pct(af["sites_with_any"])),
        ("manipulation / hidden injection", manip_adv,
         _C["adversarial"], pct(manip_adv)),
    ]
    return _hbars(
        "What the top sites serve an AI agent",
        f"n = {n} sites analyzed (human fetch OK) · rates are independent, not a partition",
        rows,
    )


def crawlers_svg(s: dict) -> str:
    rows = []
    for ident in AI_IDENTITIES:
        b = s["per_bot"].get(ident.key)
        if not b or not b["denom"]:
            continue
        rows.append((ident.label, b["pct_blocked"], _C["block"],
                     f"{b['pct_blocked']:.1f}%  ({b['blocked']}/{b['denom']})"))
    return _hbars(
        "How often each AI crawler is blocked",
        "share of sites that returned a 4xx/5xx to this crawler but not to a human",
        rows,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render study figures as SVG.")
    p.add_argument("results", help="JSONL produced by the study runner / scan")
    p.add_argument("--out-dir", default="study/figures")
    args = p.parse_args(argv)

    with open(args.results, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    s = summarize(records)
    os.makedirs(args.out_dir, exist_ok=True)
    for name, svg in (("spectrum.svg", spectrum_svg(s)),
                      ("crawler_blocks.svg", crawlers_svg(s))):
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
