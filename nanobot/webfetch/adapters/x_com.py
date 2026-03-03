"""X/Twitter adapter — scrapes profiles and posts using Playwright.

Ported from the x-scraper skill. Handles:
- Profile page scraping with scrolling and DOM virtualization
- Persistent login state via x_auth.json
- Deduplication by tweet URL (fallback: date+text)
- Structured output: text, date, engagement, media
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from nanobot.webfetch.adapters.base import Adapter
from nanobot.webfetch.core.extractors import clean_text
from nanobot.webfetch.core.models import DEFAULT_HEADERS, FetchConfig, FetchResult

# Auth file location (user space only)
# Users must run: uv run python -m nanobot.webfetch.adapters.x_login
_AUTH_PATH = Path.home() / ".nanobot" / "auth" / "x_auth.json"

# Error message when auth is missing/invalid
_AUTH_MISSING_MSG = """
No X auth found or auth has expired.

To generate a working auth file:
  1. Run: uv run python -m nanobot.webfetch.adapters.x_login
  2. Log into X in the browser window when it opens
  3. Auth will be saved to: ~/.nanobot/auth/x_auth.json

Or manually export cookies from Brave:
  1. Open Brave DevTools at x.com (logged in)
  2. Application > Cookies > https://x.com
  3. Copy cookies and create the auth file at ~/.nanobot/auth/x_auth.json
