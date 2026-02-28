"""Remote execution backend."""

from __future__ import annotations

from typing import Any

from nanobot.agent.backends.base import ExecutionBackend
from nanobot.nodes.connection import RemoteNode


class RemoteExecutionBackend(ExecutionBackend):
    def __init__(self, host: str, remote_node: RemoteNode):
        self.host = host
        self.remote_node = remote_node

    async def exec(self, command: str, working_dir: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
        full_command = f"cd '{working_dir}' && {command}" if working_dir else command
        result = await self.remote_node.exec(full_command, timeout=timeout)
        result["host"] = self.host
        result["command"] = command
        result["working_dir"] = working_dir
        return result

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self.remote_node.read_file(path, timeout=30.0)

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        return await self.remote_node.write_file(path, content, timeout=30.0)

    async def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, Any]:
        return await self.remote_node.edit_file(path, old_text, new_text, timeout=30.0)

    async def list_dir(self, path: str) -> dict[str, Any]:
        return await self.remote_node.list_dir(path, timeout=30.0)
