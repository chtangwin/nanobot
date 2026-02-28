import pytest

from nanobot.agent.tools.filesystem import CompareDirTool


class FakeBackend:
    def __init__(self, tree=None, texts=None, bytes_map=None):
        self.tree = tree or {}
        self.texts = texts or {}
        self.bytes_map = bytes_map or {}

    async def exec(self, command: str, working_dir: str | None = None, timeout: float = 30.0):
        return {"success": False, "error": "not used"}

    async def list_dir(self, path: str):
        if path not in self.tree:
            return {"success": False, "error": f"Directory not found: {path}"}
        return {"success": True, "entries": self.tree[path]}

    async def read_file(self, path: str):
        if path not in self.texts:
            return {"success": False, "error": f"File not found: {path}"}
        return {"success": True, "content": self.texts[path]}

    async def write_file(self, path: str, content: str):
        return {"success": True}

    async def read_bytes(self, path: str):
        if path not in self.bytes_map:
            return {"success": False, "error": f"File not found: {path}"}
        data = self.bytes_map[path]
        return {"success": True, "content": data, "size": len(data)}

    async def edit_file(self, path: str, old_text: str, new_text: str):
        return {"success": True}


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
async def test_compare_dir_rejects_local_local():
    local = FakeBackend(tree={"/a": [], "/b": []})
    router = FakeRouter(local_backend=local, remote_backends={})
    tool = CompareDirTool(router)

    result = await tool.execute(left_path="/a", right_path="/b")

    assert "local<->local compare is not supported" in result


@pytest.mark.asyncio
async def test_compare_dir_structure_summary_and_ignore_note():
    left = FakeBackend(
        tree={
            "/left": [
                {"name": "same.txt", "is_dir": False},
                {"name": "only_left.txt", "is_dir": False},
                {"name": "node_modules", "is_dir": True},
            ],
            "/left/node_modules": [{"name": "lib.js", "is_dir": False}],
        },
        texts={"/left/.gitignore": "node_modules/\n"},
    )
    right = FakeBackend(
        tree={
            "/right": [
                {"name": "same.txt", "is_dir": False},
                {"name": "only_right.txt", "is_dir": False},
            ]
        }
    )

    router = FakeRouter(local_backend=FakeBackend(), remote_backends={"l": left, "r": right})
    tool = CompareDirTool(router)

    result = await tool.execute(left_host="l", left_path="/left", right_host="r", right_path="/right")

    assert "Directory comparison summary" in result
    assert "- only in left: 1" in result
    assert "- only in right: 1" in result
    assert "only_left.txt" in result
    assert "only_right.txt" in result
    assert "🧹 Ignore rules:" in result
    assert "- Left  (.gitignore + defaults):" in result
    assert "- Right (defaults):" in result
    assert "Asymmetric ignore rules applied" in result


@pytest.mark.asyncio
async def test_compare_dir_aborts_when_entry_limit_exceeded():
    left = FakeBackend(
        tree={
            "/left": [
                {"name": "a.txt", "is_dir": False},
                {"name": "b.txt", "is_dir": False},
                {"name": "c.txt", "is_dir": False},
            ]
        }
    )
    right = FakeBackend(tree={"/right": [{"name": "a.txt", "is_dir": False}]})

    router = FakeRouter(local_backend=FakeBackend(), remote_backends={"l": left, "r": right})
    tool = CompareDirTool(router)

    result = await tool.execute(
        left_host="l",
        left_path="/left",
        right_host="r",
        right_path="/right",
        max_entries=2,
    )

    assert "entry limit exceeded" in result.lower()
    assert "Tip: narrow paths or increase max_entries." in result


@pytest.mark.asyncio
async def test_compare_dir_reports_metadata_differences_in_structure_mode():
    left = FakeBackend(
        tree={"/left": [{"name": "config.json", "is_dir": False, "size": 120, "mtime": 10}]}
    )
    right = FakeBackend(
        tree={"/right": [{"name": "config.json", "is_dir": False, "size": 140, "mtime": 22}]}
    )

    router = FakeRouter(local_backend=FakeBackend(), remote_backends={"l": left, "r": right})
    tool = CompareDirTool(router)

    result = await tool.execute(left_host="l", left_path="/left", right_host="r", right_path="/right")

    assert "- different files: 1 (size/mtime)" in result
    assert "config.json size(left=120, right=140)" in result
    assert "mtime(left=1970-01-01 00:00:10 UTC [10], right=1970-01-01 00:00:22 UTC [22])" in result


@pytest.mark.asyncio
async def test_compare_dir_compare_content_hash_reports_changed_files():
    left = FakeBackend(
        tree={"/left": [{"name": "same.bin", "is_dir": False}, {"name": "diff.bin", "is_dir": False}]},
        bytes_map={
            "/left/same.bin": b"abc",
            "/left/diff.bin": b"left",
        },
    )
    right = FakeBackend(
        tree={"/right": [{"name": "same.bin", "is_dir": False}, {"name": "diff.bin", "is_dir": False}]},
        bytes_map={
            "/right/same.bin": b"abc",
            "/right/diff.bin": b"right",
        },
    )

    router = FakeRouter(local_backend=FakeBackend(), remote_backends={"l": left, "r": right})
    tool = CompareDirTool(router)

    result = await tool.execute(
        left_host="l",
        left_path="/left",
        right_host="r",
        right_path="/right",
        compare_content=True,
    )

    assert "mode: content-hash" in result
    assert "- different files: 1 (checksum)" in result
    assert "diff.bin checksum(" in result
