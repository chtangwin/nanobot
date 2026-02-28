#!/usr/bin/env python3
"""nanobot remote_server: Remote execution server for nanobot.

This script runs on remote servers and provides command execution
capabilities through WebSocket communication.

Usage:
    # Direct execution with command line args
    uv run --with websockets remote_server.py --port 8765 --token secret

    # Using config file (recommended for automated deployment)
    uv run --with websockets remote_server.py --config /path/to/config.json

Options:
    --config PATH         Path to JSON config file
    --port PORT           WebSocket port to listen on (default: 8765)
    --token TOKEN         Authentication token (optional)
    --no-tmux             Don't use tmux for session management
"""

import asyncio
import json
import os
import subprocess
import sys
import signal
import argparse
import logging
import time
import uuid
import difflib
import hashlib
import base64
from collections import deque
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Error: websockets package not found.")
    print("Install with: pip install websockets")
    print("Or run with: uv run --with websockets remote_server.py")
    sys.exit(1)

# Configuration defaults
DEFAULT_PORT = 8765
DEFAULT_SESSION_NAME = "nanobot"

logger = logging.getLogger(__name__)

# Request de-duplication cache (idempotency for client retry)
_REQUEST_RESULTS: dict[str, dict] = {}
_REQUEST_INFLIGHT: dict[str, asyncio.Future] = {}
_REQUEST_ORDER: deque[str] = deque()
_REQUEST_CACHE_MAX = 2000


def _payload_hash(data: dict) -> str:
    """Stable hash for request payload validation."""
    stable = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _cache_response(request_id: str, payload_hash: str, response: dict) -> None:
    _REQUEST_RESULTS[request_id] = {
        "hash": payload_hash,
        "response": response,
    }
    _REQUEST_ORDER.append(request_id)
    while len(_REQUEST_ORDER) > _REQUEST_CACHE_MAX:
        old = _REQUEST_ORDER.popleft()
        _REQUEST_RESULTS.pop(old, None)


