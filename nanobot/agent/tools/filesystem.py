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


class CompareDirTool(Tool):
    name = "compare_dir"
    description = (
        "Compare two directories for high-level consistency across endpoints "
        "(local↔remote or remote↔remote).\n"
        "Use this tool when the user asks to compare folders, check deployment drift, "
        "or get added/removed/changed summaries before drilling into files.\n"
        "Returns summary only (counts + sampled paths). It does NOT return file-level text diffs.\n"
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
            "recursive": {
                "type": "boolean",
                "description": "Recursively scan subdirectories (default: true)",
            },
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
            "compare_content": {
                "type": "boolean",
                "description": "If true, compare file content by SHA256 hash (default: false)",
            },
        },
        "required": ["left_path", "right_path"],
    }

    _DEFAULT_IGNORES = [
        ".git/**",
        "node_modules/**",
        ".venv/**",
        "venv/**",
        "__pycache__/**",
        "*.pyc",
        ".pytest_cache/**",
        ".mypy_cache/**",
        ".ruff_cache/**",
        ".tox/**",
        ".nox/**",
        "dist/**",
        "build/**",
        "coverage/**",
        ".pnpm-store/**",
        ".npm/**",
        "._npx/**",
        ".cache/**",
        ".next/**",
        ".gradle/**",
        ".cxx/**",
        ".swiftpm/**",
        ".build/**",
        "site-packages/**",
        "*.tsbuildinfo",
        ".DS_Store",
        "Thumbs.db",
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
            return (
                "Error: local<->local compare is not supported in compare_dir. "
                "Use local tooling via exec (e.g., diff -rq / git diff --no-index)."
            )

        try:
            left_backend = await self.backend_router.resolve(left_host)
            right_backend = await self.backend_router.resolve(right_host)
        except KeyError as e:
            return f"Error: Host not found: {e}"
        except Exception as e:
            return f"Error preparing compare backends: {e}"

        ignore_cfg = await self._resolve_ignore_config(
            left_backend,
            left_path,
            right_backend,
            right_path,
            ignore_globs,
        )

        left_scan = await self._scan_tree(
            backend=left_backend,
            host=left_host,
            root_path=left_path,
            recursive=recursive,
            max_entries=max_entries,
            ignore_patterns=ignore_cfg["left_patterns"],
            compare_content=compare_content,
        )
        if left_scan.get("error"):
            return left_scan["error"]

        right_scan = await self._scan_tree(
            backend=right_backend,
            host=right_host,
            root_path=right_path,
            recursive=recursive,
            max_entries=max_entries,
            ignore_patterns=ignore_cfg["right_patterns"],
            compare_content=compare_content,
        )
        if right_scan.get("error"):
            return right_scan["error"]

        if left_scan.get("too_many") or right_scan.get("too_many"):
            return self._render_limit_exceeded(
                left_host,
                left_path,
                right_host,
                right_path,
                left_scan,
                right_scan,
                max_entries,
                ignore_cfg,
            )

        return self._render_summary(
            left_host,
            left_path,
            right_host,
            right_path,
            left_scan,
            right_scan,
            compare_content,
            recursive,
            ignore_cfg,
        )

    async def _resolve_ignore_config(
        self,
        left_backend: Any,
        left_path: str,
        right_backend: Any,
        right_path: str,
        user_globs: list[str] | None,
    ) -> dict[str, Any]:
        if user_globs:
            left_patterns = self._dedup_patterns(user_globs)
            right_patterns = self._dedup_patterns(user_globs)
            left_source = "user"
            right_source = "user"
        else:
            left_gitignore = await self._load_gitignore(left_backend, left_path)
            right_gitignore = await self._load_gitignore(right_backend, right_path)

            left_patterns = self._dedup_patterns(left_gitignore + self._DEFAULT_IGNORES)
            right_patterns = self._dedup_patterns(right_gitignore + self._DEFAULT_IGNORES)

            left_source = ".gitignore + defaults" if left_gitignore else "defaults"
            right_source = ".gitignore + defaults" if right_gitignore else "defaults"

        return {
            "left_patterns": left_patterns,
            "right_patterns": right_patterns,
            "left_source": left_source,
            "right_source": right_source,
            "asymmetric": left_patterns != right_patterns,
        }

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
        gitignore_path = f"{dir_path.rstrip('/')}/.gitignore"
        res = await backend.read_file(gitignore_path)
        if not res.get("success"):
            return []

        patterns: list[str] = []
        for raw in (res.get("content") or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Negation is intentionally unsupported in this MVP.
            if line.startswith("!"):
                continue
            patterns.append(line)
        return patterns

    async def _scan_tree(
        self,
        *,
        backend: Any,
        host: str | None,
        root_path: str,
        recursive: bool,
        max_entries: int,
        ignore_patterns: list[str],
        compare_content: bool,
    ) -> dict[str, Any]:
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
                    return {
                        "entries": entries,
                        "count": len(entries),
                        "ignored_count": ignored_count,
                        "too_many": True,
                    }

                abs_child = f"{abs_dir.rstrip('/')}/{name}"
                meta: dict[str, Any] = {"is_dir": is_dir}
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

        return {
            "entries": entries,
            "count": len(entries),
            "ignored_count": ignored_count,
            "too_many": False,
        }

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

            # Treat plain segment patterns as directory/file name match anywhere.
            if "*" not in pat and "?" not in pat and "[" not in pat:
                if base == pat:
                    return True
                if is_dir and (norm == pat or norm.endswith("/" + pat)):
                    return True

        return False

    def _render_limit_exceeded(
        self,
        left_host: str | None,
        left_path: str,
        right_host: str | None,
        right_path: str,
        left_scan: dict[str, Any],
        right_scan: dict[str, Any],
        max_entries: int,
        ignore_cfg: dict[str, Any],
    ) -> str:
        left_label = f"{left_host}:{left_path}" if left_host else f"local:{left_path}"
        right_label = f"{right_host}:{right_path}" if right_host else f"local:{right_path}"
        return (
            "Directory comparison aborted: entry limit exceeded before full analysis.\n"
            f"- left: {left_label} scanned={left_scan.get('count', 0)} (limit={max_entries})\n"
            f"- right: {right_label} scanned={right_scan.get('count', 0)} (limit={max_entries})\n"
            "Tip: narrow paths or increase max_entries.\n\n"
            + self._render_ignore_block(left_scan, right_scan, ignore_cfg)
        )

    def _render_summary(
        self,
        left_host: str | None,
        left_path: str,
        right_host: str | None,
        right_path: str,
        left_scan: dict[str, Any],
        right_scan: dict[str, Any],
        compare_content: bool,
        recursive: bool,
        ignore_cfg: dict[str, Any],
    ) -> str:
        left_entries: dict[str, dict[str, Any]] = left_scan["entries"]
        right_entries: dict[str, dict[str, Any]] = right_scan["entries"]

        left_keys = set(left_entries.keys())
        right_keys = set(right_entries.keys())

        only_left = sorted(left_keys - right_keys)
        only_right = sorted(right_keys - left_keys)
        common = sorted(left_keys & right_keys)

        type_mismatch = []
        changed_content = []
        for key in common:
            l = left_entries[key]
            r = right_entries[key]
            if bool(l.get("is_dir")) != bool(r.get("is_dir")):
                type_mismatch.append(key)
                continue
            if compare_content and not l.get("is_dir"):
                if l.get("sha256") != r.get("sha256"):
                    changed_content.append(key)

        left_label = f"{left_host}:{left_path}" if left_host else f"local:{left_path}"
        right_label = f"{right_host}:{right_path}" if right_host else f"local:{right_path}"

        def _sample(items: list[str], cap: int = 20) -> str:
            if not items:
                return "(none)"
            if len(items) <= cap:
                return "\n".join(f"  - {x}" for x in items)
            shown = "\n".join(f"  - {x}" for x in items[:cap])
            return f"{shown}\n  ... ({len(items) - cap} more)"

        lines = [
            "Directory comparison summary",
            f"- left: {left_label}",
            f"- right: {right_label}",
            f"- recursive: {recursive}",
            f"- mode: {'content-hash' if compare_content else 'structure-only'}",
            "",
            "Counts:",
            f"- left entries: {left_scan.get('count', 0)}",
            f"- right entries: {right_scan.get('count', 0)}",
            f"- only in left: {len(only_left)}",
            f"- only in right: {len(only_right)}",
            f"- type mismatch: {len(type_mismatch)}",
            f"- changed content: {len(changed_content) if compare_content else 'n/a (compare_content=false)'}",
            "",
            "Sample - only in left:",
            _sample(only_left),
            "",
            "Sample - only in right:",
            _sample(only_right),
            "",
            "Sample - type mismatch:",
            _sample(type_mismatch),
        ]

        if compare_content:
            lines += ["", "Sample - changed content:", _sample(changed_content)]

        lines += [
            "",
            self._render_ignore_block(left_scan, right_scan, ignore_cfg),
            "Note: Run compare_file on selected paths for detailed file-level diff/checksum.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _render_ignore_block(
        left_scan: dict[str, Any],
        right_scan: dict[str, Any],
        ignore_cfg: dict[str, Any],
    ) -> str:
        left_source = ignore_cfg.get("left_source", "defaults")
        right_source = ignore_cfg.get("right_source", "defaults")
        left_ignored = left_scan.get("ignored_count", 0)
        right_ignored = right_scan.get("ignored_count", 0)
        status_line = "⚠️ Asymmetric ignore rules applied" if ignore_cfg.get("asymmetric") else "✅ Symmetric ignore rules"
        return (
            "🧹 Ignore rules:\n"
            f"- Left  ({left_source}): {left_ignored} entries ignored\n"
            f"- Right ({right_source}): {right_ignored} entries ignored\n"
            f"{status_line}"
        )


class CompareFileTool(Tool):
    name = "compare_file"
    description = (
        "Compare two files for exact differences across endpoints "
        "(local↔remote or remote↔remote).\n"
        "Use this tool when the user asks to diff two files, verify exact equality, "
        "or validate a release artifact/config across hosts.\n"
        "At least one side must be remote; local↔local is intentionally unsupported "
        "(use local diff tooling via exec).\n"
        "Modes:\n"
        "- auto: detect text vs binary automatically\n"
        "- text: unified diff output\n"
        "- binary: checksum comparison (SHA256), no text diff\n"
        "Natural language mapping hints:\n"
        "- 'show line-by-line diff' -> mode=text\n"
        "- 'ignore whitespace' -> ignore_whitespace=true\n"
        "- 'case-insensitive compare' -> ignore_case=true\n"
        "- 'binary/checksum compare' -> mode=binary\n"
        "- 'keep output short' -> lower max_diff_lines"
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
        left_path, left_host, right_path, right_host = self._normalize_paths(
            left_path=left_path,
            left_host=left_host,
            right_path=right_path,
            right_host=right_host,
            local_path=local_path,
            remote_path=remote_path,
            host=host,
        )

        if not left_path or not right_path:
            return "Error: 'left_path' and 'right_path' are required"

        local_local_error = self._validate_endpoint_semantics(left_host, right_host)
        if local_local_error:
            return local_local_error

        backends_or_error = await self._resolve_backends(left_host, right_host)
        if isinstance(backends_or_error, str):
            return backends_or_error
        left_backend, right_backend = backends_or_error

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
    def _normalize_paths(
        *,
        left_path: str | None,
        left_host: str | None,
        right_path: str | None,
        right_host: str | None,
        local_path: str | None,
        remote_path: str | None,
        host: str | None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        # Backward compatibility mapping: compare(local_path, remote_path, host)
        if local_path or remote_path or host:
            left_path = left_path or local_path
            left_host = left_host or None
            right_path = right_path or remote_path
            right_host = right_host or host
        return left_path, left_host, right_path, right_host

    @staticmethod
    def _validate_endpoint_semantics(left_host: str | None, right_host: str | None) -> str | None:
        # Intentionally require at least one remote side to avoid surprising
        # local<->local semantics mismatch with users' day-to-day tooling.
        if not left_host and not right_host:
            return (
                "Error: local<->local compare is not supported in compare_file. "
                "Use your local diff tooling via exec (e.g., git diff --no-index / diff -u)."
            )
        return None

    async def _resolve_backends(self, left_host: str | None, right_host: str | None):
        try:
            left_backend = await self.backend_router.resolve(left_host)
            right_backend = await self.backend_router.resolve(right_host)
            return left_backend, right_backend
        except KeyError as e:
            return f"Error: Host not found: {e}"
        except Exception as e:
            return f"Error preparing compare backends: {e}"

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

