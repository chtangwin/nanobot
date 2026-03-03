from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from nanobot.todos.reminder_service import TodosReminderService
from nanobot.todos.report_service import TodosReportService
from nanobot.todos.service import TodosService
from nanobot.todos.store import TodosStore
from nanobot.todos.tool import TodosTool
from nanobot.todos.types import ReportSubscription


@pytest.fixture
def cfg() -> SimpleNamespace:
    return SimpleNamespace(
        default_timezone="Asia/Shanghai",
        default_alert_channels=["chat"],
        report_tick_interval_s=60,
        default_daily_report_time="21:00",
        default_weekly_weekday="sun",
        default_weekly_report_time="20:00",
    )


class TestTodosStore:
    def test_parse_and_serialize_core_format(self, tmp_path: Path):
        store = TodosStore(tmp_path)
        text = """# Todos
@timezone(Asia/Shanghai)

## inbox

### Tasks
- [ ] 提交PR #1 @due(2026-03-03 10:00) @priority(high) @tag(work) @created(2026-03-02 09:00)
  - [ ] 合并分支 #2 @created(2026-03-02 10:00)

### Notes
- 📝 会议纪要 #3 @tag(ref) @created(2026-03-02 10:00)

---

## Archive

- [x] 已完成 #7 @created(2026-03-01 08:00) @done(2026-03-02 11:00) [inbox]
"""
        doc = store.parse(text)
        assert doc.timezone == "Asia/Shanghai"
        assert len(doc.items) == 4
        assert store.next_id(doc) == 8

        parent = next(x for x in doc.items if x.id == 1)
        child = next(x for x in doc.items if x.id == 2)
        assert child.parent_id == parent.id
        assert parent.children and parent.children[0].id == 2

        out = store.serialize(doc)
        assert "# Todos" in out
        assert "## Archive" in out
        assert "#7" in out
        assert "[inbox]" in out

    def test_parse_tolerant_invalid_due_unknown_meta_and_missing_id(self, tmp_path: Path):
        store = TodosStore(tmp_path)
        text = """# Todos
## inbox
### Tasks
- [ ] 无ID任务 @due(2026-03-03)
- [ ] 有坏日期 #1 @due(2026/03/03) @foo(bar)
"""
        doc = store.parse(text)
        assert len(doc.items) == 1
        item = doc.items[0]
        assert item.id == 1
        assert item.due is None
        assert "@due(2026/03/03)" in item.extra_meta
        assert "@foo(bar)" in item.extra_meta

    def test_atomic_write_retries_on_permission_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        store = TodosStore(tmp_path)
        target = tmp_path / "todos" / "telegram" / "u1" / "TODOS.md"
        target.parent.mkdir(parents=True, exist_ok=True)

        calls = {"n": 0}
        real_replace = __import__("os").replace

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("locked")
            return real_replace(src, dst)

        monkeypatch.setattr("nanobot.todos.store.os.replace", flaky_replace)
        store.atomic_write(target, "# Todos\n")

        assert calls["n"] == 3
        assert target.read_text(encoding="utf-8") == "# Todos\n"

    def test_path_scope_and_file_listing(self, tmp_path: Path):
        store = TodosStore(tmp_path)
        p1 = store.todos_path("telegram", "100")
        p2 = store.todos_path("slack", "C1")
        p1.parent.mkdir(parents=True, exist_ok=True)
        p2.parent.mkdir(parents=True, exist_ok=True)
        p1.write_text("# Todos\n", encoding="utf-8")
        p2.write_text("# Todos\n", encoding="utf-8")

        files = store.list_todo_files()
        assert len(files) == 2
        assert store.path_to_scope(p1) == ("telegram", "100")
        assert store.path_to_scope(tmp_path / "x" / "TODOS.md") is None


