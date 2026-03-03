"""Tests for webfetch.core.browser — _run_discovery logic with mocked pages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.webfetch.core.browser import _run_discovery, fetch_browser
from nanobot.webfetch.core.models import FetchConfig


# ---------------------------------------------------------------------------
# Helpers: mock Playwright page that matches real Playwright calling patterns
#
#   page.locator("body")          → sync, returns locator object
#   locator.inner_text()          → async, returns str
#   page.evaluate(js, arg?)       → async, returns value
#   page.wait_for_timeout(ms)     → async
# ---------------------------------------------------------------------------

def _make_mock_page(
    body_text: str = "Page content with enough words for quality.",
    evaluate_side_effects: list | None = None,
):
    """Create a mock page with the correct sync/async split."""
    page = MagicMock()  # sync base

    # page.locator("body") is sync → returns locator
    body_locator = MagicMock()
    body_locator.inner_text = AsyncMock(return_value=body_text)
    page.locator = MagicMock(return_value=body_locator)

    # page.evaluate / page.wait_for_timeout are async
    if evaluate_side_effects is not None:
        page.evaluate = AsyncMock(side_effect=evaluate_side_effects)
    else:
        page.evaluate = AsyncMock(return_value=None)

    page.wait_for_timeout = AsyncMock()

    return page


# ---------------------------------------------------------------------------
# _run_discovery unit tests
# ---------------------------------------------------------------------------

class TestRunDiscovery:
    async def test_stops_on_stall(self):
        """Discovery stops after stall_rounds of no progress."""
        cfg = FetchConfig(discovery_max_steps=10, discovery_stall_rounds=2)
        page = _make_mock_page()
        # Per step: collect_items, then try click → None, then try scroll → False
        # No items + no action = stall. After 2 stalls → break.
        page.evaluate = AsyncMock(side_effect=[
            # Step 1
            [],     # collect_items
            None,   # click_control → no target
            False,  # scroll → no movement → acted=False → break inner, stall+=1
            # Because acted=False, the loop breaks immediately in step 1
        ])

        discovered, actions = await _run_discovery(page, cfg)
        assert discovered == []
        assert actions == []

    async def test_collects_items_from_clicks(self):
        """Discovery collects items after clicking buttons."""
        cfg = FetchConfig(discovery_max_steps=6, discovery_stall_rounds=3)
        page = _make_mock_page()

        page.evaluate = AsyncMock(side_effect=[
            # Step 1: items found, click works
            ["Item one is long enough to pass", "Item two is long enough to pass"],
            "click:See More",
            # Step 2: one new item, click exhausted
            ["Item one is long enough to pass", "Item two is long enough to pass",
             "Item three long enough to pass here"],
            None,    # no click target
            False,   # no scroll → break
        ])

        discovered, actions = await _run_discovery(page, cfg)
        assert len(discovered) == 3
        assert "click:See More" in actions

    async def test_scrolls_when_no_click_target(self):
        """Discovery scrolls when click finds no target."""
        cfg = FetchConfig(discovery_max_steps=5, discovery_stall_rounds=3)
        page = _make_mock_page()

        page.evaluate = AsyncMock(side_effect=[
            # Step 1: items, no click, scroll works
            ["New item one that is quite long enough here"],
            None,   # click_control → None
            True,   # scroll → moved
            # Step 2: no new items, no click, scroll
            [],
            None,
            True,
            # Step 3: still no new items, no click, no scroll → break
            [],
            None,
            False,
        ])

        discovered, actions = await _run_discovery(page, cfg)
        scroll_actions = [a for a in actions if a == "scroll"]
        assert len(scroll_actions) >= 1

    async def test_respects_max_clicks(self):
        """Discovery stops clicking after discovery_max_clicks."""
        cfg = FetchConfig(
            discovery_max_steps=20,
            discovery_max_clicks=2,
            discovery_stall_rounds=3,
        )
        page = _make_mock_page()

        step = [0]

        async def evaluate_fn(*args, **kwargs):
            js = str(args[0]) if args else ""
            if len(args) > 1 or "maxItems" in js:
                # collect_items
                step[0] += 1
                return [f"Item {step[0]} with enough text here to pass len check"]
            elif "strongPatterns" in js:
                # click_control — always returns a click
                return "click:Next"
            elif "scrollBy" in js:
                return False
            return None

        page.evaluate = AsyncMock(side_effect=evaluate_fn)

        discovered, actions = await _run_discovery(page, cfg)
        click_actions = [a for a in actions if a.startswith("click:")]
        assert len(click_actions) <= cfg.discovery_max_clicks

    async def test_respects_max_scrolls(self):
        """Discovery stops scrolling after discovery_max_scrolls."""
        cfg = FetchConfig(
            discovery_max_steps=20,
            discovery_max_scrolls=2,
            discovery_stall_rounds=5,
        )
        page = _make_mock_page()

        step = [0]

        async def evaluate_fn(*args, **kwargs):
            js = str(args[0]) if args else ""
            if len(args) > 1 or "maxItems" in js:
                step[0] += 1
                return [f"Item {step[0]} with enough text to pass the length check"]
            elif "strongPatterns" in js:
                return None  # no click target
            elif "scrollBy" in js:
                return True  # always can scroll
            return None

        page.evaluate = AsyncMock(side_effect=evaluate_fn)

        discovered, actions = await _run_discovery(page, cfg)
        scroll_actions = [a for a in actions if a == "scroll"]
        assert len(scroll_actions) <= cfg.discovery_max_scrolls

    async def test_deduplicates_items(self):
        """Same items across steps are not added twice."""
        cfg = FetchConfig(discovery_max_steps=4, discovery_stall_rounds=3)
        page = _make_mock_page()

        same_items = ["Repeated item with enough text to pass"]
        page.evaluate = AsyncMock(side_effect=[
            # Step 1: one item, click works
            same_items,
            "click:Load More",
            # Step 2: same item again, no click, no scroll
            same_items,
            None,
            False,
        ])

        discovered, actions = await _run_discovery(page, cfg)
        assert len(discovered) == 1  # deduped


# ---------------------------------------------------------------------------
# fetch_browser — test the import guard
# ---------------------------------------------------------------------------

class TestFetchBrowser:
    async def test_raises_on_missing_playwright(self):
        """fetch_browser raises RuntimeError when playwright import fails."""
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            with pytest.raises(RuntimeError, match="Playwright unavailable"):
                await fetch_browser("https://example.com", FetchConfig())
