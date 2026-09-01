# Deploying the demo

The `agentview` web demo (`python -m agentview.demo`) lets anyone paste a URL and
see the human view vs the AI view side by side. This guide covers running it as a
public instance safely.

## Read this first — the security posture

The demo fetches a **user-supplied URL** server-side, which is a classic SSRF
surface. agentview defends it in depth:

- the target host must resolve **only** to globally-routable addresses (no
  loopback/private/link-local/CGNAT/reserved), checked up front **and** re-checked
  on every redirect hop;
- `AGENTVIEW_PUBLIC=1` caps concurrent analyses (each fans out ~15 outbound GETs),
  tightens the per-IP rate limit, and sheds load with a `503` instead of letting
  fan-out pile up;
- a strict `Content-Security-Policy` (the demo ships zero JavaScript) and
  `nosniff` are sent on every response;
- the analysis is read-only and only ever issues `GET`s.

**Residual risk:** a DNS-rebinding window remains — the guard resolves a name, then
the HTTP client resolves it again to connect, so a hostile domain could flip to an
internal address in between. For an untrusted public deployment either

1. run it behind your platform's egress firewall (block RFC-1918 / link-local from
   the container), which most PaaS let you do, **or**
2. keep it to the built-in examples only (don't advertise the paste box) — the
   `/?demo=cloaking` example needs no outbound fetch at all.

Never point a public instance at a network that has anything private reachable from it.

## Environment variables

| var | default | what it does |
| --- | --- | --- |
| `AGENTVIEW_PUBLIC` | off | Turn on public hardening (concurrency cap + tighter rate + load-shed). Set to `1` for any internet-facing deploy. |
| `AGENTVIEW_MAX_CONCURRENCY` | `4` public / `16` local | Max analyses running at once (the real DoS backstop). |
| `AGENTVIEW_RATE_MAX` | `6` public / `12` local | Analyses per client IP per minute. |
| `AGENTVIEW_TRUST_XFF` | off | Honour `X-Forwarded-For` for the client IP. Enable **only** behind a proxy that sets it reliably; otherwise a client can spoof it. The concurrency cap still bounds load regardless. |
| `HOST` | `127.0.0.1` | Bind address. The Docker image sets `0.0.0.0`. |
| `PORT` | `8000` | Listen port. Platforms that inject `$PORT` (Render, Fly, HF) are picked up automatically. |

## Run it

### Locally

```bash
pip install "agentview-cli[demo]"
python -m agentview.demo            # http://127.0.0.1:8000
```

### Docker

```bash
docker build -t agentview-demo .
docker run --rm -p 8000:8000 agentview-demo      # AGENTVIEW_PUBLIC=1 is baked in
# open http://localhost:8000
```

### Render (one click)

This repo ships a [`render.yaml`](render.yaml) Blueprint. In the Render dashboard:
**New → Blueprint**, point it at your fork, deploy. Render builds the Dockerfile,
injects `$PORT`, and health-checks `/healthz`. Free tier is enough for a demo.

### Fly.io

```bash
fly launch --dockerfile Dockerfile --now
fly secrets set AGENTVIEW_PUBLIC=1 AGENTVIEW_MAX_CONCURRENCY=4 AGENTVIEW_RATE_MAX=6
```

Fly injects `$PORT` (usually 8080); the app reads it. Consider Fly's egress rules
to satisfy the SSRF note above.

### Hugging Face Spaces (Docker)

Create a **Docker** Space, push this repo, and add to the Space README front-matter:

```yaml
sdk: docker
app_port: 8000
```

Set the env vars above in the Space **Settings → Variables**. Spaces provide the
container; the same Dockerfile works unchanged.

## Health check

`GET /healthz` returns `{"ok": true}` — wire it into your platform's health probe.
