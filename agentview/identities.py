"""The identities we fetch each page as.

A realistic desktop-Chrome UA stands in for a human visitor; the rest are the
documented user-agents of the major AI crawlers and live fetchers (per each
vendor's public bot docs). Two flavours matter and often behave differently:

* *indexers* (GPTBot, ClaudeBot, PerplexityBot) — crawl to train/index;
* *live fetchers* (ChatGPT-User, Claude-User, Perplexity-User) — pull a page
  right now because a person asked the assistant about it. The live fetchers are
  the higher-stakes target: their output is read straight back to a user.
"""
from __future__ import annotations

from .models import Audience, Identity

_HUMAN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

IDENTITIES: list[Identity] = [
    Identity("human", "Human (desktop Chrome)", _HUMAN_UA, Audience.HUMAN),
    Identity(
        "gptbot", "GPTBot (OpenAI indexer)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "GPTBot/1.2; +https://openai.com/gptbot",
        Audience.AI,
    ),
    Identity(
        "chatgpt-user", "ChatGPT-User (OpenAI live fetch)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "ChatGPT-User/1.0; +https://openai.com/bot",
        Audience.AI,
    ),
    Identity(
        "oai-searchbot", "OAI-SearchBot (OpenAI search)",
        "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)",
        Audience.AI,
    ),
    Identity(
        "claudebot", "ClaudeBot (Anthropic indexer)",
        "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
        Audience.AI,
    ),
    Identity(
        "claude-user", "Claude-User (Anthropic live fetch)",
        "Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
        Audience.AI,
    ),
    Identity(
        "perplexitybot", "PerplexityBot (indexer)",
        "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://www.perplexity.ai/perplexitybot)",
        Audience.AI,
    ),
    Identity(
        "perplexity-user", "Perplexity-User (live fetch)",
        "Mozilla/5.0 (compatible; Perplexity-User/1.0; +https://www.perplexity.ai/perplexity-user)",
        Audience.AI,
    ),
]

HUMAN: Identity = IDENTITIES[0]
AI_IDENTITIES: list[Identity] = [i for i in IDENTITIES if i.audience is Audience.AI]


def by_key(key: str) -> Identity | None:
    return next((i for i in IDENTITIES if i.key == key), None)
