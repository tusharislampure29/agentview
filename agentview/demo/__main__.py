"""Launch the demo: ``python -m agentview.demo`` (honours HOST/PORT env vars)."""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "agentview.demo.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