class TmuxSession:
    """Manage a tmux session for maintaining context using a dedicated socket.

    Commands are wrapped with unique markers so that output can be reliably
    extracted regardless of shell prompt format or special characters in the
    output.  The execution loop polls ``capture-pane`` until the end-marker
    (which embeds the exit code) appears.
    """

    # How long to wait between capture-pane polls (seconds).
    _POLL_INTERVAL_INITIAL = 0.15
    _POLL_INTERVAL_MAX = 1.0
    # Absolute timeout for a single command execution poll loop.
    _POLL_TIMEOUT = 60.0

    def __init__(self, session_name: str = DEFAULT_SESSION_NAME, socket_path: str = None):
        self.session_name = session_name
        self.socket_path = socket_path
        self.running = False

    # -- helpers ----------------------------------------------------------

    def _tmux_cmd(self, *args) -> list:
        """Build tmux command with socket."""
        return ["tmux", "-S", self.socket_path] + list(args)

    def _run(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Shorthand for subprocess.run with the tmux socket."""
        return subprocess.run(self._tmux_cmd(*args), **kwargs)

    # -- lifecycle --------------------------------------------------------

    async def create(self):
        """Create a new tmux session with dedicated socket."""
        if self.running:
            return

        # Ensure socket directory exists
        socket_dir = os.path.dirname(self.socket_path)
        os.makedirs(socket_dir, exist_ok=True)

        # Clean up stale session if it exists
        if self._run("has-session", "-t", self.session_name, capture_output=True).returncode == 0:
            self._run("kill-session", "-t", self.session_name, capture_output=True)
            logger.info(f"Cleaned up stale tmux session: {self.session_name}")

        # Create new session
        self._run("new-session", "-d", "-s", self.session_name, "-n", "shell", check=True)
        self.running = True
        logger.info(f"Created tmux session: {self.session_name} on socket {self.socket_path}")

        # Record tmux server PID (via `tmux display -p '#{pid}'`)
        try:
            r = self._run(
                "display-message", "-p", "#{pid}",
                capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                pid_path = os.path.join(socket_dir, "tmux.pid")
                with open(pid_path, "w") as f:
                    f.write(r.stdout.strip())
                logger.info(f"Saved tmux server PID to {pid_path}")
        except Exception as e:
            logger.warning(f"Could not save tmux PID: {e}")

    # -- command execution ------------------------------------------------

    async def send_and_capture(self, command: str) -> dict:
        """Send a command and capture its output using unique markers.

        Returns ``{"output": str, "exit_code": int}``.
        """
        marker_id = uuid.uuid4().hex[:12]
        start_marker = f"__NANOBOT_START_{marker_id}__"
        end_marker = f"__NANOBOT_END_{marker_id}__"

        # Wrap:  echo START; <cmd>; _ec=$?; echo; echo END_$_ec
        # The extra ``echo`` before END ensures the end-marker starts on its
        # own line even when the command output doesn't end with a newline.
        wrapped = (
            f"echo {start_marker}; "
            f"{command}; _nanobot_ec=$?; "
            f"echo; echo {end_marker}_${{_nanobot_ec}}"
        )

        # Send to tmux (literal mode to preserve special chars)
        escaped = wrapped.replace("'", "'\\''")
        self._run("send-keys", "-t", self.session_name, "-l", "--", escaped, check=True)
        self._run("send-keys", "-t", self.session_name, "Enter", check=True)

        # Poll capture-pane until end-marker appears
        poll_interval = self._POLL_INTERVAL_INITIAL
        deadline = time.monotonic() + self._POLL_TIMEOUT
        raw = ""

        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            raw = self._capture_raw()
            if end_marker in raw:
                break
            # Back off: 0.15 → 0.3 → 0.6 → 1.0 → 1.0 …
            poll_interval = min(poll_interval * 2, self._POLL_INTERVAL_MAX)
        else:
            # Timeout — return whatever we have
            logger.warning(f"Capture timed out after {self._POLL_TIMEOUT}s for marker {marker_id}")
            return {"output": self._extract_partial(raw, start_marker), "exit_code": -1}

        return self._parse_markers(raw, start_marker, end_marker)

    # -- capture helpers --------------------------------------------------

    def _capture_raw(self) -> str:
        """Capture full pane content (up to 500 lines of scrollback)."""
        r = self._run(
            "capture-pane", "-p", "-J", "-t", self.session_name, "-S", "-500",
            capture_output=True, text=True,
        )
        return r.stdout if r.returncode == 0 else ""

    @staticmethod
    def _parse_markers(raw: str, start_marker: str, end_marker: str) -> dict:
        """Extract output and exit code from captured text between markers."""
        lines = raw.split("\n")
        collecting = False
        output_lines: list[str] = []
        exit_code = -1

        for line in lines:
            if start_marker in line:
                collecting = True
                continue
            if end_marker in line:
                # Parse exit code: __NANOBOT_END_xxxx___<ec>
                # The line looks like: __NANOBOT_END_abc123def456___0
                suffix = line.split(end_marker, 1)[1].lstrip("_")
                try:
                    exit_code = int(suffix)
                except ValueError:
                    exit_code = -1
                break
            if collecting:
                output_lines.append(line)

        # Trim empty leading/trailing lines from the captured output
        while output_lines and not output_lines[0].strip():
            output_lines.pop(0)
        while output_lines and not output_lines[-1].strip():
            output_lines.pop()

        return {"output": "\n".join(output_lines), "exit_code": exit_code}

    @staticmethod
    def _extract_partial(raw: str, start_marker: str) -> str:
        """Best-effort extraction when the end-marker is missing (timeout)."""
        idx = raw.find(start_marker)
        if idx == -1:
            return raw[-2000:] if len(raw) > 2000 else raw
        after = raw[idx + len(start_marker):]
        lines = after.strip().split("\n")
        return "\n".join(lines[:200])

    # -- teardown ---------------------------------------------------------

    def destroy(self):
        """Gracefully destroy the tmux session.

        Sends ``exit`` to the shell first; falls back to ``kill-session``.
        """
        if not self.running:
            return

        try:
            self._run("send-keys", "-t", self.session_name, "exit", "Enter",
                       capture_output=True, timeout=3)
            time.sleep(0.5)
        except Exception:
            pass

        if self._run("has-session", "-t", self.session_name, capture_output=True).returncode == 0:
            self._run("kill-session", "-t", self.session_name, capture_output=True)
            logger.info(f"Killed tmux session: {self.session_name}")
        else:
            logger.info(f"Tmux session {self.session_name} exited gracefully")

        self.running = False


class SimpleExecutor:
    """Simple command executor without tmux."""

    async def execute(self, command: str) -> dict:
        """Execute a command directly."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="replace"),
                "error": stderr.decode("utf-8", errors="replace") if stderr else None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": str(e),
            }


