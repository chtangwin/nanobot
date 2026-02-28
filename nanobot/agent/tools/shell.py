"""Shell execution tool."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nanobot.agent.backends.router import ExecutionBackendRouter
from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        backend_router: ExecutionBackendRouter,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
    ):
        self.backend_router = backend_router
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",
            r"\bdel\s+/[fq]\b",
            r"\brmdir\s+/s\b",
            r"(?:^|[;&|]\s*)format\b",
            r"\b(mkfs|diskpart)\b",
            r"\bdd\s+if=",
            r">\s*/dev/sd",
            r"\b(shutdown|reboot|poweroff)\b",
            r":\(\)\s*\{.*\};\s*:",
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "For remote hosts (e.g., 'on myserver run ls'), use the 'host' parameter "
            "instead of manually constructing SSH commands."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {"type": "string", "description": "Optional working directory"},
                "host": {
                    "type": "string",
                    "description": "Remote host name. If omitted, run locally.",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        cwd = working_dir or self.working_dir
        if not host:
            guard_error = self._guard_command(command, cwd or str(Path.cwd()))
            if guard_error:
                return guard_error

        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.exec(command, working_dir=cwd, timeout=self.timeout)
        except KeyError:
            return f"Error: Host '{host}' not found. Use 'hosts action=\"add\"' to add it first"
        except Exception as e:
            return f"Error executing command: {e}"

        if not result.get("success"):
            error = result.get("error") or "Command failed"
            prefix = f"🔧 Tool: exec\n🌐 Host: {host}\n" if host else "🔧 Tool: exec\n"
            return f"{prefix}⚡ Cmd: {command}\n\n❌ Error: {error}"

        output = result.get("output") or "(no output)"
        stderr = result.get("error")
        if stderr:
            output += f"\nSTDERR:\n{stderr}"

        prefix_lines = ["🔧 Tool: exec"]
        if host:
            prefix_lines.append(f"🌐 Host: {host}")
        prefix_lines.append(f"📁 CWD: {cwd or '(default)'}")
        prefix_lines.append(f"⚡ Cmd: {command}")

        rendered = "\n".join(prefix_lines) + "\n\n" + output
        max_len = 50000
        if len(rendered) > max_len:
            rendered = rendered[:max_len] + f"\n... (truncated, {len(rendered) - max_len} more chars)"
        return rendered

    def _guard_command(self, command: str, cwd: str) -> str | None:
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns and not any(re.search(p, lower) for p in self.allow_patterns):
            return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()
            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)
            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
