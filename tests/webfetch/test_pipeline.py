"""Tests for webfetch.core.pipeline — robust_fetch, fetch_http, _build_browser_result."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.webfetch.core.models import FetchConfig, FetchResult
from nanobot.webfetch.core.pipeline import fetch_http, robust_fetch
from tests.webfetch.conftest import GOOD_HTML, SPA_HTML


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

class TestUrlNormalisation:
    async def test_adds_https_prefix(self):
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("example.com")
            assert r.url == "https://example.com"

    async def test_strips_whitespace(self):
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("  https://example.com  ")
            assert r.url == "https://example.com"

    async def test_keeps_http_scheme(self):
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "http://example.com")
            r = await robust_fetch("http://example.com")
            assert r.url == "http://example.com"


# ---------------------------------------------------------------------------
# HTTP fast path (mocked)
# ---------------------------------------------------------------------------

class TestHttpFastPath:
    async def test_good_html_stays_on_http(self):
        """Good HTML + good text → no escalation, source_tier=http."""
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("https://example.com")
            assert r.source_tier == "http"
            assert r.status_code == 200
            assert r.needs_browser_reason is None
            assert r.ok is True

    async def test_http_error_returns_error_result(self):
        """HTTP fetch raises → ok=False, error set."""
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.side_effect = RuntimeError("connection refused")
            r = await robust_fetch("https://down.example.com")
            assert r.ok is False
            assert r.source_tier == "http"
            assert "connection refused" in r.error
            assert r.needs_browser_reason == "http_fetch_error"

    async def test_default_config_used_when_none(self):
        """robust_fetch(url, cfg=None) uses FetchConfig defaults."""
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("https://example.com", cfg=None)
            assert r.ok is True


# ---------------------------------------------------------------------------
# Browser escalation (mocked)
# ---------------------------------------------------------------------------

class TestBrowserEscalation:
    async def test_spa_triggers_browser_fallback(self):
        """SPA HTML → escalate to browser."""
        padded_spa = SPA_HTML + (" " * (8 * 1024))  # pass size check
        browser_html = GOOD_HTML
        browser_body = "Real content from browser with sentences. " * 10

        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http, \
             patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_http.return_value = (200, padded_spa, "https://spa.example.com")
            mock_browser.return_value = (
                browser_html, "https://spa.example.com", browser_body, "SPA App", [], []
            )
            r = await robust_fetch("https://spa.example.com")
            assert r.source_tier == "browser"
            assert r.needs_browser_reason == "spa_signal_detected"
            mock_browser.assert_called_once()

    async def test_browser_fallback_failure_returns_http_result(self):
        """Browser fallback raises → fall back to HTTP result."""
        padded_spa = SPA_HTML + (" " * (8 * 1024))

        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http, \
             patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_http.return_value = (200, padded_spa, "https://spa.example.com")
            mock_browser.side_effect = RuntimeError("playwright crashed")
            r = await robust_fetch("https://spa.example.com")
            assert r.source_tier == "http"
            assert "playwright crashed" in r.error

    async def test_pdf_url_skips_browser(self):
        """PDF URL → no browser escalation even if quality is low."""
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http, \
             patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_http.return_value = (200, "<html>short</html>", "https://example.com/doc.pdf")
            r = await robust_fetch("https://example.com/doc.pdf")
            assert r.source_tier == "http"
            assert "non-HTML" in (r.error or "")
            mock_browser.assert_not_called()


# ---------------------------------------------------------------------------
# Force browser / discovery mode (mocked)
# ---------------------------------------------------------------------------

class TestForceBrowser:
    async def test_force_browser_skips_http(self):
        """force_browser=True → no HTTP call, goes straight to browser."""
        browser_body = "Browser content with real sentences. " * 10
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http, \
             patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_browser.return_value = (
                GOOD_HTML, "https://example.com", browser_body, "Title", [], []
            )
            r = await robust_fetch("https://example.com", force_browser=True)
            assert r.source_tier == "browser"
            assert r.needs_browser_reason == "forced"
            mock_http.assert_not_called()

    async def test_force_browser_failure(self):
        """force_browser=True + browser fails → error result."""
        with patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_browser.side_effect = RuntimeError("no chromium")
            r = await robust_fetch("https://example.com", force_browser=True)
            assert r.ok is False
            assert "no chromium" in r.error


class TestDiscoveryMode:
    async def test_discovery_mode_skips_http(self):
        """discovery_mode=True → goes to browser with discovery."""
        browser_body = "Browser content with real sentences. " * 10
        discovered = ["Item 1 with enough text to pass", "Item 2 with enough text to pass"]
        actions = ["click:See More", "click:Next"]

        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http, \
             patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_browser.return_value = (
                GOOD_HTML, "https://example.com", browser_body, "Title", discovered, actions
            )
            r = await robust_fetch("https://example.com", discovery_mode=True)
            assert r.source_tier == "browser"
            assert r.needs_browser_reason == "discovery_mode"
            assert r.discovered_items == 2
            assert r.discovery_actions == actions
            assert "[Discovery Items]" in r.content
            mock_http.assert_not_called()

    async def test_discovery_mode_no_items(self):
        """discovery_mode=True but no items discovered → still ok if content good."""
        browser_body = "Substantial page content with proper sentences. " * 10
        with patch("nanobot.webfetch.core.pipeline.fetch_browser", new_callable=AsyncMock) as mock_browser:
            mock_browser.return_value = (
                GOOD_HTML, "https://example.com", browser_body, "Title", [], []
            )
            r = await robust_fetch("https://example.com", discovery_mode=True)
            assert r.discovered_items == 0
            assert "[Discovery Items]" not in r.content


# ---------------------------------------------------------------------------
# FetchResult field consistency
# ---------------------------------------------------------------------------

class TestResultFields:
    async def test_result_always_has_required_fields(self):
        """Every result from robust_fetch must have all FetchResult fields."""
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("https://example.com")

        d = r.to_dict()
        required = {
            "ok", "url", "final_url", "title", "content", "source_tier",
            "status_code", "needs_browser_reason", "extractor", "error",
            "discovery_actions", "discovered_items",
        }
        assert required == set(d.keys())

    async def test_error_result_has_required_fields(self):
        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            mock_http.side_effect = RuntimeError("fail")
            r = await robust_fetch("https://example.com")

        d = r.to_dict()
        assert "ok" in d
        assert "error" in d
        assert d["ok"] is False
