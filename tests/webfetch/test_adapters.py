"""Tests for webfetch adapters: base, registry, generic, x_com."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.webfetch.adapters.base import Adapter
from nanobot.webfetch.adapters.generic import GenericAdapter
from nanobot.webfetch.adapters.registry import AdapterRegistry, create_default_registry
from nanobot.webfetch.adapters.x_com import (
    XComAdapter,
    _find_auth_file,
    _format_posts_as_text,
    _parse_x_url,
)
from nanobot.webfetch.core.models import FetchConfig, FetchResult


# ---------------------------------------------------------------------------
# Adapter base class
# ---------------------------------------------------------------------------

class TestAdapterBase:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Adapter()

    def test_matches_exact_domain(self):
        adapter = XComAdapter()
        assert adapter.matches("x.com") is True
        assert adapter.matches("twitter.com") is True

    def test_matches_www_prefix(self):
        adapter = XComAdapter()
        assert adapter.matches("www.x.com") is True
        assert adapter.matches("www.twitter.com") is True

    def test_no_match_other_domain(self):
        adapter = XComAdapter()
        assert adapter.matches("example.com") is False
        assert adapter.matches("notx.com") is False


# ---------------------------------------------------------------------------
# AdapterRegistry
# ---------------------------------------------------------------------------

class TestAdapterRegistry:
    def test_resolve_returns_generic_by_default(self):
        reg = AdapterRegistry()
        adapter = reg.resolve("https://example.com")
        assert isinstance(adapter, GenericAdapter)
        assert adapter.name == "generic"

    def test_resolve_x_com(self):
        reg = AdapterRegistry()
        reg.register(XComAdapter())
        adapter = reg.resolve("https://x.com/elonmusk")
        assert isinstance(adapter, XComAdapter)
        assert adapter.name == "x_com"

    def test_resolve_twitter_com(self):
        reg = AdapterRegistry()
        reg.register(XComAdapter())
        adapter = reg.resolve("https://twitter.com/elonmusk")
        assert isinstance(adapter, XComAdapter)

    def test_resolve_with_www(self):
        reg = AdapterRegistry()
        reg.register(XComAdapter())
        adapter = reg.resolve("https://www.x.com/user")
        assert isinstance(adapter, XComAdapter)

    def test_resolve_bad_url_returns_generic(self):
        reg = AdapterRegistry()
        adapter = reg.resolve("not-a-url")
        assert isinstance(adapter, GenericAdapter)

    def test_registered_list(self):
        reg = AdapterRegistry()
        assert len(reg.registered) == 0
        reg.register(XComAdapter())
        assert len(reg.registered) == 1

    def test_create_default_registry_includes_x_com(self):
        reg = create_default_registry()
        adapter = reg.resolve("https://x.com/test")
        assert adapter.name == "x_com"


# ---------------------------------------------------------------------------
# GenericAdapter
# ---------------------------------------------------------------------------

class TestGenericAdapter:
    def test_name(self):
        assert GenericAdapter().name == "generic"

    def test_domains_empty(self):
        assert GenericAdapter().domains == []

    async def test_delegates_to_robust_fetch(self):
        with patch("nanobot.webfetch.adapters.generic._robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = FetchResult(
                ok=True, url="https://example.com", final_url="https://example.com",
                title="Test", content="Hello", source_tier="http",
                status_code=200, needs_browser_reason=None, extractor="readability",
            )
            adapter = GenericAdapter()
            r = await adapter.fetch("https://example.com", FetchConfig())
            assert r.ok is True
            mock.assert_called_once()


# ---------------------------------------------------------------------------
# XComAdapter — URL parsing
# ---------------------------------------------------------------------------

class TestXComUrlParsing:
    def test_profile_url(self):
        user, tid = _parse_x_url("https://x.com/elonmusk")
        assert user == "elonmusk"
        assert tid is None

    def test_profile_with_at(self):
        user, tid = _parse_x_url("https://x.com/@elonmusk")
        assert user == "elonmusk"

    def test_tweet_url(self):
        user, tid = _parse_x_url("https://x.com/user/status/12345")
        assert user == "user"
        assert tid == "12345"

    def test_twitter_domain(self):
        user, tid = _parse_x_url("https://twitter.com/user/status/99")
        assert user == "user"
        assert tid == "99"

    def test_www_prefix(self):
        user, tid = _parse_x_url("https://www.x.com/user")
        assert user == "user"

    def test_invalid_url(self):
        user, tid = _parse_x_url("https://example.com/page")
        assert user is None
        assert tid is None


# ---------------------------------------------------------------------------
# XComAdapter — post formatting
# ---------------------------------------------------------------------------

class TestXComFormatPosts:
    def test_empty_posts(self):
        text = _format_posts_as_text([], "testuser")
        assert "No posts found" in text
        assert "testuser" in text

    def test_single_post(self):
        posts = [{
            "text": "Hello world",
            "date": "2026-01-01T00:00:00.000Z",
            "likes": "42",
            "retweets": "5",
            "replies": "2",
            "url": "https://x.com/user/status/123",
            "has_media": False,
            "media": {"photos": [], "videos": []},
        }]
        text = _format_posts_as_text(posts, "user")
        assert "Hello world" in text
        assert "2026-01-01" in text
        assert "likes:42" in text
        assert "1 posts" in text

    def test_media_post(self):
        posts = [{
            "text": "",
            "date": "",
            "likes": "0",
            "retweets": "0",
            "replies": "0",
            "url": "",
            "has_media": True,
            "media": {"photos": ["https://img.com/1.jpg"], "videos": []},
        }]
        text = _format_posts_as_text(posts, "user")
        assert "Photos:" in text


# ---------------------------------------------------------------------------
# XComAdapter — fetch (mocked)
# ---------------------------------------------------------------------------

class TestXComAdapterFetch:
    async def test_invalid_url_returns_error(self):
        adapter = XComAdapter()
        r = await adapter.fetch("https://example.com/not-x", FetchConfig())
        assert r.ok is False
        assert "Could not parse" in r.error
        assert r.source_tier == "adapter:x_com"

    async def test_profile_scrape_returns_adapter_tier(self):
        """Mocked profile scrape returns correct source_tier."""
        adapter = XComAdapter()
        mock_result = FetchResult(
            ok=True, url="https://x.com/test", final_url="https://x.com/test",
            title="@test on X", content="Posts from @test",
            source_tier="adapter:x_com", status_code=None,
            needs_browser_reason=None, extractor="x_com_scraper",
            discovered_items=5,
        )
        with patch.object(adapter, "_scrape_profile", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            r = await adapter.fetch("https://x.com/test", FetchConfig())
            assert r.source_tier == "adapter:x_com"
            assert r.extractor == "x_com_scraper"

    async def test_tweet_url_uses_single_tweet(self):
        """Individual tweet URL goes through _fetch_single_tweet."""
        adapter = XComAdapter()
        mock_result = FetchResult(
            ok=True, url="https://x.com/u/status/1", final_url="https://x.com/u/status/1",
            title="Tweet", content="Single tweet",
            source_tier="adapter:x_com", status_code=None,
            needs_browser_reason=None, extractor="x_com_scraper",
        )
        with patch.object(adapter, "_fetch_single_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            r = await adapter.fetch("https://x.com/u/status/123", FetchConfig())
            mock.assert_called_once()

    async def test_playwright_missing_returns_error(self):
        """Graceful error when playwright not installed."""
        adapter = XComAdapter()
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            r = await adapter._scrape_profile("https://x.com/test", "test", FetchConfig(), False)
            assert r.ok is False
            assert "Playwright" in (r.error or "")


# ---------------------------------------------------------------------------
# Pipeline integration — adapter routing
# ---------------------------------------------------------------------------

class TestPipelineAdapterRouting:
    async def test_x_url_routes_to_adapter(self):
        """robust_fetch with x.com URL should use XComAdapter."""
        from nanobot.webfetch.core.pipeline import robust_fetch

        mock_result = FetchResult(
            ok=True, url="https://x.com/test", final_url="https://x.com/test",
            title="@test", content="Posts", source_tier="adapter:x_com",
            status_code=None, needs_browser_reason=None, extractor="x_com_scraper",
        )
        with patch("nanobot.webfetch.adapters.x_com.XComAdapter.fetch", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            r = await robust_fetch("https://x.com/test")
            assert r.source_tier == "adapter:x_com"

    async def test_normal_url_uses_generic(self):
        """Non-X URL should not hit adapter."""
        from nanobot.webfetch.core.pipeline import robust_fetch

        with patch("nanobot.webfetch.core.pipeline.fetch_http", new_callable=AsyncMock) as mock_http:
            from tests.webfetch.conftest import GOOD_HTML
            mock_http.return_value = (200, GOOD_HTML, "https://example.com")
            r = await robust_fetch("https://example.com")
            assert r.source_tier == "http"  # generic path
