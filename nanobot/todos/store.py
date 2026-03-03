"""Markdown store for todos."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

from nanobot.todos.types import TodosDocument, TodosItem

_ID_RE = re.compile(r"#(\d+)\b")
_META_RE = re.compile(r"@(\w+)\(([^)]*)\)")
_ITEM_RE = re.compile(r"^(\s*)-\s(\[[ xX]\]|📝)\s+(.+?)\s*$")
_ARCHIVE_FROM_RE = re.compile(r"\s\[([^\[\]]+)\]\s*$")
_DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2})?$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}$")


class TodosStore:
    """Read/write TODOS.md with tolerant parser."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    def todos_path(self, channel: str, chat_id: str) -> Path:
        return self.workspace / "todos" / channel / chat_id / "TODOS.md"

    def list_todo_files(self) -> list[Path]:
        root = self.workspace / "todos"
        if not root.exists():
            return []
        return sorted(root.glob("*/*/TODOS.md"))

    def path_to_scope(self, path: Path) -> tuple[str, str] | None:
        try:
            rel = path.relative_to(self.workspace / "todos")
        except ValueError:
            return None
        if len(rel.parts) < 3:
            return None
        return rel.parts[0], rel.parts[1]

    def load(self, channel: str, chat_id: str) -> TodosDocument:
        path = self.todos_path(channel, chat_id)
        if not path.exists():
            return TodosDocument(timezone=None, items=[])
        text = path.read_text(encoding="utf-8")
        return self.parse(text)

    def save(self, channel: str, chat_id: str, doc: TodosDocument) -> None:
        path = self.todos_path(channel, chat_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write(path, self.serialize(doc))

    def load_by_path(self, path: Path) -> TodosDocument:
        if not path.exists():
            return TodosDocument(timezone=None, items=[])
        return self.parse(path.read_text(encoding="utf-8"))

    def save_by_path(self, path: Path, doc: TodosDocument) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write(path, self.serialize(doc))

    def parse(self, text: str) -> TodosDocument:
        lines = text.splitlines()
        tz = None
        items: list[TodosItem] = []
        item_by_id: dict[int, TodosItem] = {}

        current_category = "inbox"
        section = "tasks"
        in_archive = False
        stack: list[tuple[int, TodosItem]] = []

        for raw in lines:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("@timezone(") and stripped.endswith(")"):
                tz = stripped[len("@timezone(") : -1].strip() or None
                continue

            if stripped.startswith("## "):
                current_category = stripped[3:].strip()
                in_archive = current_category.lower() == "archive"
                section = "tasks"
                stack = []
                continue

            if stripped.startswith("### "):
                hdr = stripped[4:].strip().lower()
                section = "notes" if hdr == "notes" else "tasks"
                stack = []
                continue

            m = _ITEM_RE.match(line)
            if not m:
                continue

            indent = len(m.group(1).replace("\t", "    "))
            mark = m.group(2)
            body = m.group(3)
            id_match = _ID_RE.search(body)
            if not id_match:
                logger.warning("Skip todo line without #id: {}", body)
                continue
            item_id = int(id_match.group(1))

            archive_from = None
            if in_archive:
                m_from = _ARCHIVE_FROM_RE.search(body)
                if m_from:
                    archive_from = m_from.group(1).strip()
                    body = body[: m_from.start()].rstrip()

            meta = {k: v.strip() for k, v in _META_RE.findall(body)}
            extra_meta: list[str] = []
            for k, v in _META_RE.findall(body):
                if k not in {
                    "due",
                    "remind",
                    "repeat",
                    "priority",
                    "tag",
                    "created",
                    "done",
                    "reminded",
                }:
                    extra_meta.append(f"@{k}({v})")

            text_without_id = _ID_RE.sub("", body)
            text_without_meta = _META_RE.sub("", text_without_id).strip()

            item_type = "note" if mark == "📝" or section == "notes" else "task"
            status = "done" if mark.lower() == "[x]" else "pending"
            due_value = meta.get("due")
            if due_value and not _DUE_RE.match(due_value):
                extra_meta.append(f"@due({due_value})")
                due_value = None

            item = TodosItem(
                id=item_id,
                text=text_without_meta,
                type=item_type,
                status=status,
                category=(archive_from or current_category) if in_archive else current_category,
                priority=meta.get("priority") if meta.get("priority") in {"high", "medium", "low"} else None,
                due=due_value,
                remind=meta.get("remind"),
                repeat=meta.get("repeat") if meta.get("repeat") in {"daily", "weekly", "monthly", "yearly"} else None,
                tags=[v.strip().lower() for k, v in _META_RE.findall(body) if k == "tag" and v.strip()],
                created_at=meta.get("created", ""),
                done_at=meta.get("done"),
                reminded_at=meta.get("reminded"),
                archived_from=archive_from,
                extra_meta=extra_meta,
            )

            while stack and indent <= stack[-1][0]:
                stack.pop()
            if stack:
                parent = stack[-1][1]
                item.parent_id = parent.id
                parent.children.append(item)

            stack.append((indent, item))
            items.append(item)
            item_by_id[item.id] = item

        for item in items:
            if item.parent_id and item.parent_id not in item_by_id:
                item.parent_id = None

        return TodosDocument(timezone=tz, items=items)

    def serialize(self, doc: TodosDocument) -> str:
        out: list[str] = ["# Todos"]
        if doc.timezone:
            out.append(f"@timezone({doc.timezone})")
        out.append("")

        pending = [x for x in doc.items if x.status == "pending"]
        done = [x for x in doc.items if x.status == "done"]

        categories = sorted({x.category for x in pending} | {"inbox"})
        roots_pending = [x for x in pending if not x.parent_id]
        roots_done = [x for x in done if not x.parent_id]

        for idx, cat in enumerate(categories):
            if idx > 0:
                out.extend(["", "---", ""])
            out.append(f"## {cat}")
            tasks = [x for x in roots_pending if x.category == cat and x.type == "task"]
            notes = [x for x in roots_pending if x.category == cat and x.type == "note"]

            out.extend(["", "### Tasks"])
            if tasks:
                for item in sorted(tasks, key=lambda i: i.id):
                    self._emit_item(out, item, 0)
            out.extend(["", "### Notes"])
            if notes:
                for item in sorted(notes, key=lambda i: i.id):
                    self._emit_item(out, item, 0)

        out.extend(["", "---", "", "## Archive", ""])
        for item in sorted(roots_done, key=lambda i: i.id):
            self._emit_item(out, item, 0, archive=True)

        out.append("")
        return "\n".join(out)

    def _emit_item(self, out: list[str], item: TodosItem, level: int, archive: bool = False) -> None:
        indent = "  " * level
        mark = "📝" if item.type == "note" else ("[x]" if item.status == "done" else "[ ]")
        parts = [f"{indent}- {mark} {item.text} #{item.id}"]
        if item.due:
            parts.append(f"@due({item.due})")
        if item.remind:
            parts.append(f"@remind({item.remind})")
        if item.repeat:
            parts.append(f"@repeat({item.repeat})")
        if item.priority:
            parts.append(f"@priority({item.priority})")
        for tag in item.tags:
            parts.append(f"@tag({tag})")
        if item.created_at and _DATETIME_RE.match(item.created_at):
            parts.append(f"@created({item.created_at})")
        if item.done_at and _DATETIME_RE.match(item.done_at):
            parts.append(f"@done({item.done_at})")
        if item.reminded_at and _DATETIME_RE.match(item.reminded_at):
            parts.append(f"@reminded({item.reminded_at})")
        parts.extend(item.extra_meta)
        if archive:
            parts.append(f"[{item.archived_from or item.category}]")
        out.append(" ".join(parts))

        for child in sorted(item.children, key=lambda i: i.id):
            self._emit_item(out, child, level + 1, archive=archive)

    @staticmethod
    def next_id(doc: TodosDocument) -> int:
        all_ids = [x.id for x in doc.items]
        return (max(all_ids) + 1) if all_ids else 1

    @staticmethod
    def atomic_write(path: Path, content: str) -> None:
        tmp = path.parent / f".{path.name}.tmp"
        tmp.write_text(content, encoding="utf-8")

        for i in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 2:
                    raise
                time.sleep(0.1)

        # fallback cleanup
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    @staticmethod
    def now_str(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M")
