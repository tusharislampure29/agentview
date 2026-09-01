# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
semantic versioning.

## [0.1.0] — 2026-08-26

First public release.

### Added
- **Measurement engine** — fetches a URL under a human desktop-Chrome identity and
  the seven documented AI-crawler identities (GPTBot, ChatGPT-User, OAI-SearchBot,
  ClaudeBot, Claude-User, PerplexityBot, Perplexity-User), holding everything but
  the `User-Agent` constant.
- **Differential analysis** — visible-text diff (`SequenceMatcher`) plus detectors
  for invisible unicode, CSS-hidden text, instruction-bearing HTML comments,
  injection phrases, chat-role control tokens, and answer-engine manipulation
  directives. A signal only counts if it is shown to the AI but **not** the human.
- **Agent-file audit** — fetches and scans `llms.txt`, `llms-full.txt`, `ai.txt`,
  `agents.json`, and the well-known variants, rejecting SPA soft-404s.
- **CLI** — `agentview check <url>` (single-URL report; `--html PATH` writes a
  self-contained shareable report, `--render` uses the JS-rendered baseline),
  `agentview guard <url>` (sanitize a page for safe LLM ingestion),
  `agentview scan <file>` (batch → JSONL dataset), `agentview stats <jsonl>`
  (headline statistics as text, JSON, or Markdown).
- **Guard (defense)** — `agentview.guard.sanitize(html)` and `agentview guard
  <url>` strip content aimed at the model but hidden from a human (invisible
  unicode, CSS-hidden blocks, instruction-bearing comments, chat-template control
  tokens) and return clean text plus a report of what was removed. Visible
  injection phrases are flagged, not deleted, unless `--aggressive` is set. Turns
  the project from a measurement into a tool you can put in front of an agent.
- **Longitudinal watch (cloaking canary)** — `agentview.watch.watch_once(...)` and
  `agentview watch <input>` keep a small local JSON snapshot of each site's verdict
  and signals and, on each run, report only what changed since last time — flagging
  an *escalation* when a site gets more agent-targeting. `--fail-on-escalation`
  exits nonzero for cron/CI alerting. Turns a one-shot check into a monitor.
- **Cloaking-mechanism attribution** — `agentview.attribution.attribute(url)` and
  `agentview why <url>` flip one request attribute at a time (named crawler UA vs a
  generic bot UA, missing Accept-Language, missing browser client-hints) and report
  which one a cloaking site keys on — or that no single flip triggers it. Explains
  *how* a site detects the bot, not just *that* it does.
- **Injection efficacy harness** — `agentview.efficacy.measure_efficacy(...)` and
  `agentview efficacy <url>` (or `--demo`) feed the human view and the AI view to a
  real model on one benign task and report, differentially, whether the agent-only
  content changed the model's answer — the first measurement of whether a cloak
  *works*, not just whether it's present. Provider adapters (OpenAI / Anthropic)
  are plain `httpx` calls (no new dependency); the logic is unit-tested with a fake
  model. Pure text-in/text-out — the model gets no tools and its output is never
  executed.
- **Study harness** — reproducible Tranco-based seed builder, a resumable
  process-pool runner, and a zero-dependency SVG chart generator.
- **Demo** — a FastAPI paste-a-URL app showing the human view vs the AI view side
  by side with the diff highlighted, an SSRF guard, per-IP rate limiting, a JSON
  API, and a built-in defanged synthetic example. An opt-in public-hardening mode
  (`AGENTVIEW_PUBLIC=1`: concurrency cap, tighter rate limit, load-shedding, strict
  CSP) plus a `Dockerfile`, a Render blueprint, and `DEPLOY.md` for hosting it.
- **Optional JS-rendered human baseline** (`--render`, the `[render]` extra) — a
  headless-Chromium view of the page as a person actually sees it after JavaScript
  runs, while AI views stay raw HTML as the crawlers consume them. Catches
  SPA/JS cloaking a raw-HTML baseline is structurally blind to. Off by default so
  the engine stays a two-dependency, reproducible tool.
- 96 offline tests; CI across Python 3.10–3.12 on Linux/Windows/macOS.
