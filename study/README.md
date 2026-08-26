# The agentview study

The first prevalence measurement of **agent-directed content divergence**: how many
top sites serve an AI crawler a different page than they serve a human, and what
kind of different.

Everything here is reproducible. Numbers in the top-level [README](../README.md)
and in [../docs/STUDY_RESULTS.md](../docs/STUDY_RESULTS.md) come from exactly these
commands.

## Reproduce

```bash
pip install -e ".[demo,dev]"

# 1. Build a reproducible seed list from the Tranco ranking.
#    --skip-infra drops pure CDN/DNS/API domains that never serve a page.
#    --list-id pins the exact Tranco list so the sample is regenerable.
python study/build_seeds.py --count 1000 --skip-infra --list-id 74V4X \
    -o study/seeds/tranco_top1000.txt

# 2. Run the measurement (resumable — re-run to top up; safe to Ctrl-C).
python study/run_study.py study/seeds/tranco_top1000.txt \
    -o study/results/tranco_top1000.jsonl

# 3. Aggregate the headline statistics.
agentview stats study/results/tranco_top1000.jsonl                # human-readable
agentview stats study/results/tranco_top1000.jsonl --format markdown

# 4. Render the figures (standalone SVG, no plotting library).
python study/charts.py study/results/tranco_top1000.jsonl --out-dir study/figures
```

## Files

| path | what it is |
| --- | --- |
| `build_seeds.py` | fetches the Tranco ranking, writes a pinned seed list |
| `run_study.py` | resumable process-pool runner over a seed list → JSONL |
| `charts.py` | dataset → SVG figures (spectrum, per-crawler block rate) |
| `seeds/` | the exact seed lists used (with the Tranco `list_id` in the header) |
| `results/*.jsonl` | the published dataset (one JSON record per site) |
| `figures/` | generated SVG figures |

## Dataset schema

One JSON object per line. The interesting fields:

```jsonc
{
  "url": "https://example.com",
  "verdict": "identical | benign_divergence | manipulative | adversarial | error",
  "fetches": {                      // one entry per identity (human + 7 AI crawlers)
    "human":   {"ok": true, "status": 200, "bytes": 1234, "final_url": "...", ...},
    "gptbot":  {"ok": true, "status": 403, ...}
  },
  "divergences": [                  // each AI view vs the human view
    {"identity": "gptbot", "similarity": 0.13, "length_ratio": 0.1,
     "status_differs": true, "redirect_differs": false}
  ],
  "findings": [                     // differential signals (shown to AI, not human)
    {"type": "injection_phrase", "severity": "high", "identity": "gptbot",
     "snippet": "...", "detail": "..."}
  ],
  "agent_files": [                  // llms.txt / agents.json / ... audit
    {"path": "/llms.txt", "present": true, "status": 200, "findings": [...]}
  ]
}
```

## How to read the numbers honestly

- **Denominator.** Rates are over sites where the **human** fetch returned a normal
  (`<400`) page, because that's the only case where a human-vs-AI comparison is
  meaningful. Domains that don't serve a browsable page (DNS/CDN/API infrastructure
  that survives the seed filter, or hosts that block *everyone* from this network)
  land in the `error` bucket and are excluded from rates.
- **Lower bound.** We vary only the `User-Agent`. Sites that fingerprint via TLS
  handshake, IP reputation, or JS challenges will serve us the human page even when
  we claim to be a bot — so real divergence is **higher** than what we measure.
- **Spectrum, not one scary number.** The headline splits into *blocking* (a 4xx/5xx
  to the agent) and the rarer, more interesting *altered 200 page*. We report both.
- **Findings are heuristics, not proof.** Every finding carries a snippet so it can
  be adjudicated; the `injection_phrase` class in particular fires on prose that
  merely *discusses* injection, which is why it only counts as high-severity when it
  appears in content shown to the AI but not the human.
