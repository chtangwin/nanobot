"""Adapter registry — resolves URL to the best adapter."""

from __future__ import annotations

from urllib.parse import urlparse

from nanobot.webfetch.adapters.base import Adapter
from nanobot.webfetch.adapters.generic import GenericAdapter


class AdapterRegistry:
    """Maps domains to adapters. Falls back to GenericAdapter."""

    def __init__(self):
        self._adapters: list[Adapter] = []
        self._generic = GenericAdapter()

    def register(self, adapter: Adapter) -> None:
        """Register a site-specific adapter."""
        self._adapters.append(adapter)

    def resolve(self, url: str) -> Adapter:
        """Find the best adapter for a URL. Returns GenericAdapter if none match."""
        try:
            domain = urlparse(url).netloc.lower().lstrip("www.")
        except Exception:
            return self._generic

        for adapter in self._adapters:
            if adapter.matches(domain):
                return adapter

        return self._generic

    @property
    def generic(self) -> GenericAdapter:
        return self._generic

    @property
    def registered(self) -> list[Adapter]:
        return list(self._adapters)


# ---------------------------------------------------------------------------
# Default singleton registry with all built-in adapters
# ---------------------------------------------------------------------------

def create_default_registry() -> AdapterRegistry:
    """Create registry with all built-in adapters."""
    registry = AdapterRegistry()

    # Import here to avoid circular imports and to make x_com optional
    try:
        from nanobot.webfetch.adapters.x_com import XComAdapter
        registry.register(XComAdapter())
    except ImportError:
        pass

    return registry
