#!/usr/bin/env python3
"""
End-to-end test: deploy → run commands → teardown.

Tests the full lifecycle:
  1. setup()  — SSH tunnel + deploy.sh + WebSocket connect
  2. execute() — run several commands via WebSocket
  3. teardown() — graceful shutdown via WebSocket → verify cleanup
"""

import asyncio
import logging
import time
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test")


def section(n, title):
    print(f"\n{'─' * 50}")
    print(f"  [{n}] {title}")
    print(f"{'─' * 50}")


async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes["myserver"]

    print("=" * 60)
    print("  Full Workflow Test: deploy → commands → teardown")
    print("=" * 60)
    print(f"  Host : {node_config.ssh_host}")
    print(f"  Port : {node_config.remote_port}")

    node = RemoteNode(node_config)
    errors = []

    # ── 1. Setup (deploy + connect) ──────────────────────────
    section(1, "setup() — deploy.sh + WebSocket connect")
    t0 = time.time()
    try:
        await node.setup()
        elapsed = time.time() - t0
        assert node.is_connected, "node.is_connected should be True"
        print(f"  ✅ Connected in {elapsed:.1f}s  (session: {node.session_id})")
    except Exception as e:
        print(f"  ❌ setup() failed: {e}")
        import traceback; traceback.print_exc()
        return  # can't continue

    session_id = node.session_id  # save for later cleanup check

    # ── 2. Execute commands ──────────────────────────────────
    commands = [
        ("pwd",                     "basic command"),
        ("whoami",                  "identity check"),
        ("echo hello-from-nanobot", "echo test"),
        ("uname -a",               "system info"),
        ("ls /tmp/",               "list /tmp"),
        ("cd /tmp && pwd",         "cd + pwd (session)"),
    ]

    section(2, f"execute() — {len(commands)} commands")
    for i, (cmd, desc) in enumerate(commands, 1):
        try:
            result = await node.execute(cmd, timeout=15.0)
            ok = result.get("success", False)
            output = (result.get("output") or "").strip()
            symbol = "✅" if ok else "⚠️"
            # Truncate long output
            display = output[:120] + ("…" if len(output) > 120 else "")
            print(f"  {symbol} [{i}] {desc:25s} │ {display}")
            if not ok:
                errors.append(f"Command '{cmd}' failed: {result.get('error')}")
        except Exception as e:
            print(f"  ❌ [{i}] {desc:25s} │ EXCEPTION: {e}")
            errors.append(f"Command '{cmd}' exception: {e}")

    # ── 3. Verify remote PID file exists ─────────────────────
    section(3, "verify remote state before teardown")
    try:
        result = await node.execute(f"cat /tmp/{session_id}/server.pid", timeout=10.0)
        pid = (result.get("output") or "").strip()
        print(f"  server.pid = {pid}")
        result = await node.execute(f"ls -la /tmp/{session_id}/", timeout=10.0)
        print(f"  session dir:\n{result.get('output', '').strip()}")
    except Exception as e:
        print(f"  ⚠️  Could not check remote state: {e}")

    # ── 4. Get remote log ────────────────────────────────────
    section(4, "remote server log (last 10 lines)")
    try:
        log = await node._get_remote_log(tail_lines=10)
        for line in log.strip().split("\n"):
            print(f"  │ {line}")
    except Exception as e:
        print(f"  ⚠️  Could not get log: {e}")

    # ── 5. Teardown (graceful shutdown) ──────────────────────
    section(5, "teardown() — graceful shutdown")
    t0 = time.time()
    try:
        await node.teardown()
        elapsed = time.time() - t0
        assert not node.is_connected, "node.is_connected should be False"
        print(f"  ✅ Teardown completed in {elapsed:.1f}s")
    except Exception as e:
        print(f"  ❌ teardown() failed: {e}")
        import traceback; traceback.print_exc()
        errors.append(f"teardown() failed: {e}")

    # ── 6. Verify cleanup on remote ─────────────────────────
    section(6, "verify remote cleanup")
    try:
        remote_check = (
            f"if [ -d /tmp/{session_id} ]; then echo DIR_CHECK=EXISTS; else echo DIR_CHECK=GONE; fi; "
            f"if [ -f /tmp/{session_id}/server.pid ]; then "
            f"  pid=$(cat /tmp/{session_id}/server.pid 2>/dev/null); "
            f"  if [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null; then echo PID_CHECK=ALIVE; else echo PID_CHECK=DEAD; fi; "
            f"else echo PID_CHECK=DEAD; fi; "
            f"if ss -ltn 2>/dev/null | awk '{{print $4}}' | grep -Eq ':{node_config.remote_port}$'; "
            f"then echo PORT_CHECK=IN_USE; else echo PORT_CHECK=FREE; fi"
        )

        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            node_config.ssh_host,
            remote_check,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            print(f"  ⚠️  cleanup check ssh return code={proc.returncode}")
            err = stderr.decode(errors='replace').strip()
            if err:
                print(f"  ⚠️  ssh stderr: {err}")

        output = stdout.decode(errors='replace').strip()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("DIR_CHECK="):
                is_gone = line.endswith("GONE")
                print(f"  {'✅' if is_gone else '⚠️'} Session dir: {'removed' if is_gone else 'STILL EXISTS'}")
            elif line.startswith("PID_CHECK="):
                is_dead = line.endswith("DEAD")
                print(f"  {'✅' if is_dead else '⚠️'} Server process: {'stopped' if is_dead else 'STILL RUNNING'}")
            elif line.startswith("PORT_CHECK="):
                is_free = line.endswith("FREE")
                print(f"  {'✅' if is_free else '⚠️'} Port {node_config.remote_port}: {'free' if is_free else 'STILL IN USE'}")
    except Exception as e:
        print(f"  ⚠️  Could not verify cleanup: {e}")

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    if errors:
        print(f"  ⚠️  {len(errors)} issue(s):")
        for e in errors:
            print(f"    • {e}")
    else:
        print("  ✅ All tests passed!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(test())
