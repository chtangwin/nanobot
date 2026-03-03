"""Generic adapter — wraps the core pipeline as the default fallback."""

from __future__ import annotations

from nanobot.webfetch.adapters.base import Adapter
from nanobot.webfetch.core.models import FetchConfig, FetchResult
from nanobot.webfetch.core.pipeline import robust_fetch as _robust_fetch


class GenericAdapter(Adapter):
    """Default adapter that delegates to the core HTTP → browser pipeline."""

    @property
    def name(self) -> str:
        return "generic"

    @property
    def domains(self) -> list[str]:
        return []  # matches nothing — used as fallback only

    async def fetch(
        self,
        url: str,
        cfg: FetchConfig,
        *,
        force_browser: bool = False,
        discovery_mode: bool = False,
    ) -> FetchResult:
        return await _robust_fetch(
            url, cfg, force_browser=force_browser, discovery_mode=discovery_mode,
        )
