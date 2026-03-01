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
from nanobot.remote.config import HostsConfig
from nanobot.remote.connection import RemoteHost

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
    config = HostsConfig.load(HostsConfig.get_default_config_path())
    host_config = config.hosts["debian-bot"]

    print("=" * 60)
    print("  Full Workflow Test: deploy → commands → teardown")
    print("=" * 60)
    print(f"  Host : {host_config.ssh_host}")
    print(f"  Port : {host_config.remote_port}")

    host = RemoteHost(host_config)
    errors = []

    # ── 1. Setup (deploy + connect) ──────────────────────────
    section(1, "setup() — deploy.sh + WebSocket connect")
    t0 = time.time()
    try:
        await host.setup()
        elapsed = time.time() - t0
        assert host.is_connected, "host.is_connected should be True"
        print(f"  ✅ Connected in {elapsed:.1f}s  (session: {host.session_id})")
    except Exception as e:
        print(f"  ❌ setup() failed: {e}")
        import traceback; traceback.print_exc()
        return  # can't continue

    session_id = host.session_id  # save for later cleanup check

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
            result = await host.execute(cmd, timeout=15.0)
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
        result = await host.execute(f"cat /tmp/{session_id}/server.pid", timeout=10.0)
        pid = (result.get("output") or "").strip()
        print(f"  server.pid = {pid}")
        result = await host.execute(f"ls -la /tmp/{session_id}/", timeout=10.0)
        print(f"  session dir:\n{result.get('output', '').strip()}")
    except Exception as e:
        print(f"  ⚠️  Could not check remote state: {e}")

    # ── 4. Auto-heal transport (no implicit new session) ─────
    section(4, "auto-heal on transport drop (same session, no redeploy)")
    try:
        before_session = host.session_id
        # Simulate network/transport loss on local side only
        await host._mark_transport_down()

        result = await host.execute("pwd", timeout=20.0)
        ok = result.get("success", False)
        same_session = host.session_id == before_session
        print(f"  {'✅' if ok else '❌'} auto-reconnect execute: {result.get('output', '').strip()}")
        print(f"  {'✅' if same_session else '❌'} session unchanged: {before_session} -> {host.session_id}")
        if not ok:
            errors.append(f"auto-heal execute failed: {result.get('error')}")
        if not same_session:
            errors.append("auto-heal changed session unexpectedly")
    except Exception as e:
        print(f"  ❌ auto-heal test failed: {e}")
        errors.append(f"auto-heal test failed: {e}")

    # ── 5. Idempotency (request_id de-dup) ───────────────────
    section(5, "idempotency: retry same request_id should not re-execute")
    try:
        counter_file = f"/tmp/{session_id}/idem_counter.txt"
        req_id = "idem-e2e-001"
        command = (
            f"v=$(cat {counter_file} 2>/dev/null || echo 0); "
            f"v=$((v+1)); echo $v > {counter_file}; cat {counter_file}"
        )

        first = await host._rpc({"type": "exec", "command": command, "request_id": req_id}, timeout=20.0)
        # Simulate transport loss before retrying the SAME request_id
        await host._mark_transport_down()
        second = await host._rpc({"type": "exec", "command": command, "request_id": req_id}, timeout=20.0)
        verify = await host.execute(f"cat {counter_file}", timeout=10.0)

        out1 = (first.get("output") or "").strip()
        out2 = (second.get("output") or "").strip()
        outv = (verify.get("output") or "").strip()

        print(f"  first result  = {out1}")
        print(f"  retry result  = {out2}")
        print(f"  counter final = {outv}")

        idempotent = (out1 == out2 == "1") and (outv == "1")
        print(f"  {'✅' if idempotent else '❌'} de-dup effective")
        if not idempotent:
            errors.append("idempotency failed: same request_id appears re-executed")
    except Exception as e:
        print(f"  ❌ idempotency test failed: {e}")
        errors.append(f"idempotency test failed: {e}")

    # ── 6. request_id 冲突保护（同 ID 不同 payload）───────────
    section(6, "idempotency guard: same request_id + different payload should fail")
    try:
        guard_id = "idem-e2e-guard-001"
        cmd_a = "echo guard-A"
        cmd_b = "echo guard-B"

        first_ok = await host._rpc({"type": "exec", "command": cmd_a, "request_id": guard_id}, timeout=15.0)
        second_conflict = await host._rpc({"type": "exec", "command": cmd_b, "request_id": guard_id}, timeout=15.0)

        out_ok = (first_ok.get("output") or "").strip()
        err_conflict = (second_conflict.get("error") or "").strip()
        is_guarded = (out_ok == "guard-A") and ("different payload" in err_conflict)

        print(f"  first result   = {out_ok}")
        print(f"  conflict error = {err_conflict}")
        print(f"  {'✅' if is_guarded else '❌'} conflict guard effective")

        if not is_guarded:
            errors.append("idempotency guard failed: same request_id accepted different payload")
    except Exception as e:
        print(f"  ❌ idempotency guard test failed: {e}")
        errors.append(f"idempotency guard test failed: {e}")

    # ── 7. Get remote log ────────────────────────────────────
    section(7, "remote server log (last 10 lines)")
    try:
        log = await host._get_remote_log(tail_lines=10)
        for line in log.strip().split("\n"):
            print(f"  │ {line}")
    except Exception as e:
        print(f"  ⚠️  Could not get log: {e}")

    # ── 8. Teardown (graceful shutdown) ──────────────────────
    section(8, "teardown() — graceful shutdown")
    t0 = time.time()
    try:
        await host.teardown()
        elapsed = time.time() - t0
        assert not host.is_connected, "host.is_connected should be False"
        print(f"  ✅ Teardown completed in {elapsed:.1f}s")
    except Exception as e:
        print(f"  ❌ teardown() failed: {e}")
        import traceback; traceback.print_exc()
        errors.append(f"teardown() failed: {e}")

    # ── 9. Verify cleanup on remote ─────────────────────────
    section(9, "verify remote cleanup")
    try:
        remote_check = (
            f"if [ -d /tmp/{session_id} ]; then echo DIR_CHECK=EXISTS; else echo DIR_CHECK=GONE; fi; "
            f"if [ -f /tmp/{session_id}/server.pid ]; then "
            f"  pid=$(cat /tmp/{session_id}/server.pid 2>/dev/null); "
            f"  if [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null; then echo PID_CHECK=ALIVE; else echo PID_CHECK=DEAD; fi; "
            f"else echo PID_CHECK=DEAD; fi; "
            f"if ss -ltn 2>/dev/null | awk '{{print $4}}' | grep -Eq ':{host_config.remote_port}$'; "
            f"then echo PORT_CHECK=IN_USE; else echo PORT_CHECK=FREE; fi"
        )

        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            host_config.ssh_host,
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
                print(f"  {'✅' if is_free else '⚠️'} Port {host_config.remote_port}: {'free' if is_free else 'STILL IN USE'}")
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
