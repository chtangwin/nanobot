"""Tests for webfetch.core.models — FetchConfig, FetchResult, DEFAULT_HEADERS."""

from nanobot.webfetch.core.models import DEFAULT_HEADERS, FetchConfig, FetchResult


# ---------------------------------------------------------------------------
# FetchConfig
# ---------------------------------------------------------------------------

class TestFetchConfig:
    def test_defaults(self):
        cfg = FetchConfig()
        assert cfg.http_connect_timeout_s == 3.0
        assert cfg.http_read_timeout_s == 7.0
        assert cfg.http_retries == 2
        assert cfg.browser_timeout_s == 20.0
        assert cfg.browser_post_wait_ms == 1200
        assert cfg.min_html_bytes == 8 * 1024
        assert cfg.min_text_chars == 300
        assert cfg.discovery_max_steps == 18
        assert cfg.discovery_max_clicks == 15
        assert cfg.discovery_max_scrolls == 10
        assert cfg.discovery_stall_rounds == 3
        assert cfg.discovery_wait_ms == 1000
        assert cfg.discovery_max_items == 250

    def test_custom_overrides(self):
        cfg = FetchConfig(http_retries=5, min_text_chars=100)
        assert cfg.http_retries == 5
        assert cfg.min_text_chars == 100
        # other fields keep defaults
        assert cfg.http_connect_timeout_s == 3.0


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------

class TestFetchResult:
    def test_minimal_result(self):
        r = FetchResult(
            ok=True, url="https://example.com", final_url="https://example.com",
            title="Example", content="Hello world", source_tier="http",
            status_code=200, needs_browser_reason=None, extractor="readability",
        )
        assert r.ok is True
        assert r.error is None
        assert r.discovery_actions == []
        assert r.discovered_items == 0

    def test_to_dict_roundtrip(self):
        r = FetchResult(
            ok=False, url="https://x.com", final_url="https://x.com",
            title=None, content="", source_tier="browser",
            status_code=None, needs_browser_reason="forced",
            extractor="none", error="timeout",
            discovery_actions=["click:Next", "scroll"],
            discovered_items=42,
        )
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["ok"] is False
        assert d["discovery_actions"] == ["click:Next", "scroll"]
        assert d["discovered_items"] == 42
        assert d["error"] == "timeout"

    def test_to_dict_contains_all_fields(self):
        r = FetchResult(
            ok=True, url="u", final_url="u", title=None, content="c",
            source_tier="http", status_code=200,
            needs_browser_reason=None, extractor="raw",
        )
        d = r.to_dict()
        expected_keys = {
            "ok", "url", "final_url", "title", "content", "source_tier",
            "status_code", "needs_browser_reason", "extractor", "error",
            "discovery_actions", "discovered_items",
        }
        assert set(d.keys()) == expected_keys


# ---------------------------------------------------------------------------
# DEFAULT_HEADERS
# ---------------------------------------------------------------------------

class TestDefaultHeaders:
    def test_has_user_agent(self):
        assert "User-Agent" in DEFAULT_HEADERS
        assert "Chrome" in DEFAULT_HEADERS["User-Agent"]

    def test_has_accept(self):
        assert "Accept" in DEFAULT_HEADERS
        assert "text/html" in DEFAULT_HEADERS["Accept"]
