"""Quality assessment and browser escalation logic."""

from __future__ import annotations

import re

from nanobot.webfetch.core.models import FetchConfig


def contains_spa_signals(html: str) -> bool:
    """Detect SPA/JS-heavy page signals in raw HTML."""
    probes = [
        r'id=["\']root["\']',
        r'id=["\']app["\']',
        r'__NEXT_DATA__',
        r'window\.__NUXT__',
        r'webpack',
        r'/chunk\.[a-z0-9]+\.js',
        r'enable javascript',
    ]
    h = html[:120_000].lower()
    return any(re.search(p, h, flags=re.I) for p in probes)


def is_low_quality_text(text: str) -> bool:
    """Heuristic check: is this text mostly navigation / boilerplate?"""
    t = text.strip()
    if not t:
        return True

    words = re.findall(r"\w+", t)
    sentence_marks = len(re.findall(r"[.!?。！？]", t))
    nav_hits = len(
        re.findall(
            r"\b(home|about|contact|privacy|terms|login|sign\s?in|menu|tools|api)\b",
            t.lower(),
        )
    )
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    short_lines = sum(1 for ln in lines if len(ln) <= 24)

    # Many words but zero sentence endings → likely nav list
    if len(words) >= 40 and sentence_marks == 0:
        return True
    # Heavy nav keywords with few sentences
    if nav_hits >= 5 and sentence_marks <= 2:
        return True
    # Mostly short lines (menu items, etc.)
    if len(lines) >= 15 and short_lines / max(1, len(lines)) >= 0.7:
        return True
    return False


def should_escalate_to_browser(
    status_code: int | None,
    html: str,
    text: str,
    cfg: FetchConfig,
) -> str | None:
    """Decide whether to escalate from HTTP to browser.

    Returns a reason string if escalation is needed, else None.
    Checks are ordered from cheapest to most expensive.
    """
    if status_code in {403, 429, 500, 502, 503, 504}:
        return f"http_status_{status_code}"
    if len(html.encode("utf-8", errors="ignore")) < cfg.min_html_bytes:
        return "html_too_small"
    if contains_spa_signals(html):
        return "spa_signal_detected"
    if len(text) < cfg.min_text_chars:
        return "text_too_short"
    if is_low_quality_text(text):
        return "low_content_quality"
    return None
