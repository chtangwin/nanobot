"""Host manager for handling multiple remote hosts."""

import asyncio
import logging
from typing import Dict, Optional

from nanobot.remote.config import HostConfig, HostsConfig
from nanobot.remote.connection import RemoteHost

logger = logging.getLogger(__name__)


class HostManager:
    """Lifecycle manager for remote host connections."""

    def __init__(self, config: Optional[HostsConfig] = None):
        self.config = config or HostsConfig()
        self._connections: Dict[str, RemoteHost] = {}
        self._lock = asyncio.Lock()

    async def add_host(self, name: str, ssh_host: str, **kwargs) -> HostConfig:
        config = HostConfig(name=name, ssh_host=ssh_host, **kwargs)
        self.config.add_host(config)
        self.config.save()
        return config

    async def remove_host(self, name: str) -> bool:
        if name in self._connections:
            await self.disconnect(name)
        self.config.remove_host(name)
        self.config.save()
        return True

    async def connect(self, name: str) -> RemoteHost:
        config = self.config.get_host(name)
        if not config:
            raise KeyError(f"Host not found: {name}")

        if name in self._connections:
            await self.disconnect(name)

        async with self._lock:
            host = RemoteHost(config)
            await host.setup()
            self._connections[name] = host

        return host

    async def get_or_connect(self, name: str) -> RemoteHost:
        """Get existing host object or create initial connection.

        If a host object already exists (even temporarily disconnected), return it
        so lower layers can attempt transport-only auto-recovery without forcing a
        new session/deploy.
        """
        host = self._connections.get(name)
        if host:
            return host
        return await self.connect(name)

    async def disconnect(self, name: str) -> bool:
        if name not in self._connections:
            return False
        async with self._lock:
            host = self._connections.pop(name)
            await host.teardown()
        return True

    async def disconnect_all(self):
        for name in list(self._connections.keys()):
            await self.disconnect(name)

    def get_host(self, name: str) -> Optional[RemoteHost]:
        return self._connections.get(name)

    def list_hosts(self) -> list[dict]:
        hosts = []
        for config in self.config.list_hosts():
            host = self._connections.get(config.name)
            hosts.append({
                "name": config.name,
                "ssh_host": config.ssh_host,
                "connected": host.is_connected if host else False,
                "workspace": config.workspace,
            })
        return hosts

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect_all()