"""

# JS: extract tweets from current viewport
_JS_EXTRACT_TWEETS = """() => {
    const results = [];
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    articles.forEach(article => {
        const textEl = article.querySelector('[data-testid="tweetText"]');
        const text = textEl ? textEl.innerText.trim() : '';

        const photoEls = article.querySelectorAll('[data-testid="tweetPhoto"] img');
        const photos = Array.from(photoEls)
            .map((img) => img.getAttribute('src') || '')
            .filter(Boolean);

        const videoEls = article.querySelectorAll('video');
        const videos = Array.from(videoEls)
            .map((v) => v.currentSrc || v.getAttribute('src') || '')
            .filter(Boolean);

        const hasMedia = photos.length > 0 || videos.length > 0;
        if (!textEl && !hasMedia) return;
        if (textEl && text.length < 3 && !hasMedia) return;

        const timeEl = article.querySelector('time');
        const date = timeEl ? timeEl.getAttribute('datetime') || timeEl.innerText : '';

        const linkEl = timeEl ? timeEl.closest('a') : null;
        const tweetUrl = linkEl ? linkEl.href : '';

        const getLabelCount = (label) => {
            const el = article.querySelector(`[data-testid="${label}"]`);
            if (!el) return '0';
            const span = el.querySelector('span[data-testid]') || el.querySelector('span');
            return span ? span.innerText.trim() || '0' : '0';
        };

        results.push({
            text: text,
            date: date,
            url: tweetUrl,
            likes: getLabelCount('like'),
            retweets: getLabelCount('retweet'),
            replies: getLabelCount('reply'),
            has_media: hasMedia,
            media: { photos: photos, videos: videos },
        });
    });
    return results;
}"""


def _find_auth_file() -> Path | None:
    """Return auth file path if it exists, else None."""
    return _AUTH_PATH if _AUTH_PATH.exists() else None


def _parse_x_url(url: str) -> tuple[str | None, str | None]:
    """Parse an X URL into (username, tweet_id).

    Returns:
        (username, None) for profile pages
        (username, tweet_id) for individual tweets
    """
    # Match: x.com/username or x.com/username/status/123
    m = re.match(
        r"https?://(?:www\.)?(?:x\.com|twitter\.com)/(@?\w+)(?:/status/(\d+))?",
        url,
    )
    if m:
        return m.group(1).lstrip("@"), m.group(2)
    return None, None


def _format_posts_as_text(posts: list[dict], username: str) -> str:
    """Format structured posts into readable text for FetchResult.content."""
    if not posts:
        return f"No posts found for @{username}."

    lines = [f"Posts from @{username} ({len(posts)} posts)\n"]
    for i, p in enumerate(posts, 1):
        lines.append(f"--- Post {i} ---")
        if p.get("date"):
            lines.append(f"Date: {p['date']}")
        if p.get("text"):
            lines.append(p["text"])
        engagement = []
        for key in ("likes", "retweets", "replies"):
            v = p.get(key, "0")
            if v and v != "0":
                engagement.append(f"{key}:{v}")
        if engagement:
            lines.append(f"[{', '.join(engagement)}]")
        if p.get("url"):
            lines.append(p["url"])
        if p.get("has_media") and p.get("media"):
            media = p["media"]
            if media.get("photos"):
                lines.append(f"Photos: {', '.join(media['photos'][:3])}")
            if media.get("videos"):
                lines.append(f"Videos: {', '.join(media['videos'][:2])}")
        lines.append("")
    return clean_text("\n".join(lines))


class XComAdapter(Adapter):
    """Adapter for X/Twitter using Playwright with persistent auth."""

    @property
    def name(self) -> str:
        return "x_com"

    @property
    def domains(self) -> list[str]:
        return ["x.com", "twitter.com"]

    async def fetch(
        self,
        url: str,
        cfg: FetchConfig,
        *,
        discovery_mode: bool = False,
    ) -> FetchResult:
        username, tweet_id = _parse_x_url(url)
        if not username:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier=f"adapter:{self.name}", status_code=None,
                needs_browser_reason=None, extractor="none",
                error=f"Could not parse X username from URL: {url}",
            )

        # For individual tweets, fall back to generic browser fetch for now
        if tweet_id:
            return await self._fetch_single_tweet(url, cfg)

        # Profile scrape
        return await self._scrape_profile(url, username, cfg, discovery_mode)

    async def _scrape_profile(
        self,
        url: str,
        username: str,
        cfg: FetchConfig,
        discovery_mode: bool,
    ) -> FetchResult:
        """Scrape posts from an X profile."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier=f"adapter:{self.name}", status_code=None,
                needs_browser_reason=None, extractor="none",
                error=f"Playwright not installed: {exc}",
            )

        auth_file = _find_auth_file()
        max_no_new = cfg.discovery_stall_rounds * 3  # more patient for X
        max_scrolls = cfg.discovery_max_scrolls * 2 if discovery_mode else cfg.discovery_max_scrolls

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context_kwargs = dict(
                    viewport={"width": 1280, "height": 900},
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                )
                if auth_file:
                    context_kwargs["storage_state"] = str(auth_file)

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                await page.goto(url, wait_until="domcontentloaded",
                                timeout=int(cfg.browser_timeout_s * 1000))
                await page.wait_for_timeout(3000)

                # Check page title for errors
                title = await page.title()
                page_url = page.url

                collected: dict[str, dict] = {}
                actions: list[str] = []
                no_new_count = 0
                scroll_count = 0

                while scroll_count < max_scrolls:
                    tweets = await page.evaluate(_JS_EXTRACT_TWEETS)

                    prev_count = len(collected)
                    for tweet in tweets:
                        key = tweet.get("url") or f"{tweet.get('date', '')}|{tweet.get('text', '')[:200]}"
                        if key and key not in collected:
                            collected[key] = tweet

                    new_count = len(collected) - prev_count
                    scroll_count += 1

                    if new_count > 0:
                        no_new_count = 0
                        actions.append(f"scroll:+{new_count}")
                    else:
                        no_new_count += 1
                        if no_new_count >= max_no_new:
                            break

                    # Scroll
                    await page.mouse.wheel(0, 1200)
                    await page.wait_for_timeout(800)
                    if scroll_count % 10 == 0:
                        await page.wait_for_timeout(1500)

                await context.close()
                await browser.close()

            posts = list(collected.values())
            content = _format_posts_as_text(posts, username)
            ok = len(posts) > 0

            return FetchResult(
                ok=ok,
                url=url,
                final_url=page_url,
                title=f"@{username} on X ({len(posts)} posts)",
                content=content,
                source_tier=f"adapter:{self.name}",
                status_code=None,
                needs_browser_reason="adapter_x_com" if not auth_file else None,
                extractor="x_com_scraper",
                error=None if ok else f"No posts found for @{username}.{_AUTH_MISSING_MSG if not auth_file else ''}",
                discovery_actions=actions,
                discovered_items=len(posts),
            )

        except Exception as exc:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier=f"adapter:{self.name}", status_code=None,
                needs_browser_reason=None, extractor="none",
                error=f"X adapter error: {exc}",
            )

    async def _fetch_single_tweet(self, url: str, cfg: FetchConfig) -> FetchResult:
        """Fetch a single tweet — use browser with auth."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier=f"adapter:{self.name}", status_code=None,
                needs_browser_reason=None, extractor="none",
                error=f"Playwright not installed: {exc}",
            )

        auth_file = _find_auth_file()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context_kwargs = dict(
                    viewport={"width": 1280, "height": 900},
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                )
                if auth_file:
                    context_kwargs["storage_state"] = str(auth_file)

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                await page.goto(url, wait_until="domcontentloaded",
                                timeout=int(cfg.browser_timeout_s * 1000))
                await page.wait_for_timeout(3000)

                tweets = await page.evaluate(_JS_EXTRACT_TWEETS)
                body_text = clean_text(await page.locator("body").inner_text())
                title = await page.title()
                final_url = page.url

                await context.close()
                await browser.close()

            if tweets:
                content = _format_posts_as_text(tweets[:1], "tweet")
            else:
                content = body_text

            return FetchResult(
                ok=bool(content),
                url=url,
                final_url=final_url,
                title=title,
                content=content,
                source_tier=f"adapter:{self.name}",
                status_code=None,
                needs_browser_reason=None,
                extractor="x_com_scraper" if tweets else "browser_body_text",
                discovery_actions=[],
                discovered_items=len(tweets),
            )

        except Exception as exc:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier=f"adapter:{self.name}", status_code=None,
                needs_browser_reason=None, extractor="none",
                error=f"X adapter error: {exc}",
            )