class TestTodosService:
    def test_add_note_and_parent_child(self, tmp_path: Path):
        service = TodosService(TodosStore(tmp_path), default_timezone="Asia/Shanghai")

        p = service.add("telegram", "123", text="发布 v1.2", category="project-x")
        c = service.add("telegram", "123", text="更新 changelog", parent_id=p.id)
        n = service.add("telegram", "123", text="客户偏好蓝色", type="note", category="client")

        assert p.id == 1
        assert c.parent_id == p.id
        assert c.category == "project-x"
        assert n.type == "note"

    def test_done_undone_repeat_and_children(self, tmp_path: Path):
        service = TodosService(TodosStore(tmp_path), default_timezone="Asia/Shanghai")

        parent = service.add("telegram", "200", text="每周周报", due="2026-03-03", repeat="weekly")
        child = service.add("telegram", "200", text="收集数据", parent_id=parent.id)

        done_item, repeated = service.done("telegram", "200", parent.id)
        assert done_item.status == "done"
        assert done_item.done_at is not None
        assert done_item.archived_from == "inbox"

        reloaded = service.load("telegram", "200")
        reloaded_child = next(x for x in reloaded.items if x.id == child.id)
        assert reloaded_child.status == "done"

        assert repeated is not None
        assert repeated.repeat == "weekly"
        assert repeated.id == 3

        restored = service.undone("telegram", "200", parent.id)
        assert restored.status == "pending"
        assert restored.done_at is None

    def test_delete_cascade_and_bulk_ops(self, tmp_path: Path):
        service = TodosService(TodosStore(tmp_path), default_timezone="Asia/Shanghai")

        p1 = service.add("telegram", "300", text="父任务", category="work")
        _child = service.add("telegram", "300", text="子任务", parent_id=p1.id)
        t2 = service.add("telegram", "300", text="买牛奶", category="shopping")
        t3 = service.add("telegram", "300", text="买面包", category="shopping")

        deleted = service.delete("telegram", "300", p1.id)
        assert deleted == 2

        moved = service.bulk_move("telegram", "300", target_category="life", category="shopping")
        assert moved == 2

        done_n = service.bulk_done("telegram", "300", category="life")
        assert done_n == 2

        removed = service.bulk_delete("telegram", "300", ids=[t2.id, t3.id])
        assert removed == 2

    def test_query_filters_cover_common_cases(self, tmp_path: Path):
        service = TodosService(TodosStore(tmp_path), default_timezone="Asia/Shanghai")
        tz = ZoneInfo("Asia/Shanghai")
        now = datetime.now(tz)

        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        a = service.add("telegram", "400", text="today high", due=today, priority="high", tags=["work", "urgent"], category="project-x")
        b = service.add("telegram", "400", text="tomorrow", due=tomorrow, tags=["work"])
        c = service.add("telegram", "400", text="old task", due=yesterday, category="legacy")
        n = service.add("telegram", "400", text="meeting notes", type="note", tags=["reference"])

        service.done("telegram", "400", b.id)

        items_today, _ = service.query("telegram", "400", due="today", status="pending")
        assert [x.id for x in items_today] == [a.id]

        items_overdue, _ = service.query("telegram", "400", due="overdue")
        overdue_ids = {x.id for x in items_overdue}
        assert c.id in overdue_ids

        items_cat, _ = service.query("telegram", "400", category="project-x")
        assert [x.id for x in items_cat] == [a.id]

        items_tags, _ = service.query("telegram", "400", tags=["work", "urgent"])
        assert [x.id for x in items_tags] == [a.id]

        items_kw, _ = service.query("telegram", "400", keyword="notes")
        assert [x.id for x in items_kw] == [n.id]

        items_note, _ = service.query("telegram", "400", type="note")
        assert [x.id for x in items_note] == [n.id]

        items_done_default, _ = service.query("telegram", "400", status="done")
        assert items_done_default == []  # include_archived 默认 false

        items_done_all, _ = service.query("telegram", "400", status="done", include_archived=True)
        assert len(items_done_all) == 1

        items_before, _ = service.query("telegram", "400", due=f"before:{tomorrow}", status="all", include_archived=True)
        assert {x.id for x in items_before} >= {a.id, b.id, c.id}


