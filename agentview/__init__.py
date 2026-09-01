"""agentview — measure the gap between the web humans see and the web AI agents see."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # The installed distribution is the single source of truth (matches pyproject),
    # so `agentview --version` can never drift from the published package version.
    __version__ = _pkg_version("agentview-cli")
except PackageNotFoundError:  # running from a source checkout with no install
    __version__ = "0.1.2"
