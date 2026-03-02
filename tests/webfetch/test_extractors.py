"""Tests for webfetch.core.extractors — clean_text, extract_main_text, merge."""

import pytest

from nanobot.webfetch.core.extractors import (
    clean_text,
    extract_main_text,
    merge_discovered_content,
)
from tests.webfetch.conftest import GOOD_HTML, TINY_HTML


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_strips_whitespace(self):
        assert clean_text("  hello  ") == "hello"

    def test_normalizes_crlf(self):
        assert clean_text("a\r\nb\rc") == "a\nb\nc"

    def test_collapses_blank_lines(self):
        assert clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_mixed_line_endings(self):
        assert clean_text("a\r\n\r\n\r\nb\r\nc") == "a\n\nb\nc"


# ---------------------------------------------------------------------------
# extract_main_text
# ---------------------------------------------------------------------------

class TestExtractMainText:
    def test_good_html_returns_content(self):
        text, title, extractor = extract_main_text(GOOD_HTML, "https://example.com")
        assert len(text) > 50
        assert extractor in ("trafilatura", "readability")

    def test_tiny_html_returns_something(self):
        text, title, extractor = extract_main_text(TINY_HTML, "https://example.com")
        # Even tiny HTML should not crash; may return minimal text
        assert isinstance(text, str)
        assert extractor in ("trafilatura", "readability")

    def test_empty_html(self):
        text, title, extractor = extract_main_text("", "https://example.com")
        assert isinstance(text, str)

    def test_script_and_style_stripped(self):
        html = """<html><body>
        <script>var x = 1;</script>
        <style>.foo { color: red; }</style>
        <p>Real content here with enough words to be meaningful.</p>
        </body></html>"""
        text, _, _ = extract_main_text(html, "https://example.com")
        assert "var x" not in text
        assert "color: red" not in text

    def test_returns_tuple_of_three(self):
        result = extract_main_text(GOOD_HTML, "https://example.com")
        assert len(result) == 3
        text, title, extractor = result
        assert isinstance(text, str)
        assert title is None or isinstance(title, str)
        assert isinstance(extractor, str)


# ---------------------------------------------------------------------------
# merge_discovered_content
# ---------------------------------------------------------------------------

class TestMergeDiscoveredContent:
    def test_no_items_returns_base(self):
        assert merge_discovered_content("base text", []) == "base text"

    def test_appends_items(self):
        result = merge_discovered_content("base", ["item A", "item B"])
        assert "[Discovery Items]" in result
        assert "- item A" in result
        assert "- item B" in result
        assert result.startswith("base")

    def test_cleans_output(self):
        result = merge_discovered_content("  base  \n\n\n", ["x"])
        # Should not have excessive blank lines
        assert "\n\n\n" not in result