class TestTodosTool:
    @pytest.mark.asyncio
    async def test_tool_actions_cover_examples(self, tmp_path: Path, cfg: SimpleNamespace):
        tool = TodosTool(workspace=tmp_path, config=cfg)
        tool.set_context("telegram", "u1")

        assert "Added" in await tool.execute(action="add", text="买牛奶", category="shopping")
        assert "Added" in await tool.execute(action="add", text="周会纪要", type="note", category="work")
        assert "Added" in await tool.execute(action="add", text="提交周报", due="2026-03-03", repeat="weekly", priority="high", tags=["Work", "urgent", "work"])

        q1 = await tool.execute(action="query", category="shopping")
        assert "Query: 1 items found" in q1

        q2 = await tool.execute(action="query", type="note")
        assert "周会纪要" in q2

        d1 = await tool.execute(action="done", id=1)
        assert "Marked #1 as done" in d1

        e1 = await tool.execute(action="edit", id=2, text="周会纪要-更新", tags=["reference"])
        assert e1 == "Updated #2"

        u1 = await tool.execute(action="undone", id=1)
        assert u1 == "Marked #1 as pending"

        m1 = await tool.execute(action="bulk_move", category="shopping", target_category="life")
        assert "Moved" in m1

        bd = await tool.execute(action="bulk_done", category="life")
        assert "Bulk done" in bd

        rb = await tool.execute(action="report", period="daily")
        assert "Todos Daily Report" in rb

    @pytest.mark.asyncio
    async def test_tool_report_subscription_flow(self, tmp_path: Path, cfg: SimpleNamespace):
        tool = TodosTool(workspace=tmp_path, config=cfg)
        tool.set_context("telegram", "u2")

        r1 = await tool.execute(action="report_subscribe", cadence="daily")
        assert "Subscribed daily-1" in r1

        r2 = await tool.execute(action="report_subscribe", cadence="weekly", time="19:30", weekday="sun", tz="Asia/Shanghai")
        assert "Subscribed weekly-2" in r2

        ls = await tool.execute(action="report_list")
        assert "daily-1" in ls and "weekly-2" in ls

        rm = await tool.execute(action="report_unsubscribe", subscription_id="daily-1")
        assert rm == "Unsubscribed daily-1"

        rm2 = await tool.execute(action="report_unsubscribe", subscription_id="daily-9")
        assert "not found" in rm2

    @pytest.mark.asyncio
    async def test_tool_validation_errors(self, tmp_path: Path, cfg: SimpleNamespace):
        tool = TodosTool(workspace=tmp_path, config=cfg)

        no_ctx = await tool.execute(action="add", text="x")
        assert "no session context" in no_ctx

        tool.set_context("telegram", "u3")

        assert (await tool.execute(action="add", text="", due="2026-03-03")).startswith("Error: text")
        assert "due must be" in await tool.execute(action="add", text="x", due="2026/03/03")
        assert "remind must" in await tool.execute(action="add", text="x", remind="1w")

        assert "due filter" in await tool.execute(action="query", due="before:2026-03")
        assert "id is required" in await tool.execute(action="done", id=0)
        assert "edit requires" in await tool.execute(action="edit", id=1)
        assert "ids or category" in await tool.execute(action="bulk_done")
        assert "target_category is required" in await tool.execute(action="bulk_move", category="inbox")

        assert "period is required" in await tool.execute(action="report")
        assert "time must" in await tool.execute(action="report_subscribe", cadence="daily", time="25:00")
        assert "invalid timezone" in await tool.execute(action="report_subscribe", cadence="daily", tz="Mars/Olympus")
        assert "weekday must" in await tool.execute(action="report_subscribe", cadence="weekly", weekday="abc")
        assert "subscription_id format" in await tool.execute(action="report_unsubscribe", subscription_id="x-1")


