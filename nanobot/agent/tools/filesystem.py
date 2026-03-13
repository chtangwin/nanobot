"""File system tools: read, write, edit, list, compare."""

from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.backends.local import LocalExecutionBackend
from nanobot.agent.backends.router import ExecutionBackendRouter
from nanobot.agent.tools.base import Tool


def _find_match(content: str, old_text: str) -> tuple[str | None, int]:
    """Locate old_text in content: exact first, then line-trimmed sliding window."""
    if old_text in content:
        return old_text, content.count(old_text)

    old_lines = old_text.splitlines()
    if not old_lines:
        return None, 0
    stripped_old = [l.strip() for l in old_lines]
    content_lines = content.splitlines()

    candidates = []
    for i in range(len(content_lines) - len(stripped_old) + 1):
        window = content_lines[i : i + len(stripped_old)]
        if [l.strip() for l in window] == stripped_old:
            candidates.append("\n".join(window))

    if candidates:
        return candidates[0], len(candidates)
    return None, 0


class _FsTool(Tool):
    def __init__(
        self,
        backend_router: ExecutionBackendRouter | None = None,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
    ):
        if backend_router is None:
            backend_router = ExecutionBackendRouter(
                local_backend=LocalExecutionBackend(workspace=workspace, allowed_dir=allowed_dir),
                host_manager=None,
            )
        self.backend_router = backend_router


class ReadFileTool(_FsTool):
    _MAX_CHARS = 128_000
    _DEFAULT_LIMIT = 2000

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns numbered lines. Use host to read from a remote host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read"},
                "offset": {"type": "integer", "minimum": 1, "description": "Line number to start from (1-indexed)"},
                "limit": {"type": "integer", "minimum": 1, "description": "Maximum number of lines to read"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            result = await backend.read_file(path)
            if not result.get("success"):
                return f"Error: {result.get('error') or 'Failed to read file'}"
            content = result.get("content") or ""
            all_lines = content.splitlines()
            total = len(all_lines)

            if offset < 1:
                offset = 1
            if total == 0:
                return f"(Empty file: {path})"
            if offset > total:
                return f"Error: offset {offset} is beyond end of file ({total} lines)"

            start = offset - 1
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            rendered = "\n".join(numbered)

            if len(rendered) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                rendered = "\n".join(trimmed)

            if end < total:
                rendered += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
            else:
                rendered += f"\n\n(End of file — {total} lines total)"
            return rendered
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFileTool(_FsTool):
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


class EditFileTool(_FsTool):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing old_text with new_text. Supports minor whitespace/line-ending differences. "
            "Use host to edit on a remote host."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The text to find and replace"},
                "new_text": {"type": "string", "description": "The replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            read_res = await backend.read_file(path)
            if not read_res.get("success"):
                return f"Error: {read_res.get('error') or 'Failed to read file'}"

            original = read_res.get("content") or ""
            uses_crlf = "\r\n" in original
            content = original.replace("\r\n", "\n")
            match, count = _find_match(content, old_text.replace("\r\n", "\n"))
            if match is None:
                return self._not_found_msg(old_text, content, path)
            if count > 1 and not replace_all:
                return (
                    f"Warning: old_text appears {count} times. "
                    "Provide more context to make it unique, or set replace_all=true."
                )

            norm_new = new_text.replace("\r\n", "\n")
            new_content = content.replace(match, norm_new) if replace_all else content.replace(match, norm_new, 1)
            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")

            write_res = await backend.write_file(path, new_content)
            if write_res.get("success"):
                return f"Successfully edited {write_res.get('path', path)}"
            return f"Error: {write_res.get('error') or 'Failed to edit file'}"
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error editing file: {e}"

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start : best_start + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1})",
                    lineterm="",
                )
            )
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return f"Error: old_text not found in {path}. No similar text found. Verify the file content."


