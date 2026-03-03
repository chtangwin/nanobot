"""Site-specific adapters for hard-to-scrape sites."""

from nanobot.webfetch.adapters.registry import AdapterRegistry, create_default_registry

__all__ = ["AdapterRegistry", "create_default_registry"]
