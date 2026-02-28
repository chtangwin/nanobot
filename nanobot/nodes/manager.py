"""Node manager for handling multiple remote nodes."""

import asyncio
import logging
from typing import Dict, Optional

from nanobot.nodes.config import NodeConfig, NodesConfig
from nanobot.nodes.connection import RemoteNode

logger = logging.getLogger(__name__)


class NodeManager:
    """Lifecycle manager for remote node connections."""

    def __init__(self, config: Optional[NodesConfig] = None):
        self.config = config or NodesConfig()
        self._connections: Dict[str, RemoteNode] = {}
        self._lock = asyncio.Lock()

    async def add_node(self, name: str, ssh_host: str, **kwargs) -> NodeConfig:
        config = NodeConfig(name=name, ssh_host=ssh_host, **kwargs)
        self.config.add_node(config)
        self.config.save()
        return config

    async def remove_node(self, name: str) -> bool:
        if name in self._connections:
            await self.disconnect(name)

        self.config.remove_node(name)
        self.config.save()
        return True

    async def connect(self, name: str) -> RemoteNode:
        config = self.config.get_node(name)
        if not config:
            raise KeyError(f"Host not found: {name}")

        if name in self._connections:
            await self.disconnect(name)

        async with self._lock:
            node = RemoteNode(config)
            await node.setup()
            self._connections[name] = node

        return node

    async def get_or_connect(self, name: str) -> RemoteNode:
        node = self._connections.get(name)
        if node and node.is_connected:
            return node
        return await self.connect(name)

    async def disconnect(self, name: str) -> bool:
        if name not in self._connections:
            return False

        async with self._lock:
            node = self._connections.pop(name)
            await node.teardown()

        return True

    async def disconnect_all(self):
        names = list(self._connections.keys())
        for name in names:
            await self.disconnect(name)

    def get_node(self, name: str) -> Optional[RemoteNode]:
        return self._connections.get(name)

    def list_nodes(self) -> list[dict]:
        nodes = []
        for config in self.config.list_nodes():
            node = self._connections.get(config.name)
            nodes.append({
                "name": config.name,
                "ssh_host": config.ssh_host,
                "connected": node.is_connected if node else False,
                "workspace": config.workspace,
            })
        return nodes

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect_all()
