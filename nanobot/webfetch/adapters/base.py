"""Abstract base class for site-specific adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nanobot.webfetch.core.models import FetchConfig, FetchResult


class Adapter(ABC):
    """Site-specific fetch adapter.

    Subclasses handle domains that need special logic beyond the generic
    HTTP → browser → discovery pipeline.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'x_com'. Used in source_tier='adapter:<name>'."""

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        """Domains this adapter handles, e.g. ['x.com', 'twitter.com']."""

    @abstractmethod
    async def fetch(
        self,
        url: str,
        cfg: FetchConfig,
        *,
        discovery_mode: bool = False,
    ) -> FetchResult:
        """Fetch the URL using site-specific logic.

        Must return a FetchResult with source_tier='adapter:<name>'.
        """

    def matches(self, domain: str) -> bool:
        """Check if this adapter handles the given domain."""
        domain = domain.lower().lstrip("www.")
        return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in self.domains)
