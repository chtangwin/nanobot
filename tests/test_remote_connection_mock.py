import json
from collections import deque
from unittest.mock import AsyncMock

import pytest

from nanobot.remote.config import HostConfig, HostsConfig
from nanobot.remote.connection import RemoteHost
from nanobot.remote.manager import HostManager


class StubWebSocket:
    def __init__(self, responses=None, fail_send_exc: Exception | None = None):
        self._responses = deque(responses or [])
        self.fail_send_exc = fail_send_exc
        self.sent = []
        self.closed = False

    async def send(self, payload: str):
        self.sent.append(json.loads(payload))
        if self.fail_send_exc is not None:
            exc = self.fail_send_exc
            self.fail_send_exc = None
            raise exc

    async def recv(self) -> str:
        if not self._responses:
            raise RuntimeError("No queued response")
        return self._responses.popleft()

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_rpc_auto_recovers_transport_without_setup_redeploy(monkeypatch):
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True

    ws1 = StubWebSocket(fail_send_exc=OSError("broken pipe"))
    ws2 = StubWebSocket(
        responses=[json.dumps({"type": "result", "success": True, "output": "ok"})]
    )
    host.websocket = ws1

    async def _recover_side_effect():
        host.websocket = ws2
        host._running = True
        host._authenticated = True
        return True

    host._recover_transport = AsyncMock(side_effect=_recover_side_effect)
    host.setup = AsyncMock(side_effect=AssertionError("setup() should not be called"))

    result = await host._rpc({"type": "exec", "command": "echo hi"}, timeout=1.0)

    assert result["success"] is True
    assert result["output"] == "ok"
    assert host._recover_transport.await_count == 1
    assert host.setup.await_count == 0
    assert ws1.sent[0]["request_id"] == ws2.sent[0]["request_id"]


@pytest.mark.asyncio
async def test_ensure_transport_ready_existing_session_uses_recover_not_setup():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = False
    host._authenticated = False
    host.websocket = None

    host._recover_transport = AsyncMock(return_value=True)
    host.setup = AsyncMock(side_effect=AssertionError("setup() should not be called"))

    ready = await host._ensure_transport_ready()

    assert ready is True
    assert host._recover_transport.await_count == 1
    assert host.setup.await_count == 0


@pytest.mark.asyncio
async def test_rpc_returns_error_when_auto_recover_fails(monkeypatch):
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True
    host.websocket = StubWebSocket(fail_send_exc=OSError("connection reset"))

    host._recover_transport = AsyncMock(return_value=False)
    host.setup = AsyncMock(side_effect=AssertionError("setup() should not be called"))

    result = await host._rpc({"type": "exec", "command": "echo hi"}, timeout=1.0)

    assert result["success"] is False
    assert "auto-reconnect failed" in result["error"]
    assert host._recover_transport.await_count == 1
    assert host.setup.await_count == 0


@pytest.mark.asyncio
async def test_host_manager_get_or_connect_returns_existing_object():
    hosts_cfg = HostsConfig()
    hosts_cfg.add_host(HostConfig(name="h1", ssh_host="u@host"))

    mgr = HostManager(hosts_cfg)
    existing = RemoteHost(hosts_cfg.get_host("h1"))
    existing._running = False
    existing._authenticated = False

    mgr._connections["h1"] = existing
    mgr.connect = AsyncMock(side_effect=AssertionError("connect() should not be called"))

    got = await mgr.get_or_connect("h1")

    assert got is existing
