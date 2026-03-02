"""Tests for webfetch.tool — the new WebFetchTool drop-in replacement."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.webfetch.core.models import FetchResult
from nanobot.webfetch.tool import WebFetchTool


def _mock_result(**overrides) -> FetchResult:
    """Build a FetchResult with sensible defaults, overridable."""
    defaults = dict(
        ok=True, url="https://example.com", final_url="https://example.com",
        title="Example", content="Hello world. This is test content.",
        source_tier="http", status_code=200, needs_browser_reason=None,
        extractor="readability", error=None, discovery_actions=[], discovered_items=0,
    )
    defaults.update(overrides)
    return FetchResult(**defaults)


# ---------------------------------------------------------------------------
# Schema / interface
# ---------------------------------------------------------------------------

class TestToolSchema:
    def test_name_is_web_fetch(self):
        assert WebFetchTool().name == "web_fetch"

    def test_required_only_url(self):
        assert WebFetchTool().parameters["required"] == ["url"]

    def test_has_new_params(self):
        props = WebFetchTool().parameters["properties"]
        assert "mode" in props
        assert "forceBrowser" in props
        assert "maxChars" in props

    def test_mode_enum(self):
        props = WebFetchTool().parameters["properties"]
        assert props["mode"]["enum"] == ["snapshot", "discovery"]

    def test_to_schema_format(self):
        schema = WebFetchTool().to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "web_fetch"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    async def test_url_only_call(self):
        """Old-style call with just url should work."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result()
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com")
            r = json.loads(raw)
            assert r["ok"] is True
            assert r["text"] == "Hello world. This is test content."
            # Called with defaults
            mock.assert_called_once()
            _, kwargs = mock.call_args
            assert kwargs["force_browser"] is False
            assert kwargs["discovery_mode"] is False

    async def test_legacy_extractMode_accepted(self):
        """Old extractMode param is accepted (ignored) without error."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result()
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com", extractMode="markdown")
            r = json.loads(raw)
            assert r["ok"] is True

    async def test_response_has_old_fields(self):
        """Response includes fields that old callers expect."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result()
            t = WebFetchTool()
            r = json.loads(await t.execute(url="https://example.com"))
            # Old fields
            assert "url" in r
            assert "text" in r
            assert "extractor" in r
            assert "truncated" in r
            assert "length" in r

    async def test_response_has_new_fields(self):
        """Response includes new pipeline fields."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(source_tier="browser", needs_browser_reason="spa_signal_detected")
            t = WebFetchTool()
            r = json.loads(await t.execute(url="https://example.com"))
            assert r["source_tier"] == "browser"
            assert r["needs_browser_reason"] == "spa_signal_detected"
            assert "discovery_actions" in r
            assert "discovered_items" in r


# ---------------------------------------------------------------------------
# New parameters
# ---------------------------------------------------------------------------

class TestNewParams:
    async def test_mode_discovery(self):
        """mode='discovery' passes discovery_mode=True to pipeline."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(
                discovery_actions=["click:Next"], discovered_items=10,
            )
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com", mode="discovery")
            r = json.loads(raw)
            _, kwargs = mock.call_args
            assert kwargs["discovery_mode"] is True
            assert r["discovery_actions"] == ["click:Next"]
            assert r["discovered_items"] == 10

    async def test_force_browser(self):
        """forceBrowser=True passes force_browser=True to pipeline."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(source_tier="browser", needs_browser_reason="forced")
            t = WebFetchTool()
            await t.execute(url="https://example.com", forceBrowser=True)
            _, kwargs = mock.call_args
            assert kwargs["force_browser"] is True

    async def test_max_chars_truncation(self):
        """maxChars truncates content and sets truncated=True."""
        long_content = "x" * 500
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(content=long_content)
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com", maxChars=100)
            r = json.loads(raw)
            assert r["truncated"] is True
            assert r["length"] == 100
            assert len(r["text"]) == 100

    async def test_max_chars_no_truncation(self):
        """Content shorter than maxChars → truncated=False."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(content="short")
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com", maxChars=50000)
            r = json.loads(raw)
            assert r["truncated"] is False

    async def test_default_max_chars(self):
        """Constructor max_chars is used when maxChars not passed."""
        t = WebFetchTool(max_chars=200)
        long_content = "y" * 500
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(content=long_content)
            raw = await t.execute(url="https://example.com")
            r = json.loads(raw)
            assert r["truncated"] is True
            assert r["length"] == 200


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

class TestUrlValidation:
    async def test_invalid_scheme(self):
        t = WebFetchTool()
        raw = await t.execute(url="ftp://example.com")
        r = json.loads(raw)
        assert "error" in r
        assert "ftp" in r["error"]

    async def test_valid_url_passes(self):
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result()
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com")
            r = json.loads(raw)
            assert "error" not in r or r["error"] is None

    async def test_bare_domain_passes(self):
        """URL without scheme is allowed (pipeline adds https://)."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result()
            t = WebFetchTool()
            raw = await t.execute(url="example.com")
            r = json.loads(raw)
            assert "error" not in r or r["error"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_pipeline_error_in_response(self):
        """Pipeline returns ok=False with error → tool passes it through."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.return_value = _mock_result(ok=False, error="connection refused", content="")
            t = WebFetchTool()
            raw = await t.execute(url="https://down.example.com")
            r = json.loads(raw)
            assert r["ok"] is False
            assert r["error"] == "connection refused"

    async def test_pipeline_exception_handled(self):
        """If robust_fetch raises unexpectedly, tool returns JSON error."""
        with patch("nanobot.webfetch.tool.robust_fetch", new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("unexpected crash")
            t = WebFetchTool()
            raw = await t.execute(url="https://example.com")
            # Should not raise — tool catches and returns error string
            assert isinstance(raw, str)
