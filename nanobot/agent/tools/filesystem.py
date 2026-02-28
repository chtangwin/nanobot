"""File system tools: read, write, edit, list, compare."""

from __future__ import annotations

import difflib
from typing import Any

from nanobot.agent.backends.router import ExecutionBackendRouter
from nanobot.agent.tools.base import Tool


class ReadFileTool(Tool):
    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Use host to read from a remote host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, host: str | None = None, **kwargs: Any) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.read_file(path)
            if result.get("success"):
                return result.get("content") or ""
            return f"Error: {result.get('error') or 'Failed to read file'}"
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFileTool(Tool):
    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Use host to write to a remote host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, host: str | None = None, **kwargs: Any) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.write_file(path, content)
            if result.get("success"):
                if host:
                    return f"Successfully wrote {len(content)} bytes to {path} on host '{host}'"
                return f"Successfully wrote {len(content)} bytes to {result.get('path', path)}"
            return f"Error: {result.get('error') or 'Failed to write file'}"
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error writing file: {e}"


class EditFileTool(Tool):
    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "Exact text to replace"},
                "new_text": {"type": "string", "description": "Replacement text"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(
        self,
        path: str,
        old_text: str,
        new_text: str,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.edit_file(path, old_text, new_text)
            if result.get("success"):
                return f"Successfully edited {result.get('path', path)}"
            return f"Error: {result.get('error') or 'Failed to edit file'}"
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error editing file: {e}"


class ListDirTool(Tool):
    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List directory contents. Use host to list on a remote host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to list"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, host: str | None = None, **kwargs: Any) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.list_dir(path)
            if not result.get("success"):
                return f"Error: {result.get('error') or 'Failed to list directory'}"

            entries = result.get("entries") or []
            if not entries:
                return f"Directory {path} is empty"

            lines = []
            for entry in entries:
                prefix = "📁 " if entry.get("is_dir") else "📄 "
                lines.append(f"{prefix}{entry.get('name', '')}")
            return "\n".join(lines)
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error listing directory: {e}"


class CompareTool(Tool):
    name = "compare"
    description = (
        "Compare a local file with a remote file on a host and return unified diff format."
    )
    parameters = {
        "type": "object",
        "properties": {
            "local_path": {"type": "string", "description": "Path to local file"},
            "remote_path": {"type": "string", "description": "Path to remote file"},
            "host": {"type": "string", "description": "Host name (e.g., myserver)"},
        },
        "required": ["local_path", "remote_path", "host"],
    }

    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    async def execute(self, local_path: str, remote_path: str, host: str, **kwargs: Any) -> str:
        try:
            local_backend = await self.backend_router.resolve(None)
            remote_backend = await self.backend_router.resolve(host)

            local_result = await local_backend.read_file(local_path)
            if not local_result.get("success"):
                return f"Error reading local file: {local_result.get('error')}"

            remote_result = await remote_backend.read_file(remote_path)
            if not remote_result.get("success"):
                return f"Error reading remote file: {remote_result.get('error')}"

            local_lines = (local_result.get("content") or "").splitlines()
            remote_lines = (remote_result.get("content") or "").splitlines()

            diff = list(difflib.unified_diff(
                local_lines,
                remote_lines,
                fromfile=f"local:{local_path}",
                tofile=f"remote:{host}:{remote_path}",
                lineterm="",
            ))
            if not diff:
                return f"Files are identical: {local_path} == {host}:{remote_path}"
            return "Files differ:\n" + "\n".join(diff)
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error comparing files: {e}"
