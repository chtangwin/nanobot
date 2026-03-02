"""Shared fixtures and benchmark target definitions for webfetch tests."""

from __future__ import annotations

import pytest

from nanobot.webfetch.core.models import FetchConfig


# ---------------------------------------------------------------------------
# Benchmark targets — canonical URLs used across integration tests
# ---------------------------------------------------------------------------

BENCHMARKS = {
    "plain_html": {
        "url": "https://httpbin.org/html",
        "description": "Static HTML page (Herman Melville excerpt). Should succeed via HTTP.",
        "expect_tier": "http",  # may escalate if html < 8KB
    },
    "javascript_spa": {
        "url": "https://ip.sb/",
        "description": "Dynamic JS page showing IP info. HTTP gives nav-only; needs browser.",
        "expect_tier": "browser",
    },
    "discovery_pagination": {
        "url": "https://airank.dev",
        "description": "SPA with 'See More' + paginated 'Next'. Needs discovery mode.",
        "expect_tier": "browser",
    },
    "adapter_x": {
        "url": "https://x.com/elonmusk",
        "description": "X/Twitter profile. Needs adapter (Phase 3). Currently expected to fail or degrade.",
        "expect_tier": "adapter:x_com",
    },
}


# ---------------------------------------------------------------------------
# Reusable HTML fixtures
# ---------------------------------------------------------------------------

# Must be >= 8KB (min_html_bytes default) to avoid html_too_small escalation
_ARTICLE_BODY = """
<p>This is a well-structured article with enough content to pass quality checks.
It contains multiple sentences with proper punctuation. The content is meaningful
and not just navigation links. We need enough words here to exceed the minimum
text character threshold that the quality assessment uses.</p>
<p>Here is another paragraph with additional detail about the topic at hand.
This ensures the text extraction has substantive content to work with and
the low-quality heuristic does not flag it as boilerplate.</p>
""" * 20  # repeat to exceed 8KB

GOOD_HTML = (
    "<!DOCTYPE html>\n<html><head><title>Test Article</title></head>\n<body>\n<article>\n"
    "<h1>Test Article Title</h1>\n"
    + _ARTICLE_BODY
    + "\n</article>\n</body></html>"
)
assert len(GOOD_HTML.encode()) > 8 * 1024, "GOOD_HTML must exceed min_html_bytes"

TINY_HTML = "<html><body><p>Hi</p></body></html>"

SPA_HTML = """<!DOCTYPE html>
<html><head><title>SPA App</title></head>
<body>
<div id="root"></div>
<script src="/static/js/chunk.abc123.js"></script>
<script>window.__NEXT_DATA__={}</script>
</body></html>"""

NAV_ONLY_HTML = """<!DOCTYPE html>
<html><head><title>Nav Site</title></head>
<body>
<nav>
""" + "\n".join(
    f"<a href='/{w}'>{w.title()}</a>"
    for w in [
        "home", "about", "contact", "privacy", "terms",
        "login", "sign in", "menu", "tools", "api",
        "blog", "docs", "faq", "support", "pricing",
        "careers", "press", "status", "partners", "legal",
    ]
) + """
</nav>
<p>Welcome</p>
</body></html>"""

SHORT_LINES_HTML = """<!DOCTYPE html>
<html><head><title>Short</title></head>
<body>
""" + "\n".join(f"<div>{chr(65 + i % 26)}</div>" for i in range(20)) + """
</body></html>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_cfg() -> FetchConfig:
    """Default FetchConfig for tests."""
    return FetchConfig()


@pytest.fixture
def fast_cfg() -> FetchConfig:
    """FetchConfig with short timeouts for faster unit tests."""
    return FetchConfig(
        http_connect_timeout_s=5.0,
        http_read_timeout_s=10.0,
        http_retries=1,
        browser_timeout_s=15.0,
        browser_post_wait_ms=800,
    )
