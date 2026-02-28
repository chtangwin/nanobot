"""Node manager for handling multiple remote nodes."""

import asyncio
import logging
from typing import Dict, Optional

from nanobot.nodes.config import NodeConfig, NodesConfig
from nanobot.nodes.connection import RemoteNode

logger = logging.getLogger(__name__)


class NodeManager:
    """
    Manager for multiple remote nodes.

    Handles adding, removing, and executing commands on remote nodes.
    """

    def __init__(self, config: Optional[NodesConfig] = None):
        self.config = config or NodesConfig()
        self._connections: Dict[str, RemoteNode] = {}
        self._lock = asyncio.Lock()

    async def add_node(self, name: str, ssh_host: str, **kwargs) -> NodeConfig:
        """
        Add a new node configuration.

        Args:
            name: Node name/identifier.
            ssh_host: SSH host in user@host format.
            **kwargs: Additional NodeConfig parameters.

        Returns:
            Created NodeConfig.
        """
        config = NodeConfig(name=name, ssh_host=ssh_host, **kwargs)
        self.config.add_node(config)
        self.config.save()
        return config

    async def remove_node(self, name: str) -> bool:
        """
        Remove a node configuration and disconnect if connected.

        Args:
            name: Node name to remove.

        Returns:
            True if removed, False if not found.
        """
        # Disconnect if connected
        if name in self._connections:
            await self.disconnect(name)

        self.config.remove_node(name)
        self.config.save()
        return True

    async def connect(self, name: str) -> RemoteNode:
        """
        Connect to a remote node.

        Args:
            name: Node name to connect to.

        Returns:
            Connected RemoteNode instance.

        Raises:
            KeyError: If node configuration not found.
            ConnectionError: If connection fails.
        """
        config = self.config.get_node(name)
        if not config:
            raise KeyError(f"Node not found: {name}")

        # Disconnect existing connection if any
        if name in self._connections:
            await self.disconnect(name)

        async with self._lock:
            node = RemoteNode(config)
            await node.setup()
            self._connections[name] = node

        return node

    async def disconnect(self, name: str) -> bool:
        """
        Disconnect from a remote node.

        Args:
            name: Node name to disconnect.

        Returns:
            True if disconnected, False if not connected.
        """
        if name not in self._connections:
            return False

        async with self._lock:
            node = self._connections.pop(name)
            await node.teardown()

        return True

    async def disconnect_all(self):
        """Disconnect from all nodes."""
        names = list(self._connections.keys())
        for name in names:
            await self.disconnect(name)

    def get_node(self, name: str) -> Optional[RemoteNode]:
        """
        Get a connected node instance.

        Args:
            name: Node name.

        Returns:
            RemoteNode instance if connected, None otherwise.
        """
        return self._connections.get(name)

    def list_nodes(self) -> list[dict]:
        """
        List all configured nodes with their status.

        Returns:
            List of node info dictionaries.
        """
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

    async def execute(
        self,
        command: str,
        host: str,
        timeout: float = 30.0,
    ) -> dict:
        """
        Execute a command on a remote host.

        Args:
            command: Command to execute.
            host: Host name to execute on.
            timeout: Command timeout in seconds.

        Returns:
            Result dictionary with 'success', 'output', and 'error' keys.

        Raises:
            KeyError: If host not found.
            ConnectionError: If connection fails.
        """
        remote_node = self._connections.get(host)

        if not remote_node or not remote_node.is_connected:
            # Auto-connect if not connected
            remote_node = await self.connect(host)

        return await remote_node.execute(command, timeout=timeout)

    async def execute_on_all(
        self,
        command: str,
        timeout: float = 30.0,
    ) -> dict[str, dict]:
        """
        Execute a command on all connected nodes.

        Args:
            command: Command to execute.
            timeout: Command timeout in seconds.

        Returns:
            Dictionary mapping node names to results.
        """
        results = {}

        tasks = []
        names = []

        for name, node in self._connections.items():
            if node.is_connected:
                tasks.append(node.execute(command, timeout=timeout))
                names.append(name)

        if tasks:
            outputs = await asyncio.gather(*tasks, return_exceptions=True)

            for name, output in zip(names, outputs):
                if isinstance(output, Exception):
                    results[name] = {
                        "success": False,
                        "output": None,
                        "error": str(output),
                    }
                else:
                    results[name] = output

        return results

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect_all()