class ListDirTool(_FsTool):
    _DEFAULT_MAX = 200
    _IGNORE_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
    }

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List directory contents. Set recursive=true to explore nested structure. Use host to list on a remote host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to list"},
                "recursive": {"type": "boolean", "description": "Recursively list nested content"},
                "max_entries": {"type": "integer", "minimum": 1, "description": "Maximum entries to return"},
                "host": {"type": "string", "description": "Optional remote host name"},
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        recursive: bool = False,
        max_entries: int | None = None,
        host: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            backend = await self.backend_router.resolve(host)
            cap = max_entries or self._DEFAULT_MAX
            items: list[str] = []
            total = 0

            if recursive:
                stack: list[tuple[str, str]] = [("", path)]
                while stack:
                    rel_dir, abs_dir = stack.pop()
                    result = await backend.list_dir(abs_dir)
                    if not result.get("success"):
                        return f"Error: {result.get('error') or 'Failed to list directory'}"
                    for entry in result.get("entries") or []:
                        name = entry.get("name", "")
                        if name in self._IGNORE_DIRS:
                            continue
                        rel = f"{rel_dir}/{name}" if rel_dir else name
                        total += 1
                        if len(items) < cap:
                            items.append(f"{rel}/" if entry.get('is_dir') else rel)
                        if entry.get("is_dir"):
                            child = f"{abs_dir.rstrip('/')}" + f"/{name}"
                            stack.append((rel, child))
            else:
                result = await backend.list_dir(path)
                if not result.get("success"):
                    return f"Error: {result.get('error') or 'Failed to list directory'}"
                for entry in result.get("entries") or []:
                    name = entry.get("name", "")
                    if name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        prefix = "📁 " if entry.get("is_dir") else "📄 "
                        items.append(f"{prefix}{name}")

            if not items and total == 0:
                return f"Directory {path} is empty"
            rendered = "\n".join(items)
            if total > cap:
                rendered += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return rendered
        except KeyError:
            return f"Error: Host '{host}' not found"
        except Exception as e:
            return f"Error listing directory: {e}"


