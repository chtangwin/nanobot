"""Tests for webfetch.core.quality — SPA detection, quality heuristics, escalation."""

import pytest

from nanobot.webfetch.core.models import FetchConfig
from nanobot.webfetch.core.quality import (
    contains_spa_signals,
    is_low_quality_text,
    should_escalate_to_browser,
)
from tests.webfetch.conftest import GOOD_HTML, NAV_ONLY_HTML, SPA_HTML, TINY_HTML


# ---------------------------------------------------------------------------
# contains_spa_signals
# ---------------------------------------------------------------------------

class TestContainsSpaSignals:
    def test_detects_react_root(self):
        assert contains_spa_signals('<div id="root"></div>') is True

    def test_detects_vue_app(self):
        assert contains_spa_signals('<div id="app"></div>') is True

    def test_detects_next_data(self):
        assert contains_spa_signals("<script>__NEXT_DATA__={}</script>") is True

    def test_detects_nuxt(self):
        assert contains_spa_signals("<script>window.__NUXT__={}</script>") is True

    def test_detects_webpack_chunk(self):
        assert contains_spa_signals('<script src="/chunk.abc123.js"></script>') is True

    def test_detects_enable_javascript(self):
        assert contains_spa_signals("<noscript>Please enable javascript</noscript>") is True

    def test_plain_html_no_signal(self):
        assert contains_spa_signals(GOOD_HTML) is False

    def test_empty_html(self):
        assert contains_spa_signals("") is False

    def test_combined_spa_html(self):
        assert contains_spa_signals(SPA_HTML) is True


# ---------------------------------------------------------------------------
# is_low_quality_text
# ---------------------------------------------------------------------------

class TestIsLowQualityText:
    def test_empty_is_low_quality(self):
        assert is_low_quality_text("") is True

    def test_whitespace_only_is_low_quality(self):
        assert is_low_quality_text("   \n\n  ") is True

    def test_good_article_is_not_low_quality(self):
        text = (
            "This is a well-written article about technology. "
            "It covers many important topics. The author discusses "
            "various aspects of modern computing. Each point is "
            "supported by evidence and reasoning. The conclusion "
            "summarizes the key findings effectively."
        )
        assert is_low_quality_text(text) is False

    def test_nav_heavy_text_is_low_quality(self):
        # Many nav keywords, few sentences
        text = "Home About Contact Privacy Terms Login Sign In Menu Tools API"
        assert is_low_quality_text(text) is True

    def test_many_words_no_punctuation_is_low_quality(self):
        # 40+ words with zero sentence endings
        words = " ".join(f"word{i}" for i in range(50))
        assert is_low_quality_text(words) is True

    def test_many_short_lines_is_low_quality(self):
        # 15+ lines where 70%+ are <= 24 chars
        lines = "\n".join(["Short line"] * 20)
        assert is_low_quality_text(lines) is True

    def test_few_short_lines_is_ok(self):
        # Only 5 short lines — below the 15-line threshold
        lines = "\n".join(["Short line"] * 5)
        assert is_low_quality_text(lines) is False

    def test_mixed_content_with_sentences(self):
        text = (
            "Home About Contact\n"
            "This is a real article with sentences. "
            "It has enough punctuation to not be flagged. "
            "The quality checker should let it pass."
        )
        assert is_low_quality_text(text) is False


# ---------------------------------------------------------------------------
# should_escalate_to_browser
# ---------------------------------------------------------------------------

class TestShouldEscalateToBrowser:
    @pytest.fixture
    def cfg(self):
        return FetchConfig()

    # --- HTTP status triggers ---
    @pytest.mark.parametrize("code", [403, 429, 500, 502, 503, 504])
    def test_bad_status_triggers_escalation(self, cfg, code):
        reason = should_escalate_to_browser(code, GOOD_HTML, "text " * 100, cfg)
        assert reason == f"http_status_{code}"

    def test_200_no_escalation_for_good_content(self, cfg):
        good_text = (
            "This is a substantial article with real content. "
            "It has proper sentences and punctuation. "
            "The text is long enough to pass quality checks easily."
        ) * 3
        reason = should_escalate_to_browser(200, GOOD_HTML, good_text, cfg)
        assert reason is None

    # --- HTML size trigger ---
    def test_tiny_html_triggers_escalation(self, cfg):
        reason = should_escalate_to_browser(200, TINY_HTML, "Hi", cfg)
        assert reason == "html_too_small"

    # --- SPA signal trigger ---
    def test_spa_html_triggers_escalation(self, cfg):
        # SPA HTML is large enough to pass size check but has SPA signals
        padded_spa = SPA_HTML + (" " * cfg.min_html_bytes)
        reason = should_escalate_to_browser(200, padded_spa, "text " * 100 + ".", cfg)
        assert reason == "spa_signal_detected"

    # --- Short text trigger ---
    def test_short_text_triggers_escalation(self, cfg):
        big_html = "<html>" + ("x" * cfg.min_html_bytes) + "</html>"
        reason = should_escalate_to_browser(200, big_html, "short", cfg)
        assert reason == "text_too_short"

    # --- Low quality trigger ---
    def test_low_quality_text_triggers_escalation(self, cfg):
        big_html = "<html>" + ("x" * cfg.min_html_bytes) + "</html>"
        nav_text = " ".join(f"word{i}" for i in range(60))  # 60 words, no punctuation
        reason = should_escalate_to_browser(200, big_html, nav_text, cfg)
        assert reason == "low_content_quality"

    # --- Priority order ---
    def test_status_takes_priority_over_spa(self, cfg):
        padded_spa = SPA_HTML + (" " * cfg.min_html_bytes)
        reason = should_escalate_to_browser(403, padded_spa, "text " * 100, cfg)
        assert reason == "http_status_403"

    def test_html_size_takes_priority_over_spa(self, cfg):
        reason = should_escalate_to_browser(200, SPA_HTML, "short", cfg)
        # SPA_HTML is tiny, so html_too_small fires first
        assert reason == "html_too_small"

    def test_none_status_code_no_crash(self, cfg):
        reason = should_escalate_to_browser(None, GOOD_HTML, "text " * 100 + ".", cfg)
        # None is not in {403,429,...}, so no status trigger; check other heuristics
        assert reason is None or isinstance(reason, str)
