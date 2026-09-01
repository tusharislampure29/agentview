# agentview public demo — a minimal image that serves the paste-a-URL web app.
#
# It installs only the [demo] extra: the hosted demo deliberately does NOT use
# --render (no headless browser), which keeps the image small and the outbound
# surface to plain HTTP GETs. AGENTVIEW_PUBLIC=1 turns on the concurrency cap,
# tighter rate limit, and load-shedding described in DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    AGENTVIEW_PUBLIC=1

WORKDIR /app

# Copy just what the build needs, then install. (Small project — one layer is fine.)
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY agentview ./agentview
RUN pip install --upgrade pip && pip install ".[demo]"

# Drop root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
# The entrypoint honours $HOST/$PORT (see agentview/demo/__main__.py), so the same
# image works on any platform that injects $PORT (Render, Fly, Hugging Face, …).
CMD ["python", "-m", "agentview.demo"]
