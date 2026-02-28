"""File system tools: read, write, edit, list, compare."""

from __future__ import annotations

import difflib
import hashlib
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


class CompareFileTool(Tool):
    name = "compare_file"
    description = (
        "Compare two files across local/remote endpoints. "
        "Use when users ask to compare/diff/check whether files are identical. "
        "Supports binary files via checksum comparison. "
        "At least one side must be remote (local<->local is intentionally unsupported)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "left_path": {"type": "string", "description": "Left-side file path"},
            "left_host": {"type": "string", "description": "Optional left host (empty = local)"},
            "right_path": {"type": "string", "description": "Right-side file path"},
            "right_host": {"type": "string", "description": "Optional right host (empty = local)"},
            "mode": {
                "type": "string",
                "enum": ["auto", "text", "binary"],
                "description": "Comparison mode (default: auto)",
            },
            "ignore_whitespace": {
                "type": "boolean",
                "description": "Ignore whitespace differences in text mode",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Ignore case differences in text mode",
            },
            "context_lines": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Unified diff context lines (default: 3)",
            },
            "max_diff_lines": {
                "type": "integer",
                "minimum": 20,
                "maximum": 2000,
                "description": "Max output lines for diff body (default: 300)",
            },

            # Legacy compatibility
            "local_path": {"type": "string", "description": "(legacy) local file path"},
            "remote_path": {"type": "string", "description": "(legacy) remote file path"},
            "host": {"type": "string", "description": "(legacy) remote host name"},
        },
    }

    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    async def execute(
        self,
        left_path: str | None = None,
        left_host: str | None = None,
        right_path: str | None = None,
        right_host: str | None = None,
        mode: str = "auto",
        ignore_whitespace: bool = False,
        ignore_case: bool = False,
        context_lines: int = 3,
        max_diff_lines: int = 300,
        local_path: str | None = None,
        remote_path: str | None = None,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        # Backward compatibility mapping: compare(local_path, remote_path, host)
        if local_path or remote_path or host:
            left_path = left_path or local_path
            left_host = left_host or None
            right_path = right_path or remote_path
            right_host = right_host or host

        if not left_path or not right_path:
            return "Error: 'left_path' and 'right_path' are required"

        try:
            left_backend = await self.backend_router.resolve(left_host)
            right_backend = await self.backend_router.resolve(right_host)
        except KeyError as e:
            return f"Error: Host not found: {e}"
        except Exception as e:
            return f"Error preparing compare backends: {e}"

        # Intentionally require at least one remote side to avoid surprising
        # local<->local semantics mismatch with users' day-to-day tooling.
        if not left_host and not right_host:
            return (
                "Error: local<->local compare is not supported in compare_file. "
                "Use your local diff tooling via exec (e.g., git diff --no-index / diff -u)."
            )

        left_bytes_res = await left_backend.read_bytes(left_path)
        if not left_bytes_res.get("success"):
            side = self._fmt_side(left_host, left_path)
            return f"Error reading {side}: {left_bytes_res.get('error')}"

        right_bytes_res = await right_backend.read_bytes(right_path)
        if not right_bytes_res.get("success"):
            side = self._fmt_side(right_host, right_path)
            return f"Error reading {side}: {right_bytes_res.get('error')}"

        left_bytes = left_bytes_res.get("content") or b""
        right_bytes = right_bytes_res.get("content") or b""

        if mode == "auto":
            mode = "binary" if (self._is_binary(left_bytes) or self._is_binary(right_bytes)) else "text"

        if mode == "binary":
            return self._compare_binary(left_host, left_path, left_bytes, right_host, right_path, right_bytes)

        return self._compare_text(
            left_host,
            left_path,
            left_bytes,
            right_host,
            right_path,
            right_bytes,
            ignore_whitespace=ignore_whitespace,
            ignore_case=ignore_case,
            context_lines=context_lines,
            max_diff_lines=max_diff_lines,
        )

    @staticmethod
    def _fmt_side(host: str | None, path: str) -> str:
        return f"{host}:{path}" if host else f"local:{path}"

    @staticmethod
    def _is_binary(data: bytes) -> bool:
        if b"\x00" in data:
            return True
        if not data:
            return False
        try:
            data.decode("utf-8")
            return False
        except UnicodeDecodeError:
            return True

    def _compare_binary(
        self,
        left_host: str | None,
        left_path: str,
        left_bytes: bytes,
        right_host: str | None,
        right_path: str,
        right_bytes: bytes,
    ) -> str:
        left_hash = hashlib.sha256(left_bytes).hexdigest()
        right_hash = hashlib.sha256(right_bytes).hexdigest()
        left_label = self._fmt_side(left_host, left_path)
        right_label = self._fmt_side(right_host, right_path)

        if left_hash == right_hash:
            return (
                "Binary files are identical (sha256 match)\n"
                f"- {left_label} ({len(left_bytes)} bytes)\n"
                f"- {right_label} ({len(right_bytes)} bytes)\n"
                f"- sha256: {left_hash}"
            )

        return (
            "Binary files differ (sha256 mismatch)\n"
            f"- {left_label} ({len(left_bytes)} bytes) sha256={left_hash}\n"
            f"- {right_label} ({len(right_bytes)} bytes) sha256={right_hash}"
        )

    def _compare_text(
        self,
        left_host: str | None,
        left_path: str,
        left_bytes: bytes,
        right_host: str | None,
        right_path: str,
        right_bytes: bytes,
        *,
        ignore_whitespace: bool,
        ignore_case: bool,
        context_lines: int,
        max_diff_lines: int,
    ) -> str:
        try:
            left_text = left_bytes.decode("utf-8")
            right_text = right_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self._compare_binary(left_host, left_path, left_bytes, right_host, right_path, right_bytes)

        left_label = self._fmt_side(left_host, left_path)
        right_label = self._fmt_side(right_host, right_path)

        left_lines = left_text.splitlines()
        right_lines = right_text.splitlines()

        cmp_left = left_lines
        cmp_right = right_lines
        if ignore_whitespace:
            cmp_left = [" ".join(line.split()) for line in cmp_left]
            cmp_right = [" ".join(line.split()) for line in cmp_right]
        if ignore_case:
            cmp_left = [line.lower() for line in cmp_left]
            cmp_right = [line.lower() for line in cmp_right]

        if cmp_left == cmp_right:
            return f"Text files are identical: {left_label} == {right_label}"

        diff = list(difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=left_label,
            tofile=right_label,
            n=context_lines,
            lineterm="",
        ))

        if len(diff) > max_diff_lines:
            shown = "\n".join(diff[:max_diff_lines])
            return (
                "Text files differ:\n"
                f"{shown}\n... (diff truncated, {len(diff) - max_diff_lines} more lines)"
            )

        return "Text files differ:\n" + "\n".join(diff)


# Backward compatibility for imports in older modules
CompareTool = CompareFileTool
