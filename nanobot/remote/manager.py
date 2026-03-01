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

        # Persist session info for resume after restart
        self._save_session(name, host)
        return host

    async def get_or_connect(self, name: str) -> RemoteHost:
        """Get existing host object or create initial connection.

        If a host object already exists (even temporarily disconnected), return it
        so lower layers can attempt transport-only auto-recovery without forcing a
        new session/deploy.  If no in-memory connection exists but there is a
        persisted active_session, try to resume it before doing a full connect.
        """
        host = self._connections.get(name)
        if host:
            return host

        # Try to resume a persisted session (e.g. after nanobot restart)
        resumed = await self._try_resume(name)
        if resumed:
            return resumed

        return await self.connect(name)

    async def disconnect(self, name: str) -> bool:
        if name not in self._connections:
            return False
        async with self._lock:
            host = self._connections.pop(name)
            await host.teardown()
        self._clear_session(name)
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

    def _save_session(self, name: str, host: RemoteHost) -> None:
        """Persist session info to hosts.json for resume after restart."""
        config = self.config.get_host(name)
        if config:
            config.active_session = {
                "session_id": host.session_id,
                "local_port": config.local_port,
                "remote_port": config.remote_port,
                "auth_token": config.auth_token,
            }
            self.config.save()
            logger.info(f"Saved session info for '{name}' (session: {host.session_id})")

    def _clear_session(self, name: str) -> None:
        """Clear persisted session info."""
        config = self.config.get_host(name)
        if config and config.active_session:
            config.active_session = None
            self.config.save()
            logger.info(f"Cleared session info for '{name}'")

    async def _try_resume(self, name: str) -> Optional[RemoteHost]:
        """Try to resume a persisted session without full redeploy."""
        config = self.config.get_host(name)
        if not config or not config.active_session:
            return None

        session_id = config.active_session.get("session_id")
        if not session_id:
            self._clear_session(name)
            return None

        # Restore dynamic fields from persisted session
        if config.active_session.get("local_port"):
            config.local_port = config.active_session["local_port"]
        if config.active_session.get("remote_port"):
            config.remote_port = config.active_session["remote_port"]
        if config.active_session.get("auth_token"):
            config.auth_token = config.active_session["auth_token"]

        logger.info(f"Attempting to resume session '{session_id}' on '{name}'...")

        try:
            async with self._lock:
                host = RemoteHost(config)
                host.session_id = session_id
                # Use transport-only recovery: SSH tunnel + WebSocket + auth
                # No redeploy — remote_server.py should still be running
                recovered = await host._recover_transport()
                if recovered:
                    self._connections[name] = host
                    logger.info(f"Resumed session '{session_id}' on '{name}'")
                    return host
                else:
                    logger.warning(f"Resume failed for '{name}', will do full connect")
                    self._clear_session(name)
                    return None
        except Exception as e:
            logger.warning(f"Resume failed for '{name}': {e}")
            self._clear_session(name)
            return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect_all()
