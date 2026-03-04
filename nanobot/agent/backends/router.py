"""Backend router that resolves local vs remote execution backends."""

from __future__ import annotations

from nanobot.agent.backends.base import ExecutionBackend
from nanobot.agent.backends.local import LocalExecutionBackend
from nanobot.agent.backends.remote import RemoteExecutionBackend
from nanobot.agent.backends.localhost import is_localhost
from nanobot.remote.manager import HostManager


class ExecutionBackendRouter:
    def __init__(self, local_backend: LocalExecutionBackend, host_manager: HostManager | None = None):
        self.local_backend = local_backend
        self.host_manager = host_manager

    async def resolve(self, host: str | None = None) -> ExecutionBackend:
        if not host:
            return self.local_backend
        if not self.host_manager:
            raise RuntimeError("Host manager not available")

        # Check if the host refers to the local machine
        host_config = self.host_manager.config.get_host(host)
        if host_config and is_localhost(host_config.ssh_host):
            # Host is actually local - use local backend
            return self.local_backend

        # Host is remote - use remote backend
        remote_host = await self.host_manager.get_or_connect(host)
        return RemoteExecutionBackend(host, remote_host)
