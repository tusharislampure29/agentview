# Security Policy

agentview fetches **public** web pages read-only and compares them. Two kinds of
issue matter here:

1. **A vulnerability in agentview itself** — most importantly in the demo server,
   which fetches a *user-supplied* URL and is therefore an SSRF surface. If you can
   make the demo fetch a private/internal address, bypass the rate limit, or return
   another user's data, that's a category-1 report.
2. **A missed or mis-classified signal** — a real case of agent-directed content
   divergence the detectors don't catch, or a false positive they raise. File these
   as normal issues *unless* public disclosure would expose a live, exploitable
   injection on a third-party site — in that case report privately.

## Reporting

Report category-1 issues privately via GitHub's
**[Report a vulnerability](https://github.com/tusharislampure29/agentview/security/advisories/new)**
(Security → Advisories), or email **tusharislampure@gmail.com**.

Please include what you observed vs. expected, a minimal reproduction, and the
commit you're on. I'll acknowledge within a few days and aim for a fix or clear
disposition within two weeks, and will credit you unless you'd rather stay anonymous.

## Responsible use

- agentview is a **measurement** tool. It sends normal `GET` requests with honestly
  declared crawler User-Agents; it does not attempt to bypass authentication, defeat
  bot-detection, or evade fingerprinting.
- Any live exfiltration payload found on a real site is **defanged** before it is
  shown or published — snippets are truncated and never rendered as active content.
- Respect target sites: the batch runner is rate-limited across hosts, and you
  should keep it that way. Don't point the scanner at sites you have no business
  scanning.
