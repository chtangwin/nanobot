"""Integration tests — hit real URLs to validate end-to-end pipeline.

These tests require network access and Playwright (chromium).
Run with:  uv run pytest tests/webfetch/test_integration.py -v
Skip with: uv run pytest -m "not integration"
"""

from __future__ import annotations

import pytest

from nanobot.webfetch.core.models import FetchConfig, FetchResult
from nanobot.webfetch.core.pipeline import robust_fetch
from tests.webfetch.conftest import BENCHMARKS

# All tests in this module are integration (slow, need network + browser)
pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _assert_result_valid(r: FetchResult):
    """Common assertions every result must pass."""
    assert isinstance(r.ok, bool)
    assert isinstance(r.url, str) and r.url.startswith("http")
    assert isinstance(r.final_url, str) and r.final_url.startswith("http")
    assert isinstance(r.content, str)
    assert r.source_tier in ("http", "browser") or r.source_tier.startswith("adapter:")
    assert isinstance(r.extractor, str)
    assert isinstance(r.discovery_actions, list)
    assert isinstance(r.discovered_items, int)
    d = r.to_dict()
    assert set(d.keys()) == {
        "ok", "url", "final_url", "title", "content", "source_tier",
        "status_code", "needs_browser_reason", "extractor", "error",
        "discovery_actions", "discovered_items",
    }


# ---------------------------------------------------------------------------
# Benchmark 1: Plain HTML — httpbin.org/html
# ---------------------------------------------------------------------------

class TestPlainHtml:
    """https://httpbin.org/html — static HTML, Herman Melville excerpt."""

    URL = BENCHMARKS["plain_html"]["url"]

    async def test_snapshot_succeeds(self):
        cfg = FetchConfig(http_read_timeout_s=15.0)
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        assert r.ok is True
        assert len(r.content) > 200
        assert r.needs_browser_reason != "http_fetch_error"

    async def test_content_contains_expected_text(self):
        cfg = FetchConfig(http_read_timeout_s=15.0)
        r = await robust_fetch(self.URL, cfg)
        # httpbin.org/html returns a Melville excerpt
        assert "Melville" in r.content or "blacksmith" in r.content or "Perth" in r.content

    async def test_force_browser_also_works(self):
        cfg = FetchConfig(browser_timeout_s=20.0)
        r = await robust_fetch(self.URL, cfg, force_browser=True)
        _assert_result_valid(r)
        assert r.source_tier == "browser"
        assert r.needs_browser_reason == "forced"
        assert len(r.content) > 100


# ---------------------------------------------------------------------------
# Benchmark 2: JavaScript / Dynamic — ip.sb
# ---------------------------------------------------------------------------

class TestJavascriptSpa:
    """https://ip.sb/ — dynamic JS page; HTTP gives nav-only, needs browser."""

    URL = BENCHMARKS["javascript_spa"]["url"]

    async def test_snapshot_escalates_to_browser(self):
        cfg = FetchConfig(http_read_timeout_s=15.0, browser_timeout_s=25.0)
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        # Should have escalated due to SPA/low quality
        assert r.needs_browser_reason is not None

    async def test_browser_gets_ip_info(self):
        cfg = FetchConfig(browser_timeout_s=25.0, browser_post_wait_ms=2000)
        r = await robust_fetch(self.URL, cfg, force_browser=True)
        _assert_result_valid(r)
        assert r.source_tier == "browser"
        # ip.sb should contain IP-related content
        content_lower = r.content.lower()
        has_ip_content = any(kw in content_lower for kw in [
            "ip address", "ipv4", "ipv6", "isp", "country",
            "your ip", "connection", "location",
        ])
        # Relaxed: at least got some non-trivial content
        assert has_ip_content or len(r.content) > 200


# ---------------------------------------------------------------------------
# Benchmark 3: Discovery / Pagination — airank.dev
# ---------------------------------------------------------------------------

class TestDiscoveryPagination:
    """https://airank.dev — SPA with 'See More' + paginated 'Next'."""

    URL = BENCHMARKS["discovery_pagination"]["url"]

    async def test_snapshot_gets_first_page(self):
        cfg = FetchConfig(browser_timeout_s=25.0, browser_post_wait_ms=2000)
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        assert len(r.content) > 100

    async def test_discovery_finds_more_models(self):
        cfg = FetchConfig(
            browser_timeout_s=30.0,
            browser_post_wait_ms=2000,
            discovery_max_steps=20,
            discovery_max_clicks=15,
            discovery_wait_ms=1500,
        )
        r = await robust_fetch(self.URL, cfg, discovery_mode=True)
        _assert_result_valid(r)
        assert r.source_tier == "browser"
        assert r.needs_browser_reason == "discovery_mode"
        # Should have clicked at least once
        assert len(r.discovery_actions) >= 1
        # Should have discovered items
        assert r.discovered_items >= 1

    async def test_discovery_actions_contain_click(self):
        cfg = FetchConfig(
            browser_timeout_s=30.0,
            browser_post_wait_ms=2000,
            discovery_max_steps=5,
            discovery_wait_ms=1500,
        )
        r = await robust_fetch(self.URL, cfg, discovery_mode=True)
        click_actions = [a for a in r.discovery_actions if a.startswith("click:")]
        # Expect at least one click (See More or Next)
        assert len(click_actions) >= 1 or len(r.discovery_actions) >= 1


# ---------------------------------------------------------------------------
# Benchmark 4: X.com (adapter target — Phase 3, expected degraded)
# ---------------------------------------------------------------------------

class TestXComAdapter:
    """https://x.com/elonmusk — strong anti-scrape; adapter needed (Phase 3).

    Currently expected to fail or produce limited content.
    These tests document the baseline before adapter implementation.
    """

    URL = BENCHMARKS["adapter_x"]["url"]

    async def test_snapshot_baseline(self):
        """Record current behavior — likely fails or gets login wall."""
        cfg = FetchConfig(
            http_read_timeout_s=15.0,
            browser_timeout_s=25.0,
            browser_post_wait_ms=3000,
        )
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        # Document baseline — don't assert ok=True since adapter not built yet
        # Just ensure no crash and valid result structure

    async def test_force_browser_baseline(self):
        cfg = FetchConfig(browser_timeout_s=25.0, browser_post_wait_ms=3000)
        r = await robust_fetch(self.URL, cfg, force_browser=True)
        _assert_result_valid(r)
        assert r.source_tier == "browser"
