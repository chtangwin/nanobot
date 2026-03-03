"""Todos tool implementation."""

from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo

from nanobot.agent.tools.base import Tool
from nanobot.todos.report_service import TodosReportService
from nanobot.todos.service import TodosService
from nanobot.todos.store import TodosStore

_SUBSCRIPTION_ID_RE = re.compile(r"^(daily|weekly)-\d+$")
_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


class TodosTool(Tool):
    """Unified todos tool for CRUD, reminders and reports."""

    def __init__(self, workspace, config):
        self.store = TodosStore(workspace)
        self.service = TodosService(
            self.store,
            default_timezone=getattr(config, "default_timezone", ""),
            default_alert_channels=getattr(config, "default_alert_channels", ["chat"]),
        )
        self.report_service = TodosReportService(
            workspace=workspace,
            interval_s=getattr(config, "report_tick_interval_s", 60),
            on_notify=self._noop_notify,
            config=config,
        )
        self.config = config
        self._channel = ""
        self._chat_id = ""

    async def _noop_notify(self, _channel: str, _chat_id: str, _content: str) -> None:
        return

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "todos"

    @property
    def description(self) -> str:
        return (
            "Task manager for add/query/done/delete/edit/report/report subscriptions. "
            "Use this tool as the single entry for todo/note/reminder/report actions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "add", "query", "done", "undone", "edit", "delete",
                        "bulk_done", "bulk_delete", "bulk_move",
                        "report", "report_subscribe", "report_unsubscribe", "report_list",
                    ],
                },
                "id": {"type": "integer"},
                "ids": {"type": "array", "items": {"type": "integer"}},
                "text": {"type": "string"},
                "type": {"type": "string", "enum": ["task", "note"]},
                "category": {"type": "string"},
                "target_category": {"type": "string"},
                "due": {"type": "string"},
                "remind": {"type": "string"},
                "repeat": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
                "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "parent_id": {"type": "integer"},
                "keyword": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "done", "all"]},
                "include_archived": {"type": "boolean"},
                "period": {"type": "string", "enum": ["daily", "weekly"]},
                "cadence": {"type": "string", "enum": ["daily", "weekly"]},
                "time": {"type": "string"},
                "tz": {"type": "string"},
                "weekday": {"type": "string", "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
                "subscription_id": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"

        try:
            if action == "add":
                return self._add(**kwargs)
            if action == "query":
                return self._query(**kwargs)
            if action == "done":
                item_id = kwargs.get("id")
                if not isinstance(item_id, int) or item_id < 1:
                    return "Error: id is required for done"
                done_item, repeated = self.service.done(self._channel, self._chat_id, item_id)
                if repeated:
                    return f"Marked #{done_item.id} as done; created repeat #{repeated.id}"
                return f"Marked #{done_item.id} as done"
            if action == "undone":
                item_id = kwargs.get("id")
                if not isinstance(item_id, int) or item_id < 1:
                    return "Error: id is required for undone"
                item = self.service.undone(self._channel, self._chat_id, item_id)
                return f"Marked #{item.id} as pending"
            if action == "edit":
                return self._edit(**kwargs)
            if action == "delete":
                item_id = kwargs.get("id")
                if not isinstance(item_id, int) or item_id < 1:
                    return "Error: id is required for delete"
                removed = self.service.delete(self._channel, self._chat_id, item_id)
                return f"Deleted {removed} item(s)"
            if action == "bulk_done":
                count = self._bulk_done_or_delete(mode="done", **kwargs)
                return f"Bulk done: {count} item(s)"
            if action == "bulk_delete":
                count = self._bulk_done_or_delete(mode="delete", **kwargs)
                return f"Bulk delete: {count} item(s)"
            if action == "bulk_move":
                return self._bulk_move(**kwargs)
            if action == "report":
                period = kwargs.get("period")
                if period not in {"daily", "weekly"}:
                    return "Error: period is required and must be daily|weekly"
                return self.report_service.generate_report(self._channel, self._chat_id, period)
            if action == "report_subscribe":
                return self._report_subscribe(**kwargs)
            if action == "report_unsubscribe":
                sid = kwargs.get("subscription_id")
                if not sid:
                    return "Error: subscription_id is required"
                if not _SUBSCRIPTION_ID_RE.match(str(sid)):
                    return "Error: subscription_id format must be daily-N or weekly-N"
                ok = self.report_service.remove_subscription(self._channel, self._chat_id, sid)
                return f"Unsubscribed {sid}" if ok else f"Subscription {sid} not found"
            if action == "report_list":
                subs = self.report_service.list_subscriptions(self._channel, self._chat_id)
                if not subs:
                    return "No report subscriptions."
                lines = ["Report subscriptions:"]
                for s in subs:
                    lines.append(f"- {s.id}: {s.cadence} {s.time} {s.tz} {s.weekday or '-'}")
                return "\n".join(lines)
            return f"Error: unsupported action {action}"
        except ValueError as e:
            return f"Error: {e}"

    def _add(self, **kwargs: Any) -> str:
        text = (kwargs.get("text") or "").strip()
        if not text:
            return "Error: text is required for add"
        due = kwargs.get("due")
        remind = kwargs.get("remind")
        if due and not self.service.validate_due(due):
            return "Error: due must be YYYY-MM-DD or YYYY-MM-DD HH:MM"
        if remind and not self.service.validate_remind(remind):
            return "Error: remind must match ^\\d+[hmd]$"
        item = self.service.add(self._channel, self._chat_id, **kwargs)
        return f"Added {item.type} #{item.id} to {item.category}"

    def _query(self, **kwargs: Any) -> str:
        due = kwargs.get("due")
        allowed_due = {"today", "tomorrow", "overdue"}
        if due and not (due in allowed_due or str(due).startswith("before:")):
            return "Error: due filter must be today|tomorrow|overdue|before:YYYY-MM-DD"
        if isinstance(due, str) and due.startswith("before:"):
            date_part = due.split(":", 1)[1]
            if not self.service.validate_due(date_part) or len(date_part) != 10:
                return "Error: due filter must be today|tomorrow|overdue|before:YYYY-MM-DD"
        items, _ = self.service.query(self._channel, self._chat_id, **kwargs)
        return self.service.format_query(items)

    def _edit(self, **kwargs: Any) -> str:
        item_id = kwargs.get("id")
        if not isinstance(item_id, int) or item_id < 1:
            return "Error: id is required for edit"
        fields = ("text", "due", "remind", "repeat", "priority", "tags", "category")
        if not any(kwargs.get(f) is not None for f in fields):
            return "Error: edit requires at least one field"
        if kwargs.get("due") and not self.service.validate_due(kwargs["due"]):
            return "Error: due must be YYYY-MM-DD or YYYY-MM-DD HH:MM"
        if kwargs.get("remind") and not self.service.validate_remind(kwargs["remind"]):
            return "Error: remind must match ^\\d+[hmd]$"
        item = self.service.edit(self._channel, self._chat_id, item_id, **kwargs)
        return f"Updated #{item.id}"

    def _bulk_done_or_delete(self, mode: str, **kwargs: Any) -> int:
        ids = kwargs.get("ids")
        category = kwargs.get("category")
        if ids is not None:
            if not isinstance(ids, list) or any((not isinstance(i, int) or i < 1) for i in ids):
                raise ValueError("ids must be a list of positive integers")
        if not ids and not category:
            raise ValueError("ids or category is required")
        if mode == "done":
            return self.service.bulk_done(self._channel, self._chat_id, ids=ids, category=category)
        return self.service.bulk_delete(self._channel, self._chat_id, ids=ids, category=category)

    def _bulk_move(self, **kwargs: Any) -> str:
        ids = kwargs.get("ids")
        category = kwargs.get("category")
        target = (kwargs.get("target_category") or "").strip()
        if not target:
            return "Error: target_category is required"
        if not ids and not category:
            return "Error: ids or category is required"
        count = self.service.bulk_move(self._channel, self._chat_id, target, ids=ids, category=category)
        return f"Moved {count} item(s) to {target}"

    def _report_subscribe(self, **kwargs: Any) -> str:
        cadence = kwargs.get("cadence")
        if cadence not in {"daily", "weekly"}:
            return "Error: cadence is required and must be daily|weekly"

        default_time = (
            getattr(self.config, "default_daily_report_time", "21:00")
            if cadence == "daily"
            else getattr(self.config, "default_weekly_report_time", "20:00")
        )
        time_value = kwargs.get("time") or default_time
        if not self.service.validate_time(time_value):
            return "Error: time must match HH:MM"

        doc = self.service.load(self._channel, self._chat_id)
        tz_value = kwargs.get("tz") or doc.timezone or getattr(self.config, "default_timezone", "") or self.service.system_timezone()
        try:
            ZoneInfo(tz_value)
        except Exception:
            return f"Error: invalid timezone {tz_value}"

        weekday = kwargs.get("weekday")
        if cadence == "weekly" and not weekday:
            weekday = getattr(self.config, "default_weekly_weekday", "sun")
        if cadence == "weekly" and weekday not in _WEEKDAYS:
            return "Error: weekday must be mon|tue|wed|thu|fri|sat|sun"

        sub = self.report_service.add_subscription(
            self._channel,
            self._chat_id,
            cadence=cadence,
            time_value=time_value,
            tz_value=tz_value,
            weekday=weekday,
        )
        return f"Subscribed {sub.id}: {sub.cadence} {sub.time} {sub.tz} {sub.weekday or '-'}"
