"""Todos report generation and scheduled delivery service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from loguru import logger

from nanobot.todos.service import TodosService
from nanobot.todos.store import TodosStore
from nanobot.todos.types import ReportSubscription, ReportSubscriptionStore, TodosItem

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class TodosReportService:
    """Generate daily/weekly report and process subscriptions."""

    def __init__(
        self,
        workspace: Path,
        interval_s: int,
        on_notify: Callable[[str, str, str], Awaitable[None]],
        config,
    ):
        self.workspace = Path(workspace)
        self.interval_s = interval_s
        self.on_notify = on_notify
        self.config = config
        self.store = TodosStore(self.workspace)
        self.service = TodosService(
            self.store,
            default_timezone=getattr(config, "default_timezone", ""),
            default_alert_channels=getattr(config, "default_alert_channels", ["chat"]),
        )
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Todos report service started ({}s)", self.interval_s)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Todos report tick error: {}", e)

    async def tick(self) -> None:
        for sub_file in sorted((self.workspace / "todos").glob("*/*/report_subscriptions.json")):
            scope = self.store.path_to_scope(sub_file.parent / "TODOS.md")
            if not scope:
                continue
            channel, chat_id = scope
            data = self._load_subscriptions_file(sub_file)
            changed = False
            for sub in data.subscriptions:
                if self._should_send(sub):
                    report = self.generate_report(channel, chat_id, sub.cadence)
                    await self.on_notify(channel, chat_id, report)
                    sub.last_sent_date = datetime.now(ZoneInfo(sub.tz)).strftime("%Y-%m-%d")
                    changed = True
            if changed:
                self._save_subscriptions_file(sub_file, data)

    def generate_report(self, channel: str, chat_id: str, period: str) -> str:
        doc = self.service.load(channel, chat_id)
        tz = self.service.resolve_timezone(doc)
        now = datetime.now(tz)
        if period == "daily":
            return self._daily_report(doc.items, now, tz)
        return self._weekly_report(doc.items, now, tz)

    def add_subscription(
        self,
        channel: str,
        chat_id: str,
        cadence: str,
        time_value: str,
        tz_value: str,
        weekday: str | None,
    ) -> ReportSubscription:
        path = self._sub_path(channel, chat_id)
        data = self._load_subscriptions_file(path)

        sub = ReportSubscription(
            id=f"{cadence}-{data.next_id}",
            cadence=cadence,
            time=time_value,
            tz=tz_value,
            weekday=weekday,
            created_at=datetime.now(ZoneInfo(tz_value)).strftime("%Y-%m-%d %H:%M"),
        )
        data.next_id += 1
        data.subscriptions.append(sub)
        self._save_subscriptions_file(path, data)
        return sub

    def remove_subscription(self, channel: str, chat_id: str, subscription_id: str) -> bool:
        path = self._sub_path(channel, chat_id)
        data = self._load_subscriptions_file(path)
        before = len(data.subscriptions)
        data.subscriptions = [s for s in data.subscriptions if s.id != subscription_id]
        if len(data.subscriptions) == before:
            return False
        self._save_subscriptions_file(path, data)
        return True

    def list_subscriptions(self, channel: str, chat_id: str) -> list[ReportSubscription]:
        return self._load_subscriptions_file(self._sub_path(channel, chat_id)).subscriptions

    def _sub_path(self, channel: str, chat_id: str) -> Path:
        return self.workspace / "todos" / channel / chat_id / "report_subscriptions.json"

    def _load_subscriptions_file(self, path: Path) -> ReportSubscriptionStore:
        if not path.exists():
            return ReportSubscriptionStore()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ReportSubscriptionStore()

        subs: list[ReportSubscription] = []
        for raw in data.get("subscriptions", []):
            subs.append(
                ReportSubscription(
                    id=raw.get("id", ""),
                    cadence=raw.get("cadence", "daily"),
                    time=raw.get("time", "21:00"),
                    tz=raw.get("tz", self.service.system_timezone()),
                    weekday=raw.get("weekday"),
                    created_at=raw.get("created_at", ""),
                    last_sent_date=raw.get("last_sent_date"),
                )
            )
        return ReportSubscriptionStore(subscriptions=subs, next_id=int(data.get("next_id", 1)))

    def _save_subscriptions_file(self, path: Path, data: ReportSubscriptionStore) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "subscriptions": [asdict(s) for s in data.subscriptions],
            "next_id": data.next_id,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _should_send(self, sub: ReportSubscription) -> bool:
        now = datetime.now(ZoneInfo(sub.tz))
        today = now.strftime("%Y-%m-%d")
        if sub.last_sent_date == today:
            return False

        hh, mm = [int(x) for x in sub.time.split(":", 1)]
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < due or now > due + timedelta(minutes=1):
            return False

        if sub.cadence == "weekly":
            if WEEKDAY_MAP.get(sub.weekday or "sun", 6) != now.weekday():
                return False

        return True

    def _daily_report(self, items: list[TodosItem], now: datetime, tz: ZoneInfo) -> str:
        today = now.date()
        tomorrow = today + timedelta(days=1)
        week_end = today + timedelta(days=(6 - today.weekday()))

        pending = [x for x in items if x.status == "pending"]
        done = [x for x in items if x.status == "done"]

        def due_date(item: TodosItem):
            dt = self.service.parse_due(item.due, tz)
            return dt.date() if dt else None

        today_remaining = [x for x in pending if due_date(x) == today]
        today_completed = [x for x in done if (x.done_at or "").startswith(str(today))]
        today_overdue = [x for x in pending if (self.service.parse_due(x.due, tz) or now + timedelta(days=9999)) < now]
        tomorrow_planned = [x for x in pending if due_date(x) == tomorrow]
        week_open = [x for x in pending if (d := due_date(x)) and today <= d <= week_end]

        today_added = [x for x in items if (x.created_at or "").startswith(str(today))]
        completed_n = len(today_completed)
        completion_rate = int((completed_n / max(1, completed_n + len(today_remaining))) * 100)

        suggestion = "处理逾期任务"
        if not today_overdue:
            highs = [x for x in pending if x.priority == "high"]
            suggestion = "优先推进高优先级任务" if highs else "按最早到期顺序推进"

        lines = [
            f"# 📅 Todos Daily Report ({today})",
            "",
            "## 1) Today",
            f"- Remaining: {len(today_remaining)}",
            f"- Completed: {len(today_completed)}",
            f"- Overdue: {len(today_overdue)}",
            "",
            "### Today Priority List",
        ]
        lines.extend(self._render_items(today_overdue + today_remaining))
        lines.extend([
            "",
            "## 2) Tomorrow",
            f"- Planned: {len(tomorrow_planned)}",
            f"- High Priority: {len([x for x in tomorrow_planned if x.priority == 'high'])}",
            "",
            "### Tomorrow Key Tasks",
        ])
        lines.extend(self._render_items(tomorrow_planned))
        lines.extend([
            "",
            "## 3) This Week",
            f"- Week Open Tasks: {len(week_open)}",
            f"- Week High Priority Open: {len([x for x in week_open if x.priority == 'high'])}",
            "",
            "### This Week Focus",
        ])
        lines.extend(self._render_items(week_open))
        lines.extend([
            "",
            "## 4) Summary",
            f"- Added Today: {len(today_added)}",
            f"- Daily Completion Rate: {completion_rate}%",
            f"- Suggested Next Action: {suggestion}",
        ])
        return "\n".join(lines)

    def _weekly_report(self, items: list[TodosItem], now: datetime, tz: ZoneInfo) -> str:
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        def in_week(s: str) -> bool:
            if not s:
                return False
            try:
                d = datetime.strptime(s[:10], "%Y-%m-%d").date()
            except ValueError:
                return False
            return week_start <= d <= week_end

        week_added = [x for x in items if in_week(x.created_at)]
        week_done = [x for x in items if in_week(x.done_at or "")]
        pending = [x for x in items if x.status == "pending"]
        overdue_open = [x for x in pending if (self.service.parse_due(x.due, tz) or now + timedelta(days=3650)) < now]

        by_cat: dict[str, int] = {}
        for item in pending:
            by_cat[item.category] = by_cat.get(item.category, 0) + 1
        top_cats = sorted(by_cat.items(), key=lambda x: (-x[1], x[0]))[:10]
        high_open = [x for x in pending if x.priority == "high"]

        completion_rate = int((len(week_done) / max(1, len(week_added))) * 100)
        week_range = f"{week_start} ~ {week_end}"

        lines = [
            f"# 🗓️ Todos Weekly Report ({week_range})",
            "",
            "## 1) Weekly KPI",
            f"- Added: {len(week_added)}",
            f"- Completed: {len(week_done)}",
            f"- Completion Rate: {completion_rate}%",
            f"- Overdue Remaining: {len(overdue_open)}",
            "",
            "## 2) Category Breakdown",
        ]
        if top_cats:
            lines.extend([f"- {k}: {v}" for k, v in top_cats])
        else:
            lines.append("- -: 0")

        lines.extend(["", "## 3) High Priority Open"])
        lines.extend(self._render_items(high_open))

        top3 = self._render_items(overdue_open[:3] or high_open[:3])
        while len(top3) < 3:
            top3.append(f"{len(top3) + 1}. -")

        lines.extend([
            "",
            "## 4) Next Week Plan",
            "- Top 3 Must-Do:",
            f"  1. {top3[0].lstrip('- ').strip() if top3 else '-'}",
            f"  2. {top3[1].lstrip('- ').strip() if len(top3) > 1 else '-'}",
            f"  3. {top3[2].lstrip('- ').strip() if len(top3) > 2 else '-'}",
        ])
        return "\n".join(lines)

    @staticmethod
    def _render_items(items: list[TodosItem]) -> list[str]:
        if not items:
            return ["- -"]
        out: list[str] = []
        for item in items[:10]:
            due = item.due or "-"
            priority = item.priority or "-"
            out.append(f"- #{item.id} {item.text} @due({due}) @priority({priority})")
        return out
