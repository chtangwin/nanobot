"""Web fetch subsystem: HTTP-first fetcher with browser fallback and discovery."""

from nanobot.webfetch.core.models import FetchConfig, FetchResult
from nanobot.webfetch.core.pipeline import robust_fetch

__all__ = ["FetchConfig", "FetchResult", "robust_fetch"]
