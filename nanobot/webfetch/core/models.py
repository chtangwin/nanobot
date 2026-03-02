"""Data models for web fetch pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


@dataclass
class FetchConfig:
    """Configuration for the fetch pipeline."""

    # HTTP fast path
    http_connect_timeout_s: float = 3.0
    http_read_timeout_s: float = 7.0
    http_retries: int = 2

    # Browser fallback
    browser_timeout_s: float = 20.0
    browser_post_wait_ms: int = 1200

    # Quality thresholds
    min_html_bytes: int = 8 * 1024
    min_text_chars: int = 300

    # Discovery limits
    discovery_max_steps: int = 18
    discovery_max_clicks: int = 15
    discovery_max_scrolls: int = 10
    discovery_stall_rounds: int = 3
    discovery_wait_ms: int = 1000
    discovery_max_items: int = 250


@dataclass
class FetchResult:
    """Unified result from any fetch path."""

    ok: bool
    url: str
    final_url: str
    title: str | None
    content: str
    source_tier: str  # "http" | "browser" | "adapter:<name>"
    status_code: int | None
    needs_browser_reason: str | None
    extractor: str
    error: str | None = None
    discovery_actions: list[str] = field(default_factory=list)
    discovered_items: int = 0

    def to_dict(self) -> dict:
        """Serialize to dict (for JSON output)."""
        return asdict(self)
