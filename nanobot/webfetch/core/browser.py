"""Playwright browser fetch with optional discovery (click/scroll expansion)."""

from __future__ import annotations

from nanobot.webfetch.core.extractors import clean_text
from nanobot.webfetch.core.models import DEFAULT_HEADERS, FetchConfig


# ---------------------------------------------------------------------------
# Discovery JS helpers (injected into page context)
# ---------------------------------------------------------------------------

_JS_COLLECT_ITEMS = """
(maxItems) => {
  const out = [];
  const seen = new Set();
  const add = (raw) => {
    if (!raw) return;
    const t = raw.replace(/\\s+/g, ' ').trim();
    if (!t) return;
    if (t.length < 20) return;
    if (t.length > 500) return;
    if (!seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  };

  document.querySelectorAll('table tr').forEach((tr) => {
    const cells = [...tr.querySelectorAll('th,td')].map(el => el.innerText.trim()).filter(Boolean);
    if (cells.length > 1) add(cells.join(' | '));
  });

  document.querySelectorAll('main li, [role="listitem"], article, section li, .card, [class*="card"], [class*="item"]').forEach((el) => {
    const text = el.innerText || '';
    add(text);
  });

  return out.slice(0, maxItems);
}
"""

_JS_CLICK_CONTROL = """
() => {
  const strongPatterns = [
    /^(see|show|load)\\s+more\\b/i,
    /^view\\s+more\\b/i,
    /more\\s+results?/i,
    /^next(\\s+page)?\\b/i,
    /^older\\b/i,
    /^expand\\b/i,
    /^(更多|下一页|加载更多|展开|继续)$/
  ];

  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const isDisabled = (el) => {
    return !!(el.disabled || el.getAttribute('aria-disabled') === 'true');
  };

  const candidates = [
    ...document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'),
    ...document.querySelectorAll('a[rel="next"], button[aria-label*="next" i], a[aria-label*="next" i]')
  ];

  for (const el of candidates) {
    if (!isVisible(el) || isDisabled(el)) continue;

    const text = (el.innerText || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
    if (!text) continue;
    if (text.length > 40 && !/see more|load more|show more|更多|加载更多/i.test(text)) continue;
    if (/^#?\\d+\\b/.test(text)) continue;

    const matched = strongPatterns.some((p) => p.test(text));
    if (!matched) continue;

    const isNextLike = /^next(\\s+page)?$/i.test(text) || text === '下一页';
    if (!isNextLike && el.dataset.nbClicked === '1') continue;

    if (!isNextLike) {
      el.dataset.nbClicked = '1';
    }
    el.click();
    return `click:${text.slice(0, 120)}`;
  }

  return null;
}
"""

_JS_SCROLL = """
() => {
  const before = window.scrollY;
  window.scrollBy(0, Math.floor(window.innerHeight * 0.9));
  const after = window.scrollY;
  return after > before;
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_browser(
    url: str,
    cfg: FetchConfig,
    discovery_mode: bool = False,
) -> tuple[str, str, str, str | None, list[str], list[str]]:
    """Fetch URL with Playwright.

    Returns:
        (html, final_url, body_text, page_title, discovered_items, actions)
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright unavailable. Install with: uv add playwright && uv run playwright install chromium"
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"], locale="en-US"
        )
        page = await context.new_page()

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(cfg.browser_timeout_s * 1000),
        )
        if cfg.browser_post_wait_ms > 0:
            await page.wait_for_timeout(cfg.browser_post_wait_ms)

        actions: list[str] = []
        discovered: list[str] = []

        if discovery_mode:
            discovered, actions = await _run_discovery(page, cfg)

        html = await page.content()
        body_text = clean_text(await page.locator("body").inner_text())
        page_title = await page.title()
        final_url = page.url

        await context.close()
        await browser.close()

        return html, final_url, body_text, (page_title or None), discovered, actions


async def _run_discovery(page, cfg: FetchConfig) -> tuple[list[str], list[str]]:
    """Execute generic discovery loop: click controls, scroll, collect items."""
    seen_items: set[str] = set()
    discovered: list[str] = []
    actions: list[str] = []

    stall = 0
    clicks = 0
    scrolls = 0
    best_len = 0

    for _ in range(cfg.discovery_max_steps):
        body_text = clean_text(await page.locator("body").inner_text())
        current_len = len(body_text)

        # Collect items
        items: list[str] = await page.evaluate(_JS_COLLECT_ITEMS, cfg.discovery_max_items)
        new_count = 0
        for it in items:
            if it not in seen_items:
                seen_items.add(it)
                discovered.append(it)
                new_count += 1

        # Progress check
        progressed = new_count > 0 or current_len > best_len + 200
        best_len = max(best_len, current_len)
        stall = 0 if progressed else stall + 1
        if stall >= cfg.discovery_stall_rounds:
            break

        # Try click first, then scroll
        acted = False
        if clicks < cfg.discovery_max_clicks:
            action: str | None = await page.evaluate(_JS_CLICK_CONTROL)
            if action:
                actions.append(action)
                clicks += 1
                acted = True
                await page.wait_for_timeout(cfg.discovery_wait_ms)

        if not acted and scrolls < cfg.discovery_max_scrolls:
            moved: bool = await page.evaluate(_JS_SCROLL)
            if moved:
                actions.append("scroll")
                scrolls += 1
                acted = True
                await page.wait_for_timeout(cfg.discovery_wait_ms)

        if not acted:
            break

    return discovered, actions
