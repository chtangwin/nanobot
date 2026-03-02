"""Main fetch pipeline: HTTP fast path → quality check → browser fallback."""

from __future__ import annotations

import asyncio

import httpx

from nanobot.webfetch.core.browser import fetch_browser
from nanobot.webfetch.core.extractors import (
    clean_text,
    extract_main_text,
    merge_discovered_content,
)
from nanobot.webfetch.core.models import DEFAULT_HEADERS, FetchConfig, FetchResult
from nanobot.webfetch.core.quality import is_low_quality_text, should_escalate_to_browser


async def fetch_http(url: str, cfg: FetchConfig) -> tuple[int | None, str, str]:
    """HTTP fast path with retries.

    Returns (status_code, html, final_url).
    """
    timeout = httpx.Timeout(
        connect=cfg.http_connect_timeout_s,
        read=cfg.http_read_timeout_s,
        write=10.0,
        pool=10.0,
    )
    last_exc: Exception | None = None

    for attempt in range(cfg.http_retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, headers=DEFAULT_HEADERS
            ) as client:
                resp = await client.get(url)
                html = resp.text or ""
                return resp.status_code, html, str(resp.url)
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            if attempt >= cfg.http_retries:
                break
            await asyncio.sleep(0.5 * (2**attempt))

    raise RuntimeError(f"HTTP fetch failed after retries: {last_exc}")


def _build_browser_result(
    url: str,
    b_html: str,
    b_final_url: str,
    b_body_text: str,
    b_page_title: str | None,
    discovered: list[str],
    actions: list[str],
    cfg: FetchConfig,
    reason: str,
    status_code: int | None = None,
    http_title: str | None = None,
    discovery_mode: bool = False,
) -> FetchResult:
    """Shared logic to build a FetchResult from browser output."""
    b_text, b_title, b_extractor = extract_main_text(b_html, b_final_url)

    if len(b_text) < cfg.min_text_chars or is_low_quality_text(b_text):
        if len(b_body_text) > len(b_text):
            b_text = b_body_text
            b_extractor = "browser_body_text"

    if discovery_mode and discovered:
        b_text = merge_discovered_content(b_text, discovered)

    ok = len(b_text) >= max(80, cfg.min_text_chars // 2)
    return FetchResult(
        ok=ok,
        url=url,
        final_url=b_final_url,
        title=b_title or b_page_title or http_title,
        content=b_text,
        source_tier="browser",
        status_code=status_code,
        needs_browser_reason=reason,
        extractor=b_extractor,
        error=None if ok else "Browser fetch returned low-quality text",
        discovery_actions=actions,
        discovered_items=len(discovered),
    )


async def robust_fetch(
    url: str,
    cfg: FetchConfig | None = None,
    force_browser: bool = False,
    discovery_mode: bool = False,
) -> FetchResult:
    """Main entry point: fetch URL with progressive escalation.

    Pipeline:
      0. Check adapter registry — if a site-specific adapter matches, use it.
      1. If force_browser or discovery_mode → go straight to browser.
      2. Otherwise try HTTP fast path.
      3. Assess quality; if below threshold → escalate to browser.
    """
    if cfg is None:
        cfg = FetchConfig()

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # --- Adapter routing ---
    try:
        from nanobot.webfetch.adapters.registry import create_default_registry
        registry = create_default_registry()
        adapter = registry.resolve(url)
        if adapter.name != "generic":
            return await adapter.fetch(url, cfg, discovery_mode=discovery_mode)
    except Exception:
        pass  # adapter layer is optional; fall through to generic pipeline

    # --- Direct browser path ---
    if force_browser or discovery_mode:
        reason = "forced" if force_browser else "discovery_mode"
        try:
            b_html, b_final_url, b_body_text, b_page_title, discovered, actions = (
                await fetch_browser(url, cfg, discovery_mode=discovery_mode)
            )
            return _build_browser_result(
                url, b_html, b_final_url, b_body_text, b_page_title,
                discovered, actions, cfg, reason,
                discovery_mode=discovery_mode,
            )
        except Exception as exc:
            return FetchResult(
                ok=False, url=url, final_url=url, title=None, content="",
                source_tier="browser", status_code=None,
                needs_browser_reason=reason, extractor="none",
                error=f"Browser fetch failed: {exc}",
            )

    # --- HTTP fast path ---
    status_code: int | None = None
    final_url = url

    try:
        status_code, html, final_url = await fetch_http(url, cfg)
    except Exception as exc:
        return FetchResult(
            ok=False, url=url, final_url=final_url, title=None, content="",
            source_tier="http", status_code=status_code,
            needs_browser_reason="http_fetch_error", extractor="none",
            error=str(exc),
        )

    text, title, extractor = extract_main_text(html, final_url)
    reason = should_escalate_to_browser(status_code, html, text, cfg)

    # HTTP result is good enough
    if not reason:
        return FetchResult(
            ok=True, url=url, final_url=final_url, title=title, content=text,
            source_tier="http", status_code=status_code,
            needs_browser_reason=None, extractor=extractor,
        )

    # Non-HTML target (e.g. PDF) — don't try browser
    if final_url.lower().endswith(".pdf"):
        return FetchResult(
            ok=bool(text), url=url, final_url=final_url, title=title, content=text,
            source_tier="http", status_code=status_code,
            needs_browser_reason=reason, extractor=extractor,
            error="Detected non-HTML target",
        )

    # --- Browser fallback ---
    try:
        b_html, b_final_url, b_body_text, b_page_title, discovered, actions = (
            await fetch_browser(final_url, cfg, discovery_mode=False)
        )
        return _build_browser_result(
            url, b_html, b_final_url, b_body_text, b_page_title,
            discovered, actions, cfg, reason,
            status_code=status_code, http_title=title,
        )
    except Exception as exc:
        # Fall back to HTTP result even if low quality
        return FetchResult(
            ok=bool(text), url=url, final_url=final_url, title=title, content=text,
            source_tier="http", status_code=status_code,
            needs_browser_reason=reason, extractor=extractor,
            error=f"Browser fallback failed: {exc}",
        )
