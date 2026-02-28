"""Backend router that resolves local vs remote execution backends."""

from __future__ import annotations

from nanobot.agent.backends.base import ExecutionBackend
from nanobot.agent.backends.local import LocalExecutionBackend
from nanobot.agent.backends.remote import RemoteExecutionBackend
from nanobot.nodes.manager import NodeManager


class ExecutionBackendRouter:
    def __init__(self, local_backend: LocalExecutionBackend, node_manager: NodeManager | None = None):
        self.local_backend = local_backend
        self.node_manager = node_manager

    async def resolve(self, host: str | None = None) -> ExecutionBackend:
        if not host:
            return self.local_backend
        if not self.node_manager:
            raise RuntimeError("Host manager not available")

        remote_node = await self.node_manager.get_or_connect(host)
        return RemoteExecutionBackend(host, remote_node)
