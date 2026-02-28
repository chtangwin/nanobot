"""Host management tools for managing and executing commands on remote hosts."""

import logging
from typing import Any, Optional

from nanobot.agent.tools.base import Tool
from nanobot.nodes.manager import NodeManager
from nanobot.nodes.config import NodesConfig

logger = logging.getLogger(__name__)


class NodesTool(Tool):
    """
    Tool for managing remote hosts and executing commands on them.

    Supports:
    - Adding/removing hosts
    - Connecting/disconnecting from hosts
    - Listing hosts and their status
    - Executing commands on remote hosts
    """

    def __init__(self, config_path: Optional[str] = None, node_manager: Optional[NodeManager] = None):
        """
        Initialize the hosts tool.

        Args:
            config_path: Optional path to hosts configuration file.
                        If not specified, uses default path.
            node_manager: Optional shared NodeManager instance.
                         If provided, uses this instead of creating a new one.
        """
        if node_manager:
            self.manager = node_manager
        elif config_path:
            config = NodesConfig.load(config_path)
            self.manager = NodeManager(config)
        else:
            config = NodesConfig.load(NodesConfig.get_default_config_path())
            self.manager = NodeManager(config)

    @property
    def name(self) -> str:
        return "hosts"

    @property
    def description(self) -> str:
        return """Manage and execute commands on remote hosts.

Actions:
- list: List all configured hosts and their status
- add: Add a new host (requires: name, ssh_host)
- remove: Remove a host (requires: name)
- connect: Connect to a host (requires: name)
- disconnect: Disconnect from a host (requires: name)
- status: Get status of a host (requires: name)
- exec: Execute a command on a host (requires: name, command)

Examples:
- hosts action="list"
- hosts action="add" name="build-server" ssh_host="user@192.168.1.100"
- hosts action="exec" name="build-server" command="ls -la"
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "connect", "disconnect", "status", "exec"],
                    "description": "Action to perform"
                },
                "name": {
                    "type": "string",
                    "description": "Host name (for add/remove/connect/disconnect/status/exec)"
                },
                "ssh_host": {
                    "type": "string",
                    "description": "SSH host in user@host format (for add)"
                },
                "ssh_port": {
                    "type": "integer",
                    "description": "SSH port (default: 22, for add)"
                },
                "ssh_key_path": {
                    "type": "string",
                    "description": "Path to SSH private key (for add)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Default workspace directory on remote (for add)"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute (for exec)"
                },
                "timeout": {
                    "type": "number",
                    "description": "Command timeout in seconds (default: 30, for exec)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the hosts tool.

        Args:
            **kwargs: Tool parameters.

        Returns:
            Result of the action.
        """
        import asyncio

        action = kwargs.get("action")

        try:
            if action == "list":
                return await self._list_nodes()

            elif action == "add":
                return await self._add_node(
                    name=kwargs.get("name"),
                    ssh_host=kwargs.get("ssh_host"),
                    ssh_port=kwargs.get("ssh_port"),
                    ssh_key_path=kwargs.get("ssh_key_path"),
                    workspace=kwargs.get("workspace"),
                )

            elif action == "remove":
                return await self._remove_node(name=kwargs.get("name"))

            elif action == "connect":
                return await self._connect_node(name=kwargs.get("name"))

            elif action == "disconnect":
                return await self._disconnect_node(name=kwargs.get("name"))

            elif action == "status":
                return await self._node_status(name=kwargs.get("name"))

            elif action == "exec":
                return await self._exec_command(
                    name=kwargs.get("name"),
                    command=kwargs.get("command"),
                    timeout=kwargs.get("timeout", 30.0),
                )

            else:
                return f"Error: Unknown action '{action}'"

        except Exception as e:
            logger.exception(f"Error executing hosts tool action: {action}")
            return f"Error: {str(e)}"

    async def _list_nodes(self) -> str:
        """List all configured hosts."""
        nodes = self.manager.list_nodes()

        if not nodes:
            return "No hosts configured. Use 'hosts action=\"add\"' to add a host."

        lines = ["Configured hosts:"]
        for node in nodes:
            status = "✓ connected" if node["connected"] else "○ disconnected"
            lines.append(f"\n  {node['name']}: {node['ssh_host']} [{status}]")
            if node.get("workspace"):
                lines.append(f"    workspace: {node['workspace']}")

        return "\n".join(lines)

    async def _add_node(
        self,
        name: str,
        ssh_host: str,
        ssh_port: Optional[int] = None,
        ssh_key_path: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> str:
        """Add a new host."""
        if not name:
            return "Error: 'name' parameter is required for add action"

        if not ssh_host:
            return "Error: 'ssh_host' parameter is required for add action"

        kwargs = {}
        if ssh_port is not None:
            kwargs["ssh_port"] = ssh_port
        if ssh_key_path:
            kwargs["ssh_key_path"] = ssh_key_path
        if workspace:
            kwargs["workspace"] = workspace

        config = await self.manager.add_node(name, ssh_host, **kwargs)

        return f"✓ Host '{name}' added successfully\n  ssh_host: {config.ssh_host}\n  Use 'hosts action=\"connect\" name=\"{name}\"' to connect"

    async def _remove_node(self, name: str) -> str:
        """Remove a host."""
        if not name:
            return "Error: 'name' parameter is required for remove action"

        if self.manager.config.get_node(name) is None:
            return f"Error: Host '{name}' not found"

        await self.manager.remove_node(name)
        return f"✓ Host '{name}' removed successfully"

    async def _connect_node(self, name: str) -> str:
        """Connect to a host."""
        if not name:
            return "Error: 'name' parameter is required for connect action"

        try:
            node = await self.manager.connect(name)
            return f"✓ Connected to '{name}' (session: {node.session_id})"
        except KeyError:
            return f"Error: Host '{name}' not found. Use 'hosts action=\"add\"' first"
        except Exception as e:
            return f"Error: Failed to connect to '{name}': {str(e)}"

    async def _disconnect_node(self, name: str) -> str:
        """Disconnect from a host."""
        if not name:
            return "Error: 'name' parameter is required for disconnect action"

        disconnected = await self.manager.disconnect(name)

        if not disconnected:
            return f"Host '{name}' is not connected"

        return f"✓ Disconnected from '{name}'"

    async def _node_status(self, name: str) -> str:
        """Get host status."""
        if not name:
            return "Error: 'name' parameter is required for status action"

        config = self.manager.config.get_node(name)
        if not config:
            return f"Error: Host '{name}' not found"

        node = self.manager.get_node(name)
        is_connected = node.is_connected if node else False

        lines = [
            f"Host: {name}",
            f"  ssh_host: {config.ssh_host}",
            f"  ssh_port: {config.ssh_port}",
            f"  status: {'Connected' if is_connected else 'Disconnected'}",
        ]

        if config.workspace:
            lines.append(f"  workspace: {config.workspace}")

        if is_connected and node:
            lines.append(f"  session_id: {node.session_id}")

        return "\n".join(lines)

    async def _exec_command(
        self,
        name: str,
        command: str,
        timeout: float = 30.0,
    ) -> str:
        """Execute a command on a host."""
        if not name:
            return "Error: 'name' parameter is required for exec action"

        if not command:
            return "Error: 'command' parameter is required for exec action"

        try:
            remote_node = await self.manager.get_or_connect(name)
            result = await remote_node.exec(command, timeout=timeout)

            if result["success"]:
                output = result.get("output") or "(no output)"
                return f"✓ Command executed successfully on '{name}':\n\n{output}"
            else:
                error = result.get("error") or "Unknown error"
                return f"✗ Command failed on '{name}':\n\n{error}"

        except KeyError:
            return f"Error: Host '{name}' not found"
        except Exception as e:
            return f"Error: Failed to execute command on '{name}': {str(e)}"


class LegacyNodesTool(NodesTool):
    """Backward-compatible alias: `nodes` -> `hosts`."""

    @property
    def name(self) -> str:
        return "nodes"

    @property
    def description(self) -> str:
        return (
            "[Deprecated alias] Use `hosts` instead. "
            "This tool manages remote hosts and executes commands on them."
        )