class CommandExecutor:
    """Execute commands and return results."""

    def __init__(self, use_tmux: bool = True, socket_path: str = None):
        self.use_tmux = use_tmux
        self.socket_path = socket_path or "/tmp/nanobot-tmux.sock"
        if use_tmux:
            self.tmux = TmuxSession(socket_path=self.socket_path)
        else:
            self.tmux = None

    async def exec(self, command: str) -> dict:
        """Execute a shell command and return structured result."""
        if self.use_tmux:
            return await self._execute_tmux(command)
        return await self._execute_simple(command)

    async def _execute_tmux(self, command: str) -> dict:
        try:
            await self.tmux.create()
            result = await self.tmux.send_and_capture(command)
            exit_code = result["exit_code"]
            return {
                "success": exit_code == 0,
                "output": result["output"],
                "exit_code": exit_code,
                "error": None if exit_code == 0 else f"exit code {exit_code}",
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "exit_code": -1,
                "error": str(e),
            }

    async def _execute_simple(self, command: str) -> dict:
        executor = SimpleExecutor()
        result = await executor.execute(command)
        result.setdefault("exit_code", 0 if result.get("success") else 1)
        return result

    def cleanup(self):
        if self.tmux:
            self.tmux.destroy()


class FileService:
    """Structured filesystem RPC operations."""

    @staticmethod
    async def read_file(path: str) -> dict:
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"Not a file: {path}"}
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = p.read_bytes().decode("utf-8", errors="replace")
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def write_file(path: str, content: str) -> dict:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "bytes": len(content), "path": str(p)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def read_bytes(path: str) -> dict:
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"Not a file: {path}"}
            content = p.read_bytes()
            return {
                "success": True,
                "content_b64": base64.b64encode(content).decode("ascii"),
                "size": len(content),
                "path": str(p),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def edit_file(path: str, old_text: str, new_text: str) -> dict:
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"Not a file: {path}"}

            content = p.read_text(encoding="utf-8")
            if old_text not in content:
                lines = content.splitlines(keepends=True)
                old_lines = old_text.splitlines(keepends=True)
                window = len(old_lines)
                best_ratio, best_start = 0.0, 0
                for i in range(max(1, len(lines) - window + 1)):
                    ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
                    if ratio > best_ratio:
                        best_ratio, best_start = ratio, i
                if best_ratio > 0.5:
                    diff = "\n".join(difflib.unified_diff(
                        old_lines,
                        lines[best_start : best_start + window],
                        fromfile="old_text (provided)",
                        tofile=f"{path} (actual, line {best_start + 1})",
                        lineterm="",
                    ))
                    return {
                        "success": False,
                        "error": f"old_text not found in {path}. Best match ({best_ratio:.0%}) at line {best_start + 1}:\n{diff}",
                    }
                return {"success": False, "error": f"old_text not found in {path}. No similar text found."}

            count = content.count(old_text)
            if count > 1:
                return {"success": False, "error": f"old_text appears {count} times. Please provide more context."}

            p.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return {"success": True, "path": str(p)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def list_dir(path: str) -> dict:
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            if not p.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            entries = [
                {"name": item.name, "is_dir": item.is_dir()}
                for item in sorted(p.iterdir())
            ]
            return {"success": True, "entries": entries}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def handle_connection(
    websocket,
    auth_token: str,
    use_tmux: bool,
    session_dir: str = None,
    stop_event: asyncio.Event = None,
):
    """Handle WebSocket connection.

    Message types:
        exec       - run a shell command, returns structured result
        read_file  - read file content (text)
        read_bytes - read file content (raw bytes, base64-encoded)
        write_file - write file content
        edit_file  - replace text in file
        list_dir   - list directory entries
        ping      - health check, returns pong
        close     - close this connection (server stays up)
        shutdown  - gracefully shut down the entire server
    """
    logger.info(f"New connection from {websocket.remote_address}")

    # Authentication
    try:
        auth_message = await websocket.recv()
        auth_data = json.loads(auth_message)

        if auth_token and auth_data.get("token") != auth_token:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Authentication failed"
            }))
            logger.warning("Authentication failed")
            return

        # Send success message
        await websocket.send(json.dumps({
            "type": "authenticated",
            "message": "Connection established"
        }))
        logger.info("Authentication successful")

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return

    # Use socket in session directory
    socket_path = f"{session_dir}/tmux.sock" if session_dir else "/tmp/nanobot-tmux.sock"
    logger.info(f"Using tmux socket: {socket_path}")
    
    executor = CommandExecutor(use_tmux=use_tmux, socket_path=socket_path)

    async def _dispatch_message(data: dict) -> tuple[dict, bool]:
        """Dispatch one protocol message. Returns (response, should_break)."""
        msg_type = data.get("type")

        if msg_type in ("exec", "execute"):
            command = data.get("command")
            if not command:
                return ({"type": "error", "message": "No command provided"}, False)

            logger.info(f"Executing: {command[:100]}...")
            result = await executor.exec(command)
            return ({"type": "result", "command": command, **result}, False)

        if msg_type == "read_file":
            path = data.get("path")
            if not path:
                return ({"type": "error", "message": "No path provided"}, False)
            result = await FileService.read_file(path)
            return ({"type": "result", **result}, False)

        if msg_type == "read_bytes":
            path = data.get("path")
            if not path:
                return ({"type": "error", "message": "No path provided"}, False)
            result = await FileService.read_bytes(path)
            return ({"type": "result", **result}, False)

        if msg_type == "write_file":
            path = data.get("path")
            content = data.get("content")
            if not path:
                return ({"type": "error", "message": "No path provided"}, False)
            if content is None:
                return ({"type": "error", "message": "No content provided"}, False)
            result = await FileService.write_file(path, content)
            return ({"type": "result", **result}, False)

        if msg_type == "edit_file":
            path = data.get("path")
            old_text = data.get("old_text")
            new_text = data.get("new_text")
            if not path:
                return ({"type": "error", "message": "No path provided"}, False)
            if old_text is None or new_text is None:
                return ({"type": "error", "message": "old_text/new_text required"}, False)
            result = await FileService.edit_file(path, old_text, new_text)
            return ({"type": "result", **result}, False)

        if msg_type == "list_dir":
            path = data.get("path")
            if not path:
                return ({"type": "error", "message": "No path provided"}, False)
            result = await FileService.list_dir(path)
            return ({"type": "result", **result}, False)

        if msg_type == "ping":
            return ({"type": "pong"}, False)

        if msg_type == "close":
            logger.info("Received close message, closing connection")
            return ({"type": "result", "success": True, "message": "Connection closing"}, True)

        if msg_type == "shutdown":
            logger.info("Received shutdown message, stopping server")
            if stop_event:
                stop_event.set()
            return ({"type": "shutdown_ack", "message": "Server shutting down"}, True)

        return ({"type": "error", "message": f"Unknown message type: {msg_type}"}, False)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                request_id = data.get("request_id")

                # Fast path: no idempotency key
                if not request_id:
                    response, should_break = await _dispatch_message(data)
                    await websocket.send(json.dumps(response))
                    if should_break:
                        break
                    continue

                payload_hash = _payload_hash(data)

                # 1) Done cache
                cached = _REQUEST_RESULTS.get(request_id)
                if cached:
                    if cached["hash"] != payload_hash:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "request_id": request_id,
                            "message": "request_id reuse with different payload",
                        }))
                        continue
                    await websocket.send(json.dumps(cached["response"]))
                    continue

                # 2) In-flight dedupe
                in_flight = _REQUEST_INFLIGHT.get(request_id)
                if in_flight:
                    response = await in_flight
                    await websocket.send(json.dumps(response))
                    continue

                # 3) Execute and cache
                loop = asyncio.get_running_loop()
                fut: asyncio.Future = loop.create_future()
                _REQUEST_INFLIGHT[request_id] = fut

                try:
                    response, should_break = await _dispatch_message(data)
                    response["request_id"] = request_id
                    _cache_response(request_id, payload_hash, response)
                    fut.set_result(response)
                    await websocket.send(json.dumps(response))
                    if should_break:
                        break
                except Exception as e:
                    err_resp = {
                        "type": "error",
                        "request_id": request_id,
                        "message": str(e),
                    }
                    _cache_response(request_id, payload_hash, err_resp)
                    if not fut.done():
                        fut.set_result(err_resp)
                    await websocket.send(json.dumps(err_resp))
                finally:
                    _REQUEST_INFLIGHT.pop(request_id, None)

            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON"
                }))
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": str(e)
                }))

    except websockets.exceptions.ConnectionClosed:
        logger.info("Connection closed")
    finally:
        executor.cleanup()


