"""Todos reminder polling service."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from nanobot.todos.service import TodosService
from nanobot.todos.store import TodosStore


class TodosReminderService:
    """Scan todo files and deliver due reminders once."""

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
        logger.info("Todos reminder service started ({}s)", self.interval_s)

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
                logger.error("Todos reminder tick error: {}", e)

    async def tick(self) -> None:
        for path in self.store.list_todo_files():
            scope = self.store.path_to_scope(path)
            if not scope:
                continue
            channel, chat_id = scope
            doc = self.store.load_by_path(path)
            tz = self.service.resolve_timezone(doc)
            now = datetime.now(tz)
            changed = False

            for item in doc.items:
                if item.status != "pending" or not item.due or not item.remind or item.reminded_at:
                    continue
                due_dt = self.service.parse_due(item.due, tz)
                remind_delta = self.service.parse_remind(item.remind)
                if not due_dt or not remind_delta:
                    continue
                if now < due_dt - remind_delta:
                    continue

                content = f"⏰ Reminder: #{item.id} {item.text} @due({item.due})"
                await self.on_notify(channel, chat_id, content)
                item.reminded_at = self.store.now_str(now)
                changed = True

            if changed:
                self.store.save_by_path(path, doc)
