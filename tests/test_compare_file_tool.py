import pytest

from nanobot.agent.tools.filesystem import CompareFileTool


class FakeBackend:
    def __init__(self, text_map=None, bytes_map=None):
        self.text_map = text_map or {}
        self.bytes_map = bytes_map or {}

    async def exec(self, command: str, working_dir: str | None = None, timeout: float = 30.0):
        return {"success": False, "error": "not used"}

    async def read_file(self, path: str):
        if path not in self.text_map:
            return {"success": False, "error": f"File not found: {path}"}
        return {"success": True, "content": self.text_map[path]}

    async def write_file(self, path: str, content: str):
        return {"success": True}

    async def read_bytes(self, path: str):
        if path not in self.bytes_map:
            return {"success": False, "error": f"File not found: {path}"}
        return {"success": True, "content": self.bytes_map[path], "size": len(self.bytes_map[path])}

    async def edit_file(self, path: str, old_text: str, new_text: str):
        return {"success": True}

    async def list_dir(self, path: str):
        return {"success": True, "entries": []}


class FakeRouter:
    def __init__(self, local_backend, remote_backends):
        self.local_backend = local_backend
        self.remote_backends = remote_backends

    async def resolve(self, host=None):
        if not host:
            return self.local_backend
        if host not in self.remote_backends:
            raise KeyError(host)
        return self.remote_backends[host]


@pytest.mark.asyncio
async def test_compare_file_rejects_local_local():
    local = FakeBackend(bytes_map={"/a.txt": b"A", "/b.txt": b"A"})
    router = FakeRouter(local_backend=local, remote_backends={})
    tool = CompareFileTool(router)

    result = await tool.execute(left_path="/a.txt", right_path="/b.txt")

    assert "local<->local compare is not supported" in result


@pytest.mark.asyncio
async def test_compare_file_remote_remote_text_diff():
    local = FakeBackend()
    remote_a = FakeBackend(bytes_map={"/conf.txt": b"hello\nworld\n"})
    remote_b = FakeBackend(bytes_map={"/conf.txt": b"hello\nWORLD\n"})
    router = FakeRouter(local_backend=local, remote_backends={"a": remote_a, "b": remote_b})
    tool = CompareFileTool(router)

    result = await tool.execute(
        left_path="/conf.txt",
        left_host="a",
        right_path="/conf.txt",
        right_host="b",
    )

    assert result.startswith("Text files differ:")
    assert "--- a:/conf.txt" in result
    assert "+++ b:/conf.txt" in result


@pytest.mark.asyncio
async def test_compare_file_binary_uses_checksum_match():
    local = FakeBackend(bytes_map={"/pkg.bin": b"\x00\x01\x02"})
    remote = FakeBackend(bytes_map={"/pkg.bin": b"\x00\x01\x02"})
    router = FakeRouter(local_backend=local, remote_backends={"prod": remote})
    tool = CompareFileTool(router)

    result = await tool.execute(
        left_path="/pkg.bin",
        right_path="/pkg.bin",
        right_host="prod",
    )

    assert "Binary files are identical" in result
    assert "sha256:" in result


@pytest.mark.asyncio
async def test_compare_file_legacy_params_supported():
    local = FakeBackend(bytes_map={"/local.txt": b"same"})
    remote = FakeBackend(bytes_map={"/remote.txt": b"same"})
    router = FakeRouter(local_backend=local, remote_backends={"h1": remote})
    tool = CompareFileTool(router)

    result = await tool.execute(local_path="/local.txt", remote_path="/remote.txt", host="h1")

    assert "Text files are identical" in result
