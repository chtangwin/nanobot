import asyncio
import json

import pytest

import nanobot.remote.remote_server as remote_server


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