class CompareDirTool(Tool):
    name = "compare_dir"
    description = (
        "Compare two directories for high-level consistency across endpoints "
        "(local↔remote or remote↔remote).\n"
        "Use this tool when the user asks to compare folders, check deployment drift, "
        "or get added/removed/changed summaries before drilling into files.\n"
        "Returns summary only (raw line-based entries + counts). It does NOT return file-level text diffs.\n"
        "Constraints: at least one side must be remote; local↔local is intentionally unsupported "
        "(use local diff tools via exec).\n"
        "Natural language mapping hints:\n"
        "- 'ignore .git / node_modules / logs' -> ignore_globs\n"
        "- 'structure only' -> compare_content=false\n"
        "- 'verify content/checksum' -> compare_content=true\n"
        "- 'compare recursively' -> recursive=true\n"
        "- 'top-level only' -> recursive=false\n"
        "- 'directory is too large, give summary first' -> set/lower max_entries "
        "(entry cap; over-limit returns capped summary).\n"
        "Ignore-rule provenance is reported in output (user /.gitignore / defaults).\n"
        "Note: defaults include large generated/cache paths (including site-packages); "
        "override with explicit ignore_globs when needed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "left_path": {"type": "string", "description": "Left-side directory path"},
            "left_host": {"type": "string", "description": "Optional left host (empty = local)"},
            "right_path": {"type": "string", "description": "Right-side directory path"},
            "right_host": {"type": "string", "description": "Optional right host (empty = local)"},
            "recursive": {"type": "boolean", "description": "Recursively scan subdirectories (default: true)"},
            "max_entries": {
                "type": "integer",
                "minimum": 50,
                "maximum": 5000,
                "description": "Hard scan cap per side; if exceeded, stop and return summary (default: 500)",
            },
            "ignore_globs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ignore glob patterns (e.g., .git/**, node_modules/**). If provided, these explicit rules are used as-is.",
            },
            "compare_content": {"type": "boolean", "description": "If true, compare file content by SHA256 hash (default: false)"},
        },
        "required": ["left_path", "right_path"],
    }

    _DEFAULT_IGNORES = [
        ".git/**", "node_modules/**", ".venv/**", "venv/**", "__pycache__/**", "*.pyc", ".pytest_cache/**",
        ".mypy_cache/**", ".ruff_cache/**", ".tox/**", ".nox/**", "dist/**", "build/**", "coverage/**",
        ".pnpm-store/**", ".npm/**", "._npx/**", ".cache/**", ".next/**", ".gradle/**", ".cxx/**",
        ".swiftpm/**", ".build/**", "site-packages/**", "*.tsbuildinfo", ".DS_Store", "Thumbs.db",
    ]

    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    async def execute(
        self,
        left_path: str,
        right_path: str,
        left_host: str | None = None,
        right_host: str | None = None,
        recursive: bool = True,
        max_entries: int = 500,
        ignore_globs: list[str] | None = None,
        compare_content: bool = False,
        **kwargs: Any,
    ) -> str:
        if not left_host and not right_host:
            return "Error: local<->local compare is not supported in compare_dir. Use local tooling via exec (e.g., diff -rq / git diff --no-index)."
        try:
            left_backend = await self.backend_router.resolve(left_host)
            right_backend = await self.backend_router.resolve(right_host)
        except KeyError as e:
            return f"Error: Host not found: {e}"
        except Exception as e:
            return f"Error preparing compare backends: {e}"

        ignore_cfg = await self._resolve_ignore_config(left_backend, left_path, right_backend, right_path, ignore_globs)
        left_scan = await self._scan_tree(left_backend, left_host, left_path, recursive, max_entries, ignore_cfg["left_patterns"], compare_content)
        if left_scan.get("error"):
            return left_scan["error"]
        right_scan = await self._scan_tree(right_backend, right_host, right_path, recursive, max_entries, ignore_cfg["right_patterns"], compare_content)
        if right_scan.get("error"):
            return right_scan["error"]
        if left_scan.get("too_many") or right_scan.get("too_many"):
            return self._render_limit_exceeded(left_host, left_path, right_host, right_path, left_scan, right_scan, max_entries, ignore_cfg)
        return self._render_summary(left_host, left_path, right_host, right_path, left_scan, right_scan, compare_content, recursive, ignore_cfg)

    async def _resolve_ignore_config(self, left_backend: Any, left_path: str, right_backend: Any, right_path: str, user_globs: list[str] | None) -> dict[str, Any]:
        if user_globs:
            left_patterns = self._dedup_patterns(user_globs)
            right_patterns = self._dedup_patterns(user_globs)
            left_source = right_source = "user"
        else:
            left_gitignore = await self._load_gitignore(left_backend, left_path)
            right_gitignore = await self._load_gitignore(right_backend, right_path)
            left_patterns = self._dedup_patterns(left_gitignore + self._DEFAULT_IGNORES)
            right_patterns = self._dedup_patterns(right_gitignore + self._DEFAULT_IGNORES)
            left_source = ".gitignore + defaults" if left_gitignore else "defaults"
            right_source = ".gitignore + defaults" if right_gitignore else "defaults"
        return {"left_patterns": left_patterns, "right_patterns": right_patterns, "left_source": left_source, "right_source": right_source, "asymmetric": left_patterns != right_patterns}

    @staticmethod
    def _dedup_patterns(patterns: list[str]) -> list[str]:
        dedup: list[str] = []
        seen: set[str] = set()
        for p in patterns:
            if p and p not in seen:
                dedup.append(p)
                seen.add(p)
        return dedup

    async def _load_gitignore(self, backend: Any, dir_path: str) -> list[str]:
        res = await backend.read_file(f"{dir_path.rstrip('/')}/.gitignore")
        if not res.get("success"):
            return []
        patterns = []
        for raw in (res.get("content") or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            patterns.append(line)
        return patterns

    async def _scan_tree(self, backend: Any, host: str | None, root_path: str, recursive: bool, max_entries: int, ignore_patterns: list[str], compare_content: bool) -> dict[str, Any]:
        entries: dict[str, dict[str, Any]] = {}
        ignored_count = 0
        stack: list[tuple[str, str]] = [("", root_path)]
        while stack:
            rel_dir, abs_dir = stack.pop()
            listed = await backend.list_dir(abs_dir)
            if not listed.get("success"):
                side = f"{host}:{root_path}" if host else f"local:{root_path}"
                return {"error": f"Error listing directory {side}: {listed.get('error')}"}
            for item in listed.get("entries") or []:
                name = item.get("name") or ""
                is_dir = bool(item.get("is_dir"))
                rel = f"{rel_dir}/{name}" if rel_dir else name
                if self._should_ignore(rel, is_dir, ignore_patterns):
                    ignored_count += 1
                    continue
                if len(entries) >= max_entries:
                    return {"entries": entries, "count": len(entries), "ignored_count": ignored_count, "too_many": True}
                abs_child = f"{abs_dir.rstrip('/')}/{name}"
                meta: dict[str, Any] = {"is_dir": is_dir, "size": item.get("size"), "mtime": item.get("mtime")}
                if compare_content and not is_dir:
                    rb = await backend.read_bytes(abs_child)
                    if not rb.get("success"):
                        side = f"{host}:{abs_child}" if host else f"local:{abs_child}"
                        return {"error": f"Error reading bytes {side}: {rb.get('error')}"}
                    data = rb.get("content") or b""
                    meta["size"] = len(data)
                    meta["sha256"] = hashlib.sha256(data).hexdigest()
                entries[rel] = meta
                if recursive and is_dir:
                    stack.append((rel, abs_child))
        return {"entries": entries, "count": len(entries), "ignored_count": ignored_count, "too_many": False}

    @staticmethod
    def _should_ignore(rel_path: str, is_dir: bool, patterns: list[str]) -> bool:
        import fnmatch

        norm = rel_path.strip("/")
        base = norm.split("/")[-1] if norm else norm
        for p in patterns:
            pat = (p or "").strip()
            if not pat:
                continue
            if pat.startswith("/"):
                pat = pat[1:]
            if pat.endswith("/"):
                d = pat.rstrip("/")
                if norm == d or norm.startswith(d + "/") or base == d:
                    return True
                continue
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(base, pat):
                return True
            if "*" not in pat and "?" not in pat and "[" not in pat:
                if base == pat:
                    return True
                if is_dir and (norm == pat or norm.endswith("/" + pat)):
                    return True
        return False

    def _render_limit_exceeded(self, left_host: str | None, left_path: str, right_host: str | None, right_path: str, left_scan: dict[str, Any], right_scan: dict[str, Any], max_entries: int, ignore_cfg: dict[str, Any]) -> str:
        left_label = f"{left_host}:{left_path}" if left_host else f"local:{left_path}"
        right_label = f"{right_host}:{right_path}" if right_host else f"local:{right_path}"
        return (
            "Directory comparison aborted: entry limit exceeded before full analysis.\n"
            f"- left: {left_label} scanned={left_scan.get('count', 0)} (limit={max_entries})\n"
            f"- right: {right_label} scanned={right_scan.get('count', 0)} (limit={max_entries})\n"
            "Tip: narrow paths or increase max_entries.\n\n" + self._render_ignore_block(left_scan, right_scan, ignore_cfg)
        )

    def _render_summary(self, left_host: str | None, left_path: str, right_host: str | None, right_path: str, left_scan: dict[str, Any], right_scan: dict[str, Any], compare_content: bool, recursive: bool, ignore_cfg: dict[str, Any]) -> str:
        left_entries: dict[str, dict[str, Any]] = left_scan["entries"]
        right_entries: dict[str, dict[str, Any]] = right_scan["entries"]
        left_keys = set(left_entries.keys())
        right_keys = set(right_entries.keys())
        only_left = sorted(left_keys - right_keys)
        only_right = sorted(right_keys - left_keys)
        common = sorted(left_keys & right_keys)
        type_mismatch: list[str] = []
        different_files: list[str] = []
        for key in common:
            l = left_entries[key]
            r = right_entries[key]
            if bool(l.get("is_dir")) != bool(r.get("is_dir")):
                type_mismatch.append(f"{key} (left={'dir' if l.get('is_dir') else 'file'}, right={'dir' if r.get('is_dir') else 'file'})")
                continue
            if l.get("is_dir"):
                continue
            if compare_content:
                if l.get("sha256") != r.get("sha256"):
                    different_files.append(f"{key} checksum(left={(l.get('sha256') or 'n/a')[:12]}, right={(r.get('sha256') or 'n/a')[:12]})")
                continue
            details: list[str] = []
            if l.get("size") is not None and r.get("size") is not None and l.get("size") != r.get("size"):
                details.append(f"size(left={l.get('size')}, right={r.get('size')})")
            if l.get("mtime") is not None and r.get("mtime") is not None and l.get("mtime") != r.get("mtime"):
                details.append(f"mtime(left={self._format_mtime(l.get('mtime'))} [{l.get('mtime')}], right={self._format_mtime(r.get('mtime'))} [{r.get('mtime')}])")
            if details:
                different_files.append(f"{key} {' '.join(details)}")
        left_label = f"{left_host}:{left_path}" if left_host else f"local:{left_path}"
        right_label = f"{right_host}:{right_path}" if right_host else f"local:{right_path}"
        lines = [
            "[FULL DIFF]",
            "COMPARE_DIR v1",
            f"LEFT {left_label}",
            f"RIGHT {right_label}",
            f"RECURSIVE {str(recursive).lower()}",
            f"MODE {'content-hash' if compare_content else 'structure-only'}",
            f"LEFT_ENTRIES {left_scan.get('count', 0)}",
            f"RIGHT_ENTRIES {right_scan.get('count', 0)}",
            "",
        ]
        lines.extend(f"ONLY_LEFT {p}" for p in only_left)
        lines.extend(f"ONLY_RIGHT {p}" for p in only_right)
        lines.extend(f"TYPE_MISMATCH {p}" for p in type_mismatch)
        lines.extend(f"DIFF_FILE {p}" for p in different_files)
        lines += [
            "[/FULL DIFF]",
            "",
            "SUMMARY "
            f"only_left={len(only_left)} only_right={len(only_right)} type_mismatch={len(type_mismatch)} "
            f"different_files={len(different_files)} diff_mode={'checksum' if compare_content else 'size/mtime'}",
            self._render_ignore_block(left_scan, right_scan, ignore_cfg),
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_mtime(ts: Any) -> str:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            return str(ts)

    @staticmethod
    def _render_ignore_block(left_scan: dict[str, Any], right_scan: dict[str, Any], ignore_cfg: dict[str, Any]) -> str:
        left_source = ignore_cfg.get("left_source", "defaults")
        right_source = ignore_cfg.get("right_source", "defaults")
        left_ignored = left_scan.get("ignored_count", 0)
        right_ignored = right_scan.get("ignored_count", 0)
        status_line = "⚠️ Asymmetric ignore rules applied" if ignore_cfg.get("asymmetric") else "✅ Symmetric ignore rules"
        return "[SHOW TO USER]\n🧹 Ignore rules:\n" f"- Left  ({left_source}): {left_ignored} entries ignored\n" f"- Right ({right_source}): {right_ignored} entries ignored\n" f"{status_line}\n[/SHOW TO USER]"


class CompareFileTool(Tool):
    name = "compare_file"
    description = (
        "Compare two files for exact differences across endpoints "
        "(local↔remote or remote↔remote).\n"
        "Use this tool when the user asks to diff two files, verify exact equality, "
        "or validate a release artifact/config across hosts.\n"
        "At least one side must be remote; local↔local is intentionally unsupported "
        "(use local diff tooling via exec).\n"
        "Modes:\n- auto: detect text vs binary automatically\n- text: unified diff output\n- binary: checksum comparison (SHA256), no text diff"
    )
    parameters = {
        "type": "object",
        "properties": {
            "left_path": {"type": "string", "description": "Left-side file path"},
            "left_host": {"type": "string", "description": "Optional left host (empty = local)"},
            "right_path": {"type": "string", "description": "Right-side file path"},
            "right_host": {"type": "string", "description": "Optional right host (empty = local)"},
            "mode": {"type": "string", "enum": ["auto", "text", "binary"], "description": "Comparison mode (default: auto)"},
            "ignore_whitespace": {"type": "boolean", "description": "Ignore whitespace differences in text mode"},
            "ignore_case": {"type": "boolean", "description": "Ignore case differences in text mode"},
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 20, "description": "Unified diff context lines (default: 3)"},
            "max_diff_lines": {"type": "integer", "minimum": 20, "maximum": 2000, "description": "Max output lines for diff body (default: 300)"},
            "local_path": {"type": "string", "description": "(legacy) local file path"},
            "remote_path": {"type": "string", "description": "(legacy) remote file path"},
            "host": {"type": "string", "description": "(legacy) remote host name"},
        },
    }

    def __init__(self, backend_router: ExecutionBackendRouter):
        self.backend_router = backend_router

    async def execute(self, left_path: str | None = None, left_host: str | None = None, right_path: str | None = None, right_host: str | None = None, mode: str = "auto", ignore_whitespace: bool = False, ignore_case: bool = False, context_lines: int = 3, max_diff_lines: int = 300, local_path: str | None = None, remote_path: str | None = None, host: str | None = None, **kwargs: Any) -> str:
        left_path, left_host, right_path, right_host = self._normalize_paths(left_path=left_path, left_host=left_host, right_path=right_path, right_host=right_host, local_path=local_path, remote_path=remote_path, host=host)
        if not left_path or not right_path:
            return "Error: 'left_path' and 'right_path' are required"
        if not left_host and not right_host:
            return "Error: local<->local compare is not supported in compare_file. Use your local diff tooling via exec (e.g., git diff --no-index / diff -u)."
        try:
            left_backend = await self.backend_router.resolve(left_host)
            right_backend = await self.backend_router.resolve(right_host)
        except KeyError as e:
            return f"Error: Host not found: {e}"
        except Exception as e:
            return f"Error preparing compare backends: {e}"
        left_bytes_or_error = await self._read_side_bytes(left_backend, left_host, left_path)
        if isinstance(left_bytes_or_error, str):
            return left_bytes_or_error
        right_bytes_or_error = await self._read_side_bytes(right_backend, right_host, right_path)
        if isinstance(right_bytes_or_error, str):
            return right_bytes_or_error
        left_bytes = left_bytes_or_error
        right_bytes = right_bytes_or_error
        mode = self._resolve_mode(mode, left_bytes, right_bytes)
        if mode == "binary":
            return self._compare_binary(left_host, left_path, left_bytes, right_host, right_path, right_bytes)
        return self._compare_text(left_host, left_path, left_bytes, right_host, right_path, right_bytes, ignore_whitespace=ignore_whitespace, ignore_case=ignore_case, context_lines=context_lines, max_diff_lines=max_diff_lines)

    @staticmethod
    def _normalize_paths(*, left_path: str | None, left_host: str | None, right_path: str | None, right_host: str | None, local_path: str | None, remote_path: str | None, host: str | None) -> tuple[str | None, str | None, str | None, str | None]:
        if local_path or remote_path or host:
            left_path = left_path or local_path
            left_host = left_host or None
            right_path = right_path or remote_path
            right_host = right_host or host
        return left_path, left_host, right_path, right_host

    async def _read_side_bytes(self, backend: Any, host: str | None, path: str) -> bytes | str:
        result = await backend.read_bytes(path)
        if not result.get("success"):
            side = self._fmt_side(host, path)
            return f"Error reading {side}: {result.get('error')}"
        return result.get("content") or b""

    def _resolve_mode(self, mode: str, left_bytes: bytes, right_bytes: bytes) -> str:
        if mode == "auto":
            return "binary" if (self._is_binary(left_bytes) or self._is_binary(right_bytes)) else "text"
        return mode

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

    def _compare_binary(self, left_host: str | None, left_path: str, left_bytes: bytes, right_host: str | None, right_path: str, right_bytes: bytes) -> str:
        left_hash = hashlib.sha256(left_bytes).hexdigest()
        right_hash = hashlib.sha256(right_bytes).hexdigest()
        left_label = self._fmt_side(left_host, left_path)
        right_label = self._fmt_side(right_host, right_path)
        if left_hash == right_hash:
            return f"Binary files are identical (sha256 match)\n- {left_label} ({len(left_bytes)} bytes)\n- {right_label} ({len(right_bytes)} bytes)\n- sha256: {left_hash}"
        return f"Binary files differ (sha256 mismatch)\n- {left_label} ({len(left_bytes)} bytes) sha256={left_hash}\n- {right_label} ({len(right_bytes)} bytes) sha256={right_hash}"

    def _compare_text(self, left_host: str | None, left_path: str, left_bytes: bytes, right_host: str | None, right_path: str, right_bytes: bytes, *, ignore_whitespace: bool, ignore_case: bool, context_lines: int, max_diff_lines: int) -> str:
        try:
            left_text = left_bytes.decode("utf-8")
            right_text = right_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self._compare_binary(left_host, left_path, left_bytes, right_host, right_path, right_bytes)
        left_label = self._fmt_side(left_host, left_path)
        right_label = self._fmt_side(right_host, right_path)
        left_lines = left_text.splitlines()
        right_lines = right_text.splitlines()
        cmp_left = [" ".join(line.split()) for line in left_lines] if ignore_whitespace else left_lines
        cmp_right = [" ".join(line.split()) for line in right_lines] if ignore_whitespace else right_lines
        if ignore_case:
            cmp_left = [line.lower() for line in cmp_left]
            cmp_right = [line.lower() for line in cmp_right]
        if cmp_left == cmp_right:
            if left_bytes != right_bytes:
                details = []
                left_has_crlf = b"\r\n" in left_bytes
                right_has_crlf = b"\r\n" in right_bytes
                if left_has_crlf != right_has_crlf:
                    details.append(f"line endings differ: {left_label} uses {'CRLF' if left_has_crlf else 'LF'}, {right_label} uses {'CRLF' if right_has_crlf else 'LF'}")
                if len(left_bytes) != len(right_bytes):
                    details.append(f"size: {len(left_bytes)} vs {len(right_bytes)} bytes")
                note = "; ".join(details) if details else "raw bytes differ"
                return f"Text content is logically identical but {note}: {left_label} vs {right_label}"
            return f"Text files are identical: {left_label} == {right_label}"
        diff = list(difflib.unified_diff(left_lines, right_lines, fromfile=left_label, tofile=right_label, n=context_lines, lineterm=""))
        if len(diff) > max_diff_lines:
            shown = "\n".join(diff[:max_diff_lines])
            return f"Text files differ:\n{shown}\n... (diff truncated, {len(diff) - max_diff_lines} more lines)"
        return "Text files differ:\n" + "\n".join(diff)
