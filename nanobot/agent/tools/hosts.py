"""Hosts tool for managing and executing commands on remote hosts."""

import logging
from typing import Any, Optional

from nanobot.agent.tools.base import Tool
from nanobot.remote.config import HostsConfig
from nanobot.remote.manager import HostManager

logger = logging.getLogger(__name__)


class HostsTool(Tool):
    """Tool for managing remote hosts and executing commands on them."""

    def __init__(self, config_path: Optional[str] = None, host_manager: Optional[HostManager] = None):
        if host_manager:
            self.manager = host_manager
        elif config_path:
            config = HostsConfig.load(config_path)
            self.manager = HostManager(config)
        else:
            config = HostsConfig.load(HostsConfig.get_default_config_path())
            self.manager = HostManager(config)

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
- disconnect: ⚠️ TEARDOWN: kills remote_server, tmux session, and deletes /tmp/nanobot-* — use only when completely done (requires: name)
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
                    "description": "Action to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Host name (for add/remove/connect/disconnect/status/exec)",
                },
                "ssh_host": {
                    "type": "string",
                    "description": "SSH host in user@host format (for add)",
                },
                "ssh_port": {
                    "type": "integer",
                    "description": "SSH port (default: 22, for add)",
                },
                "ssh_key_path": {
                    "type": "string",
                    "description": "Path to SSH private key (for add)",
                },
                "workspace": {
                    "type": "string",
                    "description": "Default workspace directory on remote (for add)",
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute (for exec)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Set true ONLY when user explicitly asked to disconnect. Never set on your own.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Command timeout in seconds (default: 30, for exec)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")

        try:
            if action == "list":
                return await self._list_hosts()
            if action == "add":
                return await self._add_host(
                    name=kwargs.get("name"),
                    ssh_host=kwargs.get("ssh_host"),
                    ssh_port=kwargs.get("ssh_port"),
                    ssh_key_path=kwargs.get("ssh_key_path"),
                    workspace=kwargs.get("workspace"),
                )
            if action == "remove":
                return await self._remove_host(name=kwargs.get("name"))
            if action == "connect":
                return await self._connect_host(name=kwargs.get("name"))
            if action == "disconnect":
                if not kwargs.get("confirm"):
                    return "⚠️ This will TEARDOWN the remote session (kill remote_server, tmux, delete /tmp/nanobot-*). Ask the user to confirm before proceeding."
                return await self._disconnect_host(name=kwargs.get("name"))
            if action == "status":
                return await self._host_status(name=kwargs.get("name"))
            if action == "exec":
                return await self._exec_command(
                    name=kwargs.get("name"),
                    command=kwargs.get("command"),
                    timeout=kwargs.get("timeout", 30.0),
                )
            return f"Error: Unknown action '{action}'"
        except Exception as e:
            logger.exception(f"Error executing hosts tool action: {action}")
            return f"Error: {e}"

    async def _list_hosts(self) -> str:
        hosts = self.manager.list_hosts()
        if not hosts:
            return "No hosts configured. Use 'hosts action=\"add\"' to add a host."

        lines = ["Configured hosts:"]
        for host in hosts:
            status = "✓ connected" if host["connected"] else "○ disconnected"
            lines.append(f"\n  {host['name']}: {host['ssh_host']} [{status}]")
            if host.get("workspace"):
                lines.append(f"    workspace: {host['workspace']}")
        return "\n".join(lines)

    async def _add_host(
        self,
        name: str,
        ssh_host: str,
        ssh_port: Optional[int] = None,
        ssh_key_path: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> str:
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

        config = await self.manager.add_host(name, ssh_host, **kwargs)
        return (
            f"✓ Host '{name}' added successfully\n"
            f"  ssh_host: {config.ssh_host}\n"
            f"  Use 'hosts action=\"connect\" name=\"{name}\"' to connect"
        )

    async def _remove_host(self, name: str) -> str:
        if not name:
            return "Error: 'name' parameter is required for remove action"
        if self.manager.config.get_host(name) is None:
            return f"Error: Host '{name}' not found"
        await self.manager.remove_host(name)
        return f"✓ Host '{name}' removed successfully"

    async def _connect_host(self, name: str) -> str:
        if not name:
            return "Error: 'name' parameter is required for connect action"
        try:
            host = await self.manager.connect(name)
            return f"✓ Connected to '{name}' (session: {host.session_id})"
        except KeyError:
            return f"Error: Host '{name}' not found. Use 'hosts action=\"add\"' first"
        except Exception as e:
            return f"Error: Failed to connect to '{name}': {e}"

    async def _disconnect_host(self, name: str) -> str:
        if not name:
            return "Error: 'name' parameter is required for disconnect action"
        disconnected = await self.manager.disconnect(name)
        if not disconnected:
            return f"Host '{name}' is not connected"
        return f"✓ Disconnected from '{name}'"

    async def _host_status(self, name: str) -> str:
        if not name:
            return "Error: 'name' parameter is required for status action"

        config = self.manager.config.get_host(name)
        if not config:
            return f"Error: Host '{name}' not found"

        host = self.manager.get_host(name)
        is_connected = host.is_connected if host else False

        lines = [
            f"Host: {name}",
            f"  ssh_host: {config.ssh_host}",
            f"  ssh_port: {config.ssh_port}",
            f"  status: {'Connected' if is_connected else 'Disconnected'}",
        ]
        if config.workspace:
            lines.append(f"  workspace: {config.workspace}")
        if is_connected and host:
            lines.append(f"  session_id: {host.session_id}")
        return "\n".join(lines)

    async def _exec_command(self, name: str, command: str, timeout: float = 30.0) -> str:
        if not name:
            return "Error: 'name' parameter is required for exec action"
        if not command:
            return "Error: 'command' parameter is required for exec action"

        try:
            remote_host = await self.manager.get_or_connect(name)
            result = await remote_host.exec(command, timeout=timeout)
            if result["success"]:
                output = result.get("output") or "(no output)"
                return f"✓ Command executed successfully on '{name}':\n\n{output}"
            error = result.get("error") or "Unknown error"
            return f"✗ Command failed on '{name}':\n\n{error}"
        except KeyError:
            return f"Error: Host '{name}' not found"
        except Exception as e:
            return f"Error: Failed to execute command on '{name}': {e}"
