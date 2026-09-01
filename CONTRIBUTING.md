# Contributing to agentview

Thanks for taking a look. This started as a question I couldn't find an answer to —
*how much of the web serves AI agents a different page than it serves me?* —
and contributions that make the measurement sharper or the detectors more accurate
are very welcome.

## Ways to help

- **Detector precision/recall.** The heuristics live in `agentview/detectors.py`.
  If you find a false positive (a benign page flagged) or a false negative (real
  agent-targeting missed), that's the most valuable kind of issue — ideally with
  the URL and the snippet.
- **Agent-file coverage.** New "instructions for AI" conventions
  (`agentview/agentfiles.py`) — additional well-known paths, better soft-404
  rejection.
- **Study seeds.** Category lists (news, e-commerce, docs, job boards) beyond the
  Tranco ranking make the prevalence numbers more representative.

## Development setup

The engine depends only on `httpx` + `beautifulsoup4`. The demo adds
`fastapi` + `uvicorn`.

```bash
git clone https://github.com/tusharislampure29/agentview
cd agentview
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -e ".[demo,dev]"
pytest -q
```

Run the demo locally:

```bash
python -m agentview.demo      # http://127.0.0.1:8000
```

## Before you open a pull request

- `pytest -q` passes (currently 74 tests, all offline — no network needed).
- If you touch a detector, add or update a case in `tests/test_core.py` and keep
  the **differential** principle intact: a signal only counts if it's shown to the
  AI but *not* the human. That false-positive control is the whole credibility of
  the project — don't regress it.
- No hardcoded secrets; use obviously-fake placeholders in fixtures.

## Style

- Python 3.10+, small functions, explicit names.
- Comments explain the *why*, not the *what*.
- Every finding must carry a snippet so a human can adjudicate it.

## Reporting security issues

The demo fetches user-supplied URLs, so it has an SSRF surface. Please don't open a
public issue for that class of bug — see [SECURITY.md](SECURITY.md).
