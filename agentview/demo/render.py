"""Back-compat shim.

The side-by-side diff rendering moved up to :mod:`agentview.htmlview` so the CLI's
``--html`` report and this web demo can share one implementation without the CLI
depending on the demo package. This module re-exports the pieces the demo (and its
tests) import by name.
"""
from __future__ import annotations

from ..htmlview import (  # noqa: F401 — re-exported for the demo + tests
    VERDICT_BLURB,
    choose_ai_identity,
    diff_columns,
    render_result,
)

__all__ = ["VERDICT_BLURB", "choose_ai_identity", "diff_columns", "render_result"]
