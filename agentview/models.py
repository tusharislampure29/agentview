"""Typed data model for a single measurement.

The pipeline is: fetch a URL under several *identities* (a human browser and the
real AI crawlers) -> diff each AI view against the human view -> scan for
adversarial signals -> reduce to one Verdict per site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Below this visible-text similarity (0..1), a human and an AI are looking at
# materially different pages. Single source of truth — imported by the analysis,
# the stats aggregation, the CLI, and the demo so they never drift apart.
DIVERGENCE_THRESHOLD = 0.90


class Audience(str, Enum):
    HUMAN = "human"
    AI = "ai"


@dataclass
class Identity:
    """One way of asking a server for a page. Only the User-Agent (and any
    ``extra_headers``) varies between identities — everything else is held
    constant so the isolated variable is *who the site thinks is asking*."""
    key: str
    label: str
    user_agent: str
    audience: Audience
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchResult:
    identity: str
    url: str
    ok: bool
    status: int | None = None
    final_url: str | None = None
    redirects: int = 0
    elapsed_ms: int = 0
    html: str = ""
    text: str = ""            # normalized visible text
    content_length: int = 0
    error: str | None = None
    rendered: bool = False    # True if this view is a JS-rendered DOM, not raw HTML


class FindingType(str, Enum):
    INVISIBLE_UNICODE = "invisible_unicode"
    HIDDEN_HTML = "hidden_html"
    HTML_COMMENT_INSTRUCTION = "html_comment_instruction"
    INJECTION_PHRASE = "injection_phrase"
    ROLE_TOKEN = "role_token"
    MANIPULATION_DIRECTIVE = "manipulation_directive"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Finding:
    type: FindingType
    severity: Severity
    identity: str            # the view the signal was found in
    snippet: str
    detail: str = ""


@dataclass
class Divergence:
    """How one AI view differs from the human view."""
    identity: str
    similarity: float        # 0..1 visible-text similarity vs the human view
    length_ratio: float      # ai_text_len / human_text_len
    status_differs: bool
    redirect_differs: bool


class Verdict(str, Enum):
    ERROR = "error"                        # could not compare (e.g. human fetch failed)
    IDENTICAL = "identical"                # human and AI see the same page
    BENIGN_DIVERGENCE = "benign_divergence"  # differs, no adversarial signal (paywall, bot-block)
    MANIPULATIVE = "manipulative"          # AI-only content steers the model's answer
    ADVERSARIAL = "adversarial"            # hidden instructions / injection aimed at the AI


@dataclass
class AgentFile:
    """One "instructions for AI" file a site may publish (llms.txt, agents.json,
    …). Present-and-benign is the common case; the interesting case is a present
    file that carries manipulation directives or injected instructions."""
    path: str
    present: bool
    status: int | None = None
    content_length: int = 0
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None


@dataclass
class SiteReport:
    url: str
    fetches: dict[str, FetchResult] = field(default_factory=dict)
    divergences: list[Divergence] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    agent_files: list[AgentFile] = field(default_factory=list)
    verdict: Verdict = Verdict.IDENTICAL
    notes: list[str] = field(default_factory=list)
