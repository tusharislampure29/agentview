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
- **CLI** — `agentview check <url>` (single-URL report), `agentview scan <file>`
  (batch → JSONL dataset), `agentview stats <jsonl>` (headline statistics as text,
  JSON, or Markdown).
- **Study harness** — reproducible Tranco-based seed builder, a resumable
  process-pool runner, and a zero-dependency SVG chart generator.
- **Demo** — a FastAPI paste-a-URL app showing the human view vs the AI view side
  by side with the diff highlighted, an SSRF guard, per-IP rate limiting, a JSON
  API, and a built-in defanged synthetic example.
- 40 offline tests; CI across Python 3.10–3.12 on Linux/Windows/macOS.
