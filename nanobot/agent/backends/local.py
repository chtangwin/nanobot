"""Local execution backend."""

from __future__ import annotations

import asyncio
import difflib
import os
from pathlib import Path
from typing import Any

from nanobot.agent.backends.base import ExecutionBackend
from nanobot.agent.tools.redaction import is_sensitive_path


class LocalExecutionBackend(ExecutionBackend):
    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        block_sensitive_files: bool = True,
        path_append: str = "",
    ):
        self.workspace = workspace
        self.allowed_dir = allowed_dir
        self.block_sensitive_files = block_sensitive_files
        self.path_append = path_append

    def _resolve_path(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute() and self.workspace:
            p = self.workspace / p
        resolved = p.resolve()

        if self.block_sensitive_files and is_sensitive_path(resolved):
            raise PermissionError(f"Access to sensitive path is blocked by redaction policy: {path}")

        if self.allowed_dir:
            try:
                resolved.relative_to(self.allowed_dir.resolve())
            except ValueError:
                raise PermissionError(f"Path {path} is outside allowed directory {self.allowed_dir}")

        return resolved

    async def exec(self, command: str, working_dir: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
        cwd = working_dir or (str(self.workspace) if self.workspace else os.getcwd())
        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return {
                "success": False,
                "output": None,
                "error": f"Command timed out after {timeout} seconds",
                "exit_code": -1,
                "cwd": cwd,
            }

        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""

        return {
            "success": process.returncode == 0,
            "output": out,
            "error": err or None,
            "exit_code": process.returncode,
            "cwd": cwd,
        }

    async def read_file(self, path: str) -> dict[str, Any]:
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not file_path.is_file():
                return {"success": False, "error": f"Not a file: {path}"}
            return {"success": True, "content": file_path.read_text(encoding="utf-8")}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Error reading file: {e}"}

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        try:
            file_path = self._resolve_path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return {"success": True, "bytes": len(content), "path": str(file_path)}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Error writing file: {e}"}

    async def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, Any]:
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}

            content = file_path.read_text(encoding="utf-8")
            if old_text not in content:
                lines = content.splitlines(keepends=True)
                old_lines = old_text.splitlines(keepends=True)
                window = len(old_lines)
                best_ratio, best_start = 0.0, 0
                for i in range(max(1, len(lines) - window + 1)):
                    ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
                    if ratio > best_ratio:
                        best_ratio, best_start = ratio, i
                if best_ratio > 0.5:
                    diff = "\n".join(difflib.unified_diff(
                        old_lines,
                        lines[best_start : best_start + window],
                        fromfile="old_text (provided)",
                        tofile=f"{path} (actual, line {best_start + 1})",
                        lineterm="",
                    ))
                    return {
                        "success": False,
                        "error": f"old_text not found in {path}. Best match ({best_ratio:.0%}) at line {best_start + 1}:\n{diff}",
                    }
                return {"success": False, "error": f"old_text not found in {path}. No similar text found."}

            count = content.count(old_text)
            if count > 1:
                return {"success": False, "error": f"old_text appears {count} times. Please provide more context."}

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")
            return {"success": True, "path": str(file_path)}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Error editing file: {e}"}

    async def list_dir(self, path: str) -> dict[str, Any]:
        try:
            dir_path = self._resolve_path(path)
            if not dir_path.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            if not dir_path.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            entries = [
                {"name": item.name, "is_dir": item.is_dir()}
                for item in sorted(dir_path.iterdir())
            ]
            return {"success": True, "entries": entries}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Error listing directory: {e}"}
