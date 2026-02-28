"""Execution backend abstraction for local/remote operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExecutionBackend(ABC):
    """Abstract backend used by tools to perform operations."""

    @abstractmethod
    async def exec(self, command: str, working_dir: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
        pass

    @abstractmethod
    async def read_file(self, path: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def list_dir(self, path: str) -> dict[str, Any]:
        pass