async def main():
    """Start the WebSocket server."""
    parser = argparse.ArgumentParser(description="nanobot remote host")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to JSON config file (overrides other args)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"WebSocket port to listen on (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="Authentication token (optional)"
    )
    parser.add_argument(
        "--no-tmux",
        action="store_true",
        help="Don't use tmux for session management"
    )

    args = parser.parse_args()

    # Setup logging FIRST so all subsequent messages are formatted
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Load config file if specified
    if args.config:
        import json
        from pathlib import Path

        config_path = Path(args.config)
        if not config_path.exists():
            logger.error(f"Config file not found: {args.config}")
            sys.exit(1)

        try:
            with open(config_path) as f:
                config = json.load(f)

            # Apply config (overrides command line args)
            port = config.get("port", args.port)
            token = config.get("token", args.token)
            use_tmux = config.get("tmux", not args.no_tmux)

            logger.info(f"Loaded config from: {args.config}")
            logger.info(f"Config: port={port}, token={'***' if token else 'none'}, tmux={use_tmux}")

        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            sys.exit(1)
    else:
        port = args.port
        token = args.token
        use_tmux = not args.no_tmux

    logger.info(f"Starting remote_server on port {port}")
    if token:
        logger.info("Authentication token enabled")
    if not use_tmux:
        logger.info("Running without tmux (no session persistence)")
    else:
        logger.info("Running with tmux (session persistence enabled)")

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start server
    # Determine session directory: prefer config file dir, then CWD if it
    # looks like a nanobot session dir (/tmp/nanobot-*), else None.
    if args.config:
        session_dir = os.path.dirname(os.path.abspath(args.config))
    else:
        cwd = os.getcwd()
        session_dir = cwd if os.path.basename(cwd).startswith("nanobot-") else None

    handler = lambda ws: handle_connection(ws, token, use_tmux, session_dir, stop_event)

    async with websockets.serve(handler, "0.0.0.0", port):
        logger.info(f"Server listening on ws://0.0.0.0:{port}")
        await stop_event.wait()

    logger.info("remote_server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
