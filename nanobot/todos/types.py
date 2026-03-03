"""Data types for todos module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RepeatType = Literal["daily", "weekly", "monthly", "yearly"]
PriorityType = Literal["high", "medium", "low"]
ItemType = Literal["task", "note"]
StatusType = Literal["pending", "done"]


@dataclass
class TodosItem:
    """Single todo/note item."""

    id: int
    text: str
    type: ItemType
    status: StatusType
    category: str = "inbox"
    priority: PriorityType | None = None
    due: str | None = None
    remind: str | None = None
    repeat: RepeatType | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: int | None = None
    children: list["TodosItem"] = field(default_factory=list)
    created_at: str = ""
    done_at: str | None = None
    reminded_at: str | None = None
    alert_channels: list[str] = field(default_factory=lambda: ["chat"])
    escalation_after: str | None = None
    archived_from: str | None = None
    extra_meta: list[str] = field(default_factory=list)


@dataclass
class TodosDocument:
    """In-memory todo document."""

    timezone: str | None = None
    items: list[TodosItem] = field(default_factory=list)


@dataclass
class ReportSubscription:
    """Subscription metadata for scheduled reports."""

    id: str
    cadence: Literal["daily", "weekly"]
    time: str
    tz: str
    weekday: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] | None = None
    created_at: str = ""
    last_sent_date: str | None = None


@dataclass
class ReportSubscriptionStore:
    """Persistent report subscriptions."""

    subscriptions: list[ReportSubscription] = field(default_factory=list)
    next_id: int = 1
