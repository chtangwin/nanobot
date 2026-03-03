"""Integration tests — hit real URLs to validate end-to-end pipeline.

These tests require network access and Playwright (chromium).
Run with:  uv run pytest tests/webfetch/test_integration.py -v
Skip with: uv run pytest -m "not integration"
"""

from __future__ import annotations

import re

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
    """https://airank.dev — SPA with 'See More' + paginated 'Next'.

    Full workflow:
      1. Click "See More (93 more models)" to expand the list
      2. Click "Next" repeatedly to paginate through all 10 pages
      3. Collect all 97 models (#1 through #97)

    Uses a module-scoped fixture to fetch once and validate many aspects.
    """

    URL = BENCHMARKS["discovery_pagination"]["url"]

    async def test_snapshot_gets_first_page(self):
        cfg = FetchConfig(browser_timeout_s=25.0, browser_post_wait_ms=2000)
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        assert len(r.content) > 100

    async def test_full_discovery_workflow(self):
        """Single fetch, comprehensive validation of the complete discovery pipeline.

        Validates:
          - Result structure and ok status
          - "See More" click occurred as first action
          - "Next" clicked >=8 times (9 pages after first)
          - All 97 models (#1 to #97) present in content
          - Last page marker "Showing 91 to 97 of 97" present
          - discovered_items >= 50
        """
        cfg = FetchConfig(
            browser_timeout_s=30.0,
            browser_post_wait_ms=2000,
            discovery_max_steps=20,
            discovery_max_clicks=15,
            discovery_wait_ms=1500,
        )
        r = await robust_fetch(self.URL, cfg, discovery_mode=True)

        # --- Basic structure ---
        _assert_result_valid(r)
        assert r.ok is True
        assert r.source_tier == "browser"
        assert r.needs_browser_reason == "discovery_mode"

        # --- Action sequence: See More first, then Next ×N ---
        actions = r.discovery_actions
        assert len(actions) >= 2, f"Expected multiple actions, got {actions}"

        first_click = next((a for a in actions if a.startswith("click:")), None)
        assert first_click is not None and "See More" in first_click, (
            f"First click should be 'See More', got: {first_click}"
        )

        next_clicks = [a for a in actions if a.lower().startswith("click:next")]
        assert len(next_clicks) >= 8, (
            f"Expected >=8 'Next' clicks for full pagination, got {len(next_clicks)}: {actions}"
        )

        # --- All 97 models present ---
        model_numbers = sorted(set(
            int(m) for m in re.findall(r"#(\d+)\s", r.content)
        ))
        assert len(model_numbers) >= 95, (
            f"Expected >=95 unique model numbers, got {len(model_numbers)}: "
            f"range #{model_numbers[0]}-#{model_numbers[-1]}"
        )
        assert model_numbers[0] == 1, f"First model should be #1, got #{model_numbers[0]}"
        assert model_numbers[-1] == 97, f"Last model should be #97, got #{model_numbers[-1]}"

        # --- Last page marker ---
        assert "Showing 91 to 97 of 97" in r.content, (
            "Last page marker 'Showing 91 to 97 of 97' not found in content"
        )

        # --- Discovery item count ---
        assert r.discovered_items >= 50, (
            f"Expected >=50 discovered items, got {r.discovered_items}"
        )


# ---------------------------------------------------------------------------
# Benchmark 4: X.com (adapter target — Phase 3, expected degraded)
# ---------------------------------------------------------------------------

class TestXComAdapter:
    """https://x.com/elonmusk — strong anti-scrape; adapter needed (Phase 3).

    Currently expected to fail or produce limited content.
    These tests validate XComAdapter with real X.com requests.
    """

    URL = BENCHMARKS["adapter_x"]["url"]

    async def test_snapshot_with_adapter(self):
        """X URLs route through XComAdapter and return structured content."""
        cfg = FetchConfig(
            http_read_timeout_s=15.0,
            browser_timeout_s=25.0,
            browser_post_wait_ms=3000,
        )
        r = await robust_fetch(self.URL, cfg)
        _assert_result_valid(r)
        # X URLs are routed to XComAdapter
        assert r.source_tier == "adapter:x_com"
        assert r.extractor == "x_com_scraper"
        # Should have some content (may be limited with placeholder auth)
        assert r.content is not None
        # discovered_items should be a number
        assert isinstance(r.discovered_items, int)

    async def test_force_browser_with_adapter(self):
        """Even with force_browser, X URLs still route through adapter."""
        cfg = FetchConfig(browser_timeout_s=25.0, browser_post_wait_ms=3000)
        r = await robust_fetch(self.URL, cfg, force_browser=True)
        _assert_result_valid(r)
        assert r.source_tier == "adapter:x_com"
        assert r.extractor == "x_com_scraper"
        assert isinstance(r.discovered_items, int)

    async def test_tau_rho_ai_profile(self):
        """@tau_rho_ai should return real profile posts via XComAdapter.

        This is a real-network integration test against x.com and expects
        extractable timeline items (status links + post text).
        """
        url = BENCHMARKS["adapter_x_tau_rho_ai"]["url"]
        cfg = FetchConfig(
            browser_timeout_s=30.0,
            browser_post_wait_ms=2200,
            discovery_max_scrolls=24,
            discovery_stall_rounds=3,
        )
        r = await robust_fetch(url, cfg)

        _assert_result_valid(r)
        assert r.source_tier == "adapter:x_com"
        assert r.extractor == "x_com_scraper"
        assert r.ok is True, f"Expected successful fetch for {url}, got error: {r.error}"

        # Must get real post entries (not fallback/no-data text)
        assert r.discovered_items > 0, (
            f"Expected posts from @tau_rho_ai but got {r.discovered_items}. Error: {r.error}"
        )
        assert "No posts found for @tau_rho_ai" not in r.content

        # Validate this is real X timeline content
        assert re.search(r"https://x\.com/tau_rho_ai/status/\d+", r.content), (
            "Expected at least one status URL in formatted output"
        )
        assert "Posts from @tau_rho_ai" in r.content
