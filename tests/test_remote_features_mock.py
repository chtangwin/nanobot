import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock

import pytest

import nanobot.remote.remote_server as remote_server
from nanobot.remote.config import HostConfig, HostsConfig
from nanobot.remote.connection import RemoteHost
from nanobot.remote.manager import HostManager


# =========================
# Client-side (RemoteHost)
# =========================

class StubClientWebSocket:
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
async def test_rpc_auto_recovers_transport_without_setup_redeploy():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True

    ws1 = StubClientWebSocket(fail_send_exc=OSError("broken pipe"))
    ws2 = StubClientWebSocket(
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
async def test_rpc_returns_error_when_auto_recover_fails():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True
    host.websocket = StubClientWebSocket(fail_send_exc=OSError("connection reset"))

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


@pytest.mark.asyncio
async def test_ensure_transport_ready_first_time_uses_setup():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = None
    host._running = False
    host._authenticated = False

    host.setup = AsyncMock(return_value="nanobot-new")
    host._recover_transport = AsyncMock(side_effect=AssertionError("recover should not be called"))

    ready = await host._ensure_transport_ready()

    assert ready is True
    assert host.setup.await_count == 1
    assert host._recover_transport.await_count == 0


@pytest.mark.asyncio
async def test_rpc_detects_mismatched_response_request_id():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True
    host.websocket = StubClientWebSocket(
        responses=[json.dumps({"type": "result", "request_id": "wrong-id", "success": True, "output": "ok"})]
    )

    result = await host._rpc({"type": "exec", "command": "echo hi", "request_id": "expected-id"}, timeout=1.0)

    assert result["success"] is False
    assert "Mismatched request_id" in result["error"]


@pytest.mark.asyncio
async def test_rpc_returns_timeout_error():
    class SlowWebSocket:
        async def send(self, payload: str):
            return None

        async def recv(self) -> str:
            await asyncio.sleep(0.2)
            return json.dumps({"type": "result", "success": True})

    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True
    host.websocket = SlowWebSocket()

    result = await host._rpc({"type": "exec", "command": "echo hi"}, timeout=0.01)

    assert result["success"] is False
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_read_bytes_invalid_base64_returns_structured_error():
    cfg = HostConfig(name="h1", ssh_host="u@host")
    host = RemoteHost(cfg)
    host.session_id = "nanobot-existing"
    host._running = True
    host._authenticated = True
    host.websocket = StubClientWebSocket(
        responses=[json.dumps({"type": "result", "success": True, "content_b64": "!!!not-base64!!!"})]
    )

    result = await host.read_bytes("/tmp/a.bin", timeout=1.0)

    assert result["success"] is False
    assert "Invalid base64 payload" in (result.get("error") or "")
    assert result["content"] is None


# =========================
# Server-side (remote_server)
# =========================

class FakeServerWebSocket:
    def __init__(self, messages: list[dict], auth_token: str = ""):
        self.remote_address = ("127.0.0.1", 12345)
        self._auth_payload = json.dumps({"token": auth_token})
        self._messages = [json.dumps(m) for m in messages]
        self._idx = 0
        self.sent: list[dict] = []
        self._auth_done = False

    async def recv(self):
        if self._auth_done:
            raise RuntimeError("recv() should only be used for auth message")
        self._auth_done = True
        return self._auth_payload

    async def send(self, payload: str):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._messages):
            raise StopAsyncIteration
        item = self._messages[self._idx]
        self._idx += 1
        return item


@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    remote_server._REQUEST_RESULTS.clear()
    remote_server._REQUEST_INFLIGHT.clear()
    remote_server._REQUEST_ORDER.clear()


@pytest.mark.asyncio
async def test_handle_connection_same_request_id_same_payload_returns_cached(monkeypatch):
    class FakeExecutor:
        calls = 0
        cleaned = 0

        def __init__(self, *args, **kwargs):
            pass

        async def exec(self, command: str):
            FakeExecutor.calls += 1
            return {
                "success": True,
                "output": f"run-{FakeExecutor.calls}",
                "error": None,
                "exit_code": 0,
            }

        def cleanup(self):
            FakeExecutor.cleaned += 1

    monkeypatch.setattr(remote_server, "CommandExecutor", FakeExecutor)

    req = {"request_id": "rid-1", "type": "exec", "command": "echo hi"}
    ws = FakeServerWebSocket(messages=[req, req])

    await remote_server.handle_connection(ws, auth_token="", use_tmux=False)

    assert FakeExecutor.calls == 1
    assert FakeExecutor.cleaned == 1
    assert ws.sent[0]["type"] == "authenticated"
    assert ws.sent[1]["type"] == "result"
    assert ws.sent[2]["type"] == "result"
    assert ws.sent[1] == ws.sent[2]


@pytest.mark.asyncio
async def test_handle_connection_same_request_id_different_payload_rejected(monkeypatch):
    class FakeExecutor:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        async def exec(self, command: str):
            FakeExecutor.calls += 1
            return {
                "success": True,
                "output": command,
                "error": None,
                "exit_code": 0,
            }

        def cleanup(self):
            pass

    monkeypatch.setattr(remote_server, "CommandExecutor", FakeExecutor)

    ws = FakeServerWebSocket(
        messages=[
            {"request_id": "rid-2", "type": "exec", "command": "echo A"},
            {"request_id": "rid-2", "type": "exec", "command": "echo B"},
        ]
    )

    await remote_server.handle_connection(ws, auth_token="", use_tmux=False)

    assert FakeExecutor.calls == 1
    assert ws.sent[1]["type"] == "result"
    assert ws.sent[2]["type"] == "error"
    assert "different payload" in ws.sent[2]["message"]


@pytest.mark.asyncio
async def test_handle_connection_inflight_dedupe_across_connections(monkeypatch):
    class SlowExecutor:
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        def __init__(self, *args, **kwargs):
            pass

        async def exec(self, command: str):
            SlowExecutor.calls += 1
            SlowExecutor.started.set()
            await SlowExecutor.release.wait()
            return {
                "success": True,
                "output": "shared-result",
                "error": None,
                "exit_code": 0,
            }

        def cleanup(self):
            pass

    monkeypatch.setattr(remote_server, "CommandExecutor", SlowExecutor)

    req = {"request_id": "rid-3", "type": "exec", "command": "echo inflight"}
    ws1 = FakeServerWebSocket(messages=[req])
    ws2 = FakeServerWebSocket(messages=[req])

    t1 = asyncio.create_task(remote_server.handle_connection(ws1, auth_token="", use_tmux=False))
    await asyncio.wait_for(SlowExecutor.started.wait(), timeout=1.0)

    t2 = asyncio.create_task(remote_server.handle_connection(ws2, auth_token="", use_tmux=False))
    await asyncio.sleep(0.05)
    SlowExecutor.release.set()

    await asyncio.gather(t1, t2)

    assert SlowExecutor.calls == 1
    assert ws1.sent[1]["type"] == "result"
    assert ws2.sent[1]["type"] == "result"
    assert ws1.sent[1]["output"] == "shared-result"
    assert ws2.sent[1]["output"] == "shared-result"


@pytest.mark.asyncio
async def test_handle_connection_auth_failure_returns_error_only():
    ws = FakeServerWebSocket(messages=[], auth_token="wrong-token")

    await remote_server.handle_connection(ws, auth_token="expected-token", use_tmux=False)

    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "error"
    assert "Authentication failed" in ws.sent[0]["message"]
