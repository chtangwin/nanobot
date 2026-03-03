from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from nanobot.todos.reminder_service import TodosReminderService
from nanobot.todos.report_service import TodosReportService
from nanobot.todos.service import TodosService
from nanobot.todos.store import TodosStore
from nanobot.todos.tool import TodosTool


class TestTodosStore:
    def test_parse_and_serialize(self, tmp_path):
        store = TodosStore(tmp_path)
        text = """# Todos
@timezone(Asia/Shanghai)

## inbox

### Tasks
- [ ] 提交PR #1 @due(2026-03-03 10:00) @priority(high) @tag(work) @created(2026-03-02 09:00)

### Notes
- 📝 会议纪要 #2 @tag(ref) @created(2026-03-02 10:00)

---

## Archive

- [x] 已完成 #3 @created(2026-03-01 08:00) @done(2026-03-02 11:00) [inbox]
"""
        doc = store.parse(text)
        assert doc.timezone == "Asia/Shanghai"
        assert len(doc.items) == 3
        assert store.next_id(doc) == 4

        out = store.serialize(doc)
        assert "# Todos" in out
        assert "## Archive" in out
        assert "#3" in out


class TestTodosService:
    def test_add_done_undone_query(self, tmp_path):
        store = TodosStore(tmp_path)
        service = TodosService(store, default_timezone="Asia/Shanghai")

        a = service.add("telegram", "123", text="写测试", due="2026-03-03 09:00", tags=["Work", "work"])
        assert a.id == 1
        assert a.tags == ["work"]

        done_item, repeated = service.done("telegram", "123", 1)
        assert done_item.status == "done"
        assert repeated is None

        restored = service.undone("telegram", "123", 1)
        assert restored.status == "pending"

        items, _ = service.query("telegram", "123", status="pending")
        assert len(items) == 1
        assert items[0].id == 1

    def test_repeat_create_next(self, tmp_path):
        store = TodosStore(tmp_path)
        service = TodosService(store, default_timezone="Asia/Shanghai")

        item = service.add("slack", "c1", text="周报", due="2026-03-03", repeat="weekly")
        _, repeated = service.done("slack", "c1", item.id)

        assert repeated is not None
        assert repeated.id == 2
        assert repeated.repeat == "weekly"


class TestTodosTool:
    @pytest.mark.asyncio
    async def test_tool_actions(self, tmp_path):
        cfg = SimpleNamespace(
            default_timezone="Asia/Shanghai",
            default_alert_channels=["chat"],
            report_tick_interval_s=60,
            default_daily_report_time="21:00",
            default_weekly_weekday="sun",
            default_weekly_report_time="20:00",
        )
        tool = TodosTool(workspace=tmp_path, config=cfg)
        tool.set_context("telegram", "u1")

        r1 = await tool.execute(action="add", text="买牛奶", category="shopping")
        assert r1.startswith("Added")

        r2 = await tool.execute(action="query", category="shopping")
        assert "Query: 1 items found" in r2

        r3 = await tool.execute(action="done", id=1)
        assert "Marked #1 as done" in r3

        r4 = await tool.execute(action="report", period="daily")
        assert "Todos Daily Report" in r4


class TestTodosReminderService:
    @pytest.mark.asyncio
    async def test_reminder_tick_once(self, tmp_path):
        store = TodosStore(tmp_path)
        service = TodosService(store, default_timezone="Asia/Shanghai")
        service.add(
            "telegram",
            "u2",
            text="即将到期",
            due=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M"),
            remind="1m",
        )

        sent: list[str] = []

        async def _notify(_channel: str, _chat_id: str, content: str):
            sent.append(content)

        cfg = SimpleNamespace(default_timezone="Asia/Shanghai", default_alert_channels=["chat"])
        reminder = TodosReminderService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)

        await reminder.tick()
        await reminder.tick()

        assert len(sent) == 1
        doc = store.load("telegram", "u2")
        assert doc.items[0].reminded_at is not None


class TestTodosReportService:
    def test_subscription_and_report(self, tmp_path):
        cfg = SimpleNamespace(default_timezone="Asia/Shanghai", default_alert_channels=["chat"])

        async def _notify(_channel: str, _chat_id: str, _content: str):
            return

        report = TodosReportService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)
        report.service.add("telegram", "u3", text="任务A", due="2026-03-03", priority="high")

        sub = report.add_subscription("telegram", "u3", "daily", "21:00", "Asia/Shanghai", None)
        assert sub.id == "daily-1"

        all_sub = report.list_subscriptions("telegram", "u3")
        assert len(all_sub) == 1

        txt = report.generate_report("telegram", "u3", "weekly")
        assert "Todos Weekly Report" in txt

        ok = report.remove_subscription("telegram", "u3", "daily-1")
        assert ok is True

        path = tmp_path / "todos" / "telegram" / "u3" / "report_subscriptions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["next_id"] == 2
