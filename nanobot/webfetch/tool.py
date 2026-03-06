"""Enhanced WebFetchTool: drop-in replacement for agent/tools/web.py WebFetchTool.

Uses the webfetch core pipeline (HTTP-first → quality check → browser fallback)
with optional discovery mode. Backward compatible — old calls (url only) work
unchanged; new parameters (mode, forceBrowser) are optional.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from nanobot.agent.tools.base import Tool
from nanobot.webfetch.core.models import FetchConfig
from nanobot.webfetch.core.pipeline import robust_fetch


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https", ""):
            return False, f"Only http/https allowed, got '{p.scheme}'"
        if p.scheme and not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebFetchTool(Tool):
    """Fetch URL and extract readable content with progressive escalation.

    Pipeline: HTTP fast path → quality check → browser fallback → discovery.
    """

    name = "web_fetch"
    description = (
        "Fetch a URL and extract readable text content. "
        "Works for static HTML, JS/SPA pages (auto-upgrades to browser when needed), "
        "and paginated lists. Returns JSON with text, metadata, and extraction details.\n"
        "• Default (snapshot): fast HTTP fetch, auto-escalates to browser if page is JS-rendered.\n"
        "• mode='discovery': for pages with 'Load More'/'Next' buttons or infinite scroll — "
        "automatically clicks through pagination to collect all items.\n"
        "• forceBrowser=true: skip HTTP and use browser directly (useful for known JS-heavy sites)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "mode": {
                "type": "string",
                "enum": ["snapshot", "discovery"],
                "description": (
                    "snapshot (default): fetch single page, auto-upgrades to browser for JS/SPA. "
                    "discovery: expand paginated/lazy-loaded content by clicking 'Load More', "
                    "'Next', 'See More' buttons and scrolling. Use when you need ALL items "
                    "from a list/table that spans multiple pages."
                ),
            },
            "forceBrowser": {
                "type": "boolean",
                "description": (
                    "If true, skip HTTP and go straight to browser rendering. "
                    "Useful for sites you know require JavaScript (e.g. SPAs, dashboards). "
                    "Default: false (tries fast HTTP first, upgrades only if needed)."
                ),
            },
            "maxChars": {
                "type": "integer",
                "minimum": 100,
                "description": "Maximum characters to return (default: 50000). Content is truncated if longer.",
            },
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        self.max_chars = max_chars
        self.proxy = proxy

    async def execute(
        self,
        url: str,
        mode: str = "snapshot",
        forceBrowser: bool = False,
        maxChars: int | None = None,
        # Legacy params — accepted but ignored for backward compat
        extractMode: str | None = None,
        **kwargs: Any,
    ) -> str:
        max_chars = maxChars or self.max_chars

        # Validate URL
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps(
                {"error": f"URL validation failed: {error_msg}", "url": url},
                ensure_ascii=False,
            )

        # Build config
        cfg = FetchConfig(proxy=self.proxy)

        try:
            result = await robust_fetch(
                url,
                cfg,
                force_browser=forceBrowser,
                discovery_mode=(mode == "discovery"),
            )
        except Exception as exc:
            return json.dumps(
                {"error": str(exc), "url": url, "ok": False},
                ensure_ascii=False,
            )

        # Truncate content
        content = result.content
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        # Build response — superset of old fields + new fields
        return json.dumps(
            {
                "ok": result.ok,
                "url": result.url,
                "final_url": result.final_url,
                "status_code": result.status_code,
                "title": result.title,
                "extractor": result.extractor,
                "source_tier": result.source_tier,
                "needs_browser_reason": result.needs_browser_reason,
                "truncated": truncated,
                "length": len(content),
                "text": content,
                "error": result.error,
                "discovery_actions": result.discovery_actions,
                "discovered_items": result.discovered_items,
            },
            ensure_ascii=False,
        )
