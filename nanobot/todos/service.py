"""Business service for todos CRUD/query/report data helpers."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nanobot.todos.store import TodosStore
from nanobot.todos.types import TodosDocument, TodosItem

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2})?$")
_REMIND_RE = re.compile(r"^\d+[hmd]$")


class TodosService:
    """Core todo operations."""

    def __init__(self, store: TodosStore, default_timezone: str = "", default_alert_channels: list[str] | None = None):
        self.store = store
        self.default_timezone = default_timezone
        self.default_alert_channels = default_alert_channels or ["chat"]

    def load(self, channel: str, chat_id: str) -> TodosDocument:
        doc = self.store.load(channel, chat_id)
        if not doc.timezone:
            doc.timezone = self.default_timezone or None
        return doc

    def save(self, channel: str, chat_id: str, doc: TodosDocument) -> None:
        if not doc.timezone:
            doc.timezone = self.default_timezone or self.system_timezone()
        self.store.save(channel, chat_id, doc)

    def add(self, channel: str, chat_id: str, **kwargs) -> TodosItem:
        doc = self.load(channel, chat_id)
        tz = self.resolve_timezone(doc, kwargs.get("tz"))
        now = datetime.now(tz)

        item = TodosItem(
            id=self.store.next_id(doc),
            text=kwargs["text"].strip(),
            type=kwargs.get("type", "task"),
            status="pending",
            category=(kwargs.get("category") or "inbox").strip() or "inbox",
            priority=kwargs.get("priority"),
            due=kwargs.get("due"),
            remind=kwargs.get("remind"),
            repeat=kwargs.get("repeat"),
            tags=self.normalize_tags(kwargs.get("tags") or []),
            parent_id=kwargs.get("parent_id"),
            created_at=self.store.now_str(now),
            alert_channels=kwargs.get("alert_channels") or list(self.default_alert_channels),
            escalation_after=kwargs.get("escalation_after"),
        )

        if item.parent_id:
            parent = self.find_item(doc, item.parent_id)
            if parent:
                item.category = parent.category
                parent.children.append(item)

        doc.items.append(item)
        self.save(channel, chat_id, doc)
        return item

    def done(self, channel: str, chat_id: str, item_id: int) -> tuple[TodosItem, TodosItem | None]:
        doc = self.load(channel, chat_id)
        item = self.find_item(doc, item_id)
        if not item:
            raise ValueError(f"Todo #{item_id} not found")

        tz = self.resolve_timezone(doc)
        now = datetime.now(tz)

        original_category = item.category
        self._mark_done_recursive(item, now)
        item.archived_from = original_category

        new_item = None
        if item.repeat:
            new_item = self._create_repeat_item(doc, item, now)

        self.save(channel, chat_id, doc)
        return item, new_item

    def undone(self, channel: str, chat_id: str, item_id: int) -> TodosItem:
        doc = self.load(channel, chat_id)
        item = self.find_item(doc, item_id)
        if not item:
            raise ValueError(f"Todo #{item_id} not found")

        target = item.archived_from or item.category or "inbox"
        self._mark_pending_recursive(item)
        item.category = target
        item.archived_from = None

        self.save(channel, chat_id, doc)
        return item

    def edit(self, channel: str, chat_id: str, item_id: int, **kwargs) -> TodosItem:
        doc = self.load(channel, chat_id)
        item = self.find_item(doc, item_id)
        if not item:
            raise ValueError(f"Todo #{item_id} not found")

        for key in ("text", "due", "remind", "repeat", "priority", "category"):
            if key in kwargs and kwargs[key] is not None:
                value = kwargs[key].strip() if isinstance(kwargs[key], str) else kwargs[key]
                setattr(item, key, value)

        if "tags" in kwargs and kwargs["tags"] is not None:
            item.tags = self.normalize_tags(kwargs["tags"])

        self.save(channel, chat_id, doc)
        return item

    def delete(self, channel: str, chat_id: str, item_id: int) -> int:
        doc = self.load(channel, chat_id)
        item = self.find_item(doc, item_id)
        if not item:
            raise ValueError(f"Todo #{item_id} not found")

        to_remove = self.collect_tree_ids(item)
        doc.items = [x for x in doc.items if x.id not in to_remove]
        for parent in doc.items:
            parent.children = [c for c in parent.children if c.id not in to_remove]

        self.save(channel, chat_id, doc)
        return len(to_remove)

    def bulk_done(self, channel: str, chat_id: str, ids: list[int] | None = None, category: str | None = None) -> int:
        doc = self.load(channel, chat_id)
        tz = self.resolve_timezone(doc)
        now = datetime.now(tz)
        targets = self._bulk_targets(doc, ids, category, pending_only=True)
        for item in targets:
            self._mark_done_recursive(item, now)
            item.archived_from = item.archived_from or item.category
        self.save(channel, chat_id, doc)
        return len(targets)

    def bulk_delete(self, channel: str, chat_id: str, ids: list[int] | None = None, category: str | None = None) -> int:
        doc = self.load(channel, chat_id)
        targets = self._bulk_targets(doc, ids, category, pending_only=False)
        remove_ids: set[int] = set()
        for item in targets:
            remove_ids.update(self.collect_tree_ids(item))
        doc.items = [x for x in doc.items if x.id not in remove_ids]
        for parent in doc.items:
            parent.children = [c for c in parent.children if c.id not in remove_ids]
        self.save(channel, chat_id, doc)
        return len(remove_ids)

    def bulk_move(self, channel: str, chat_id: str, target_category: str, ids: list[int] | None = None, category: str | None = None) -> int:
        doc = self.load(channel, chat_id)
        targets = self._bulk_targets(doc, ids, category, pending_only=False)
        for item in targets:
            item.category = target_category
            if item.status == "done":
                item.archived_from = target_category
        self.save(channel, chat_id, doc)
        return len(targets)

    def query(self, channel: str, chat_id: str, **kwargs) -> tuple[list[TodosItem], ZoneInfo]:
        doc = self.load(channel, chat_id)
        tz = self.resolve_timezone(doc)
        now = datetime.now(tz)
        include_archived = bool(kwargs.get("include_archived", False))

        items = list(doc.items)
        status = kwargs.get("status", "pending")
        if status != "all":
            items = [x for x in items if x.status == status]
        if not include_archived:
            items = [x for x in items if x.status != "done"]

        if kwargs.get("category"):
            items = [x for x in items if x.category == kwargs["category"]]
        if kwargs.get("priority"):
            items = [x for x in items if x.priority == kwargs["priority"]]
        if kwargs.get("type"):
            items = [x for x in items if x.type == kwargs["type"]]
        if kwargs.get("tags"):
            tags = set(self.normalize_tags(kwargs["tags"]))
            items = [x for x in items if tags.issubset(set(x.tags))]
        if kwargs.get("keyword"):
            kw = str(kwargs["keyword"]).lower()
            items = [x for x in items if kw in x.text.lower()]

        due_filter = kwargs.get("due")
        if due_filter:
            items = [x for x in items if self.match_due_filter(x, due_filter, now, tz)]

        items = sorted(items, key=lambda x: self.sort_key(x, now, tz))
        return items, tz

    def format_query(self, items: list[TodosItem]) -> str:
        if not items:
            return "Query: 0 items found"
        lines = [f"Query: {len(items)} items found"]
        for item in items:
            mark = "[x]" if item.status == "done" else "[ ]"
            if item.type == "note":
                mark = "📝"
            meta: list[str] = []
            if item.due:
                meta.append(f"@due({item.due})")
            if item.priority:
                meta.append(f"@priority({item.priority})")
            for tag in item.tags:
                meta.append(f"@tag({tag})")
            lines.append(f"- {mark} #{item.id} {item.text} {' '.join(meta)}".rstrip())
        return "\n".join(lines)

    def find_item(self, doc: TodosDocument, item_id: int) -> TodosItem | None:
        for item in doc.items:
            if item.id == item_id:
                return item
        return None

    def resolve_timezone(self, doc: TodosDocument, explicit_tz: str | None = None) -> ZoneInfo:
        tz_name = explicit_tz or doc.timezone or self.default_timezone or self.system_timezone()
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo(self.system_timezone())

    @staticmethod
    def system_timezone() -> str:
        return datetime.now().astimezone().tzinfo.key if hasattr(datetime.now().astimezone().tzinfo, "key") else "UTC"

    @staticmethod
    def normalize_tags(tags: list[str]) -> list[str]:
        out: list[str] = []
        for tag in tags:
            t = str(tag).strip().lower()
            if not t or len(t) > 32:
                continue
            if t not in out:
                out.append(t)
        return out

    @staticmethod
    def validate_time(value: str) -> bool:
        return bool(_TIME_RE.match(value))

    @staticmethod
    def validate_due(value: str) -> bool:
        return bool(_DUE_RE.match(value))

    @staticmethod
    def validate_remind(value: str) -> bool:
        return bool(_REMIND_RE.match(value))

    @staticmethod
    def parse_due(due: str | None, tz: ZoneInfo) -> datetime | None:
        if not due:
            return None
        try:
            if len(due) == 10:
                return datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=tz)
            return datetime.strptime(due, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            return None

    @staticmethod
    def parse_remind(remind: str | None) -> timedelta | None:
        if not remind or not _REMIND_RE.match(remind):
            return None
        n = int(remind[:-1])
        unit = remind[-1]
        if unit == "m":
            return timedelta(minutes=n)
        if unit == "h":
            return timedelta(hours=n)
        return timedelta(days=n)

    def match_due_filter(self, item: TodosItem, due_filter: str, now: datetime, tz: ZoneInfo) -> bool:
        due_dt = self.parse_due(item.due, tz)
        if due_filter == "today":
            return bool(due_dt and due_dt.date() == now.date())
        if due_filter == "tomorrow":
            return bool(due_dt and due_dt.date() == (now + timedelta(days=1)).date())
        if due_filter == "overdue":
            return bool(due_dt and due_dt < now and item.status == "pending")
        if due_filter.startswith("before:"):
            boundary = self.parse_due(due_filter.split(":", 1)[1], tz)
            return bool(due_dt and boundary and due_dt.date() <= boundary.date())
        return False

    def sort_key(self, item: TodosItem, now: datetime, tz: ZoneInfo) -> tuple:
        due = self.parse_due(item.due, tz)
        overdue_rank = 0 if due and due < now else 1
        due_rank = due or datetime.max.replace(tzinfo=tz)
        priority_rank = {"high": 0, "medium": 1, "low": 2}.get(item.priority or "", 3)
        return overdue_rank, due_rank, priority_rank, item.id

    def _mark_done_recursive(self, item: TodosItem, now: datetime) -> None:
        item.status = "done"
        item.done_at = self.store.now_str(now)
        for child in item.children:
            self._mark_done_recursive(child, now)

    def _mark_pending_recursive(self, item: TodosItem) -> None:
        item.status = "pending"
        item.done_at = None
        for child in item.children:
            self._mark_pending_recursive(child)

    def _create_repeat_item(self, doc: TodosDocument, item: TodosItem, now: datetime) -> TodosItem:
        tz = now.tzinfo
        base = self.parse_due(item.due, tz) or now
        if item.repeat == "daily":
            next_due = base + timedelta(days=1)
        elif item.repeat == "weekly":
            next_due = base + timedelta(days=7)
        elif item.repeat == "monthly":
            year = base.year + (1 if base.month == 12 else 0)
            month = 1 if base.month == 12 else base.month + 1
            day = min(base.day, calendar.monthrange(year, month)[1])
            next_due = base.replace(year=year, month=month, day=day)
        else:
            year = base.year + 1
            day = min(base.day, calendar.monthrange(year, base.month)[1])
            next_due = base.replace(year=year, day=day)

        new_item = TodosItem(
            id=self.store.next_id(doc),
            text=item.text,
            type=item.type,
            status="pending",
            category=item.archived_from or item.category,
            priority=item.priority,
            due=next_due.strftime("%Y-%m-%d %H:%M") if item.due and len(item.due) > 10 else next_due.strftime("%Y-%m-%d"),
            remind=item.remind,
            repeat=item.repeat,
            tags=list(item.tags),
            created_at=self.store.now_str(now),
            alert_channels=list(item.alert_channels),
            escalation_after=item.escalation_after,
        )
        doc.items.append(new_item)
        return new_item

    @staticmethod
    def collect_tree_ids(item: TodosItem) -> set[int]:
        ids = {item.id}
        for child in item.children:
            ids.update(TodosService.collect_tree_ids(child))
        return ids

    def _bulk_targets(self, doc: TodosDocument, ids: list[int] | None, category: str | None, pending_only: bool) -> list[TodosItem]:
        targets = doc.items
        if pending_only:
            targets = [x for x in targets if x.status == "pending"]
        if ids:
            idset = set(ids)
            targets = [x for x in targets if x.id in idset]
        elif category:
            targets = [x for x in targets if x.category == category]
        else:
            targets = []
        return [x for x in targets if not x.parent_id]

    def todos_path(self, channel: str, chat_id: str) -> Path:
        return self.store.todos_path(channel, chat_id)