class TestTodosReminderService:
    @pytest.mark.asyncio
    async def test_reminder_tick_once_and_skip_cases(self, tmp_path: Path, cfg: SimpleNamespace):
        store = TodosStore(tmp_path)
        service = TodosService(store, default_timezone="Asia/Shanghai")
        tz = ZoneInfo("Asia/Shanghai")

        due_now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        due_later = (datetime.now(tz) + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")

        a = service.add("telegram", "u4", text="应提醒", due=due_now, remind="1m")
        b = service.add("telegram", "u4", text="未到提醒窗口", due=due_later, remind="1h")
        c = service.add("telegram", "u4", text="坏 remind", due=due_now, remind="oops")
        d = service.add("telegram", "u4", text="将完成", due=due_now, remind="1m")
        service.done("telegram", "u4", d.id)

        sent: list[str] = []

        async def _notify(_channel: str, _chat_id: str, content: str):
            sent.append(content)

        reminder = TodosReminderService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)
        await reminder.tick()
        await reminder.tick()

        assert len(sent) == 1
        assert f"#{a.id}" in sent[0]
        assert f"#{b.id}" not in sent[0]
        assert f"#{c.id}" not in sent[0]

        doc = store.load("telegram", "u4")
        item_a = next(x for x in doc.items if x.id == a.id)
        assert item_a.reminded_at is not None

    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self, tmp_path: Path, cfg: SimpleNamespace):
        async def _notify(_channel: str, _chat_id: str, _content: str):
            return

        reminder = TodosReminderService(tmp_path, interval_s=9999, on_notify=_notify, config=cfg)
        await reminder.start()
        first = reminder._task
        await reminder.start()
        assert reminder._task is first
        reminder.stop()


class TestTodosReportService:
    @pytest.mark.asyncio
    async def test_subscription_and_reports(self, tmp_path: Path, cfg: SimpleNamespace):
        async def _notify(_channel: str, _chat_id: str, _content: str):
            return

        report = TodosReportService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)
        service = report.service
        tz = ZoneInfo("Asia/Shanghai")
        today = datetime.now(tz).strftime("%Y-%m-%d")

        t1 = service.add("telegram", "u5", text="任务A", due=today, priority="high", category="work")
        service.add("telegram", "u5", text="任务B", due=(datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d"), category="life")
        service.done("telegram", "u5", t1.id)

        sub1 = report.add_subscription("telegram", "u5", "daily", "21:00", "Asia/Shanghai", None)
        sub2 = report.add_subscription("telegram", "u5", "weekly", "20:00", "Asia/Shanghai", "sun")
        assert sub1.id == "daily-1"
        assert sub2.id == "weekly-2"

        listed = report.list_subscriptions("telegram", "u5")
        assert len(listed) == 2

        daily = report.generate_report("telegram", "u5", "daily")
        weekly = report.generate_report("telegram", "u5", "weekly")
        assert "Todos Daily Report" in daily
        assert "## 1) Today" in daily
        assert "## 2) Tomorrow" in daily
        assert "## 3) This Week" in daily
        assert "## 4) Summary" in daily
        assert "Todos Weekly Report" in weekly
        assert "## 1) Weekly KPI" in weekly

        assert report.remove_subscription("telegram", "u5", "daily-1") is True
        assert report.remove_subscription("telegram", "u5", "daily-1") is False

        data = json.loads((tmp_path / "todos" / "telegram" / "u5" / "report_subscriptions.json").read_text(encoding="utf-8"))
        assert data["next_id"] == 3

    def test_should_send_and_tick_dedup(self, tmp_path: Path, cfg: SimpleNamespace):
        sent: list[tuple[str, str, str]] = []

        async def _notify(channel: str, chat_id: str, content: str):
            sent.append((channel, chat_id, content))

        report = TodosReportService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)

        # _should_send：同日已发 -> False
        sub = ReportSubscription(
            id="daily-1",
            cadence="daily",
            time=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M"),
            tz="Asia/Shanghai",
            created_at="",
            last_sent_date=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"),
        )
        assert report._should_send(sub) is False

    @pytest.mark.asyncio
    async def test_tick_sends_once_when_due_now(self, tmp_path: Path, cfg: SimpleNamespace):
        sent: list[str] = []

        async def _notify(_channel: str, _chat_id: str, content: str):
            sent.append(content)

        report = TodosReportService(tmp_path, interval_s=60, on_notify=_notify, config=cfg)
        service = report.service
        service.add("telegram", "u6", text="任务", due=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))

        now_hm = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
        report.add_subscription("telegram", "u6", "daily", now_hm, "Asia/Shanghai", None)

        await report.tick()
        await report.tick()

        assert len(sent) == 1
        path = tmp_path / "todos" / "telegram" / "u6" / "report_subscriptions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["subscriptions"][0]["last_sent_date"] is not None
