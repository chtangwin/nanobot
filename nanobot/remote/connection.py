"""Remote host connection implementation."""

import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from typing import Optional, Any
from pathlib import Path

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    websockets = None
    ConnectionClosed = Exception

from nanobot.remote.config import HostConfig

logger = logging.getLogger(__name__)

# Paths to files that get uploaded to the remote host
_MODULE_DIR = Path(__file__).parent
_REMOTE_SERVER_PATH = _MODULE_DIR / "remote_server.py"
_DEPLOY_SCRIPT_PATH = _MODULE_DIR / "deploy.sh"

# Validate at import time
for _p in (_REMOTE_SERVER_PATH, _DEPLOY_SCRIPT_PATH):
    if not _p.exists():
        logger.warning(f"Required file not found: {_p}")

class RemoteHost:
    """
    Remote host connection.

    Manages SSH tunnel, WebSocket connection, and command execution
    on a remote server.
    """

    def __init__(self, config: HostConfig):
        self.config = config
        self.session_id: Optional[str] = None
        self.tunnel_process: Optional[asyncio.subprocess.Process] = None
        self.websocket: Optional[Any] = None
        self._running = False
        self._authenticated = False
        self._last_recovery_error = ""

    @property
    def is_connected(self) -> bool:
        """Check if the host is connected."""
        return self._running and self._authenticated

    async def setup(self) -> str:
        """
        Establish connection to remote host.

        Returns:
            Session ID for this connection.

        Raises:
            ConnectionError: If connection fails.
        """
        if self._running:
            return self.session_id

        if websockets is None:
            raise ImportError(
                "websockets package is required. Install with: uv add websockets"
            )

        try:
            # Generate unique session ID
            self.session_id = f"nanobot-{uuid.uuid4().hex[:8]}"

            # Create SSH tunnel
            await self._create_ssh_tunnel()

            # Deploy and start host service (single operation)
            await self._deploy_and_start_host()

            # Connect WebSocket
            await self._connect_websocket()

            # Authenticate
            await self._authenticate()

            self._running = True
            logger.info(f"Remote host {self.config.name} connected (session: {self.session_id})")
            return self.session_id

        except Exception as e:
            logger.error(f"Failed to setup remote host {self.config.name}: {e}")
            # Try to get remote logs for debugging
            try:
                remote_log = await self._get_remote_log()
                logger.error(f"Remote host log:\n{remote_log}")
            except Exception:
                pass
            await self.teardown()
            raise ConnectionError(f"Failed to connect to {self.config.name}: {e}")

    async def teardown(self):
        """Clean up all resources.

        Shutdown sequence:
        1. Send ``shutdown`` via WebSocket → remote_server exits gracefully
           (cleans up tmux, closes WebSocket server, process exits)
        2. If shutdown didn't work, fall back to SSH-based kill
        3. Close the local SSH tunnel
        4. Clean up remote session directory
        """
        self._running = False
        self._authenticated = False

        # Step 1: Try graceful shutdown via WebSocket
        server_stopped = await self._request_shutdown()

        # Step 2: If graceful shutdown failed, force-stop via SSH
        if not server_stopped:
            try:
                await self._force_stop_host()
            except Exception as e:
                logger.warning(f"Failed to force-stop remote host: {e}")

        # Step 3: Clean up remote session directory
        if self.session_id:
            try:
                await self._ssh_exec(f"rm -rf /tmp/{self.session_id}")
            except Exception as e:
                logger.warning(f"Failed to clean remote directory: {e}")

        # Step 4: Close SSH tunnel (must be last — steps 2-3 need it)
        try:
            await self._close_ssh_tunnel()
        except Exception as e:
            logger.warning(f"Failed to close SSH tunnel: {e}")

        logger.info(f"Remote host {self.config.name} disconnected")

    async def _ensure_transport_ready(self) -> bool:
        """Ensure we have an authenticated tunnel+websocket without redeploying.

        Rules:
        - If this object has never connected before, call full setup().
        - If it connected before and later lost transport, only try transport-level
          recovery (SSH tunnel + WebSocket + auth). No implicit redeploy/new session.
        """
        if self._running and self._authenticated and self.websocket:
            return True

        if self.session_id is None:
            # First-time connect is allowed to deploy/start.
            await self.setup()
            return True

        # Existing session lost transport: recover only.
        return await self._recover_transport()

    def _is_transport_error(self, exc: Exception) -> bool:
        if isinstance(exc, (ConnectionClosed, OSError, ConnectionError, RuntimeError)):
            return True
        msg = str(exc).lower()
        return any(k in msg for k in [
            "connection closed",
            "broken pipe",
            "connection reset",
            "not connected",
            "eof",
        ])

    async def _mark_transport_down(self) -> None:
        self._running = False
        self._authenticated = False

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        # Restart tunnel during recovery.
        await self._close_ssh_tunnel()

    async def _recover_transport(self) -> bool:
        """Recover SSH tunnel + WS + auth for the same existing session.

        IMPORTANT: no redeploy, no new session_id.
        """
        self._last_recovery_error = ""
        try:
            await self._mark_transport_down()
            try:
                await self._create_ssh_tunnel()
            except Exception as e:
                self._last_recovery_error = f"Network unreachable: SSH tunnel failed ({e})"
                raise
            try:
                await self._connect_websocket()
            except Exception as e:
                self._last_recovery_error = f"Remote server not responding: WebSocket failed ({e})"
                raise
            await self._authenticate()
            self._running = True
            logger.info(f"Transport recovered for host {self.config.name} (session: {self.session_id})")
            return True
        except Exception as e:
            if not self._last_recovery_error:
                self._last_recovery_error = f"Transport recovery failed: {e}"
            logger.warning(f"{self._last_recovery_error} (host: {self.config.name})")
            await self._mark_transport_down()
            return False

    async def _rpc(self, message: dict, timeout: float = 30.0) -> dict:
        """Send one RPC message to remote_server and return normalized result.

        Uses request_id for idempotent retry and performs transport-only auto-heal.
        """
        request_id = message.get("request_id") or uuid.uuid4().hex
        message["request_id"] = request_id

        try:
            ready = await self._ensure_transport_ready()
        except Exception as e:
            return {"success": False, "error": f"Cannot connect to remote host: {e}"}

        if not ready:
            error = self._last_recovery_error or "Cannot connect to remote host"
            return {"success": False, "error": error}

        for attempt in range(2):
            try:
                await self.websocket.send(json.dumps(message))
                response = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                data = json.loads(response)

                if data.get("request_id") and data.get("request_id") != request_id:
                    return {"success": False, "error": "Mismatched request_id in response"}

                if data.get("type") == "result":
                    return data
                if data.get("type") in ("error", "shutdown_ack"):
                    return {"success": False, "error": data.get("message", "Unknown error")}
                if data.get("type") == "pong":
                    return {"success": True, "type": "pong"}
                return {"success": False, "error": f"Unexpected response type: {data.get('type')}"}

            except asyncio.TimeoutError:
                return {"success": False, "error": f"Command timed out after {timeout} seconds"}
            except Exception as e:
                if attempt == 0 and self._is_transport_error(e):
                    logger.warning(f"RPC transport issue on {self.config.name}, trying auto-recover: {e}")
                    recovered = await self._recover_transport()
                    if recovered:
                        continue
                    error = self._last_recovery_error or "Connection lost and auto-reconnect failed"
                    return {"success": False, "error": error}

                logger.error(f"RPC failed on {self.config.name}: {e}")
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "RPC retry exhausted"}

    async def ping(self, timeout: float = 5.0) -> bool:
        """Lightweight health check against remote_server."""
        try:
            result = await self._rpc({"type": "ping"}, timeout=timeout)
            return result.get("type") == "pong" or result.get("success", False)
        except Exception:
            return False

    async def exec(self, command: str, timeout: float = 30.0) -> dict:
        """Execute a shell command on the remote host."""
        result = await self._rpc({"type": "exec", "command": command}, timeout=timeout)
        return {
            "success": result.get("success", False),
            "output": result.get("output"),
            "error": result.get("error"),
            "exit_code": result.get("exit_code"),
        }

    async def execute(self, command: str, timeout: float = 30.0) -> dict:
        """Backward-compatible alias for exec()."""
        return await self.exec(command, timeout=timeout)

    async def read_file(self, path: str, timeout: float = 30.0) -> dict:
        result = await self._rpc({"type": "read_file", "path": path}, timeout=timeout)
        return {
            "success": result.get("success", False),
            "content": result.get("content"),
            "error": result.get("error"),
        }

    async def write_file(self, path: str, content: str, timeout: float = 30.0) -> dict:
        result = await self._rpc(
            {"type": "write_file", "path": path, "content": content},
            timeout=timeout,
        )
        return {
            "success": result.get("success", False),
            "bytes": result.get("bytes"),
            "error": result.get("error"),
        }

    async def read_bytes(self, path: str, timeout: float = 30.0) -> dict:
        result = await self._rpc({"type": "read_bytes", "path": path}, timeout=timeout)
        if not result.get("success", False):
            return {
                "success": False,
                "content": None,
                "size": result.get("size"),
                "error": result.get("error") or "Failed to read bytes",
            }

        data_b64 = result.get("content_b64")
        content = None
        if data_b64:
            import base64
            import binascii

            try:
                content = base64.b64decode(data_b64, validate=True)
            except (binascii.Error, ValueError) as e:
                return {
                    "success": False,
                    "content": None,
                    "size": None,
                    "error": f"Invalid base64 payload from remote read_bytes: {e}",
                }

        return {
            "success": True,
            "content": content,
            "size": result.get("size"),
            "error": result.get("error"),
        }

    async def edit_file(self, path: str, old_text: str, new_text: str, timeout: float = 30.0) -> dict:
        result = await self._rpc(
            {
                "type": "edit_file",
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
            },
            timeout=timeout,
        )
        return {
            "success": result.get("success", False),
            "path": result.get("path"),
            "error": result.get("error"),
        }

    async def list_dir(self, path: str, timeout: float = 30.0) -> dict:
        result = await self._rpc({"type": "list_dir", "path": path}, timeout=timeout)
        return {
            "success": result.get("success", False),
            "entries": result.get("entries"),
            "error": result.get("error"),
        }

    async def _create_ssh_tunnel(self):
        """Create SSH tunnel to remote host."""
        # Auto-assign local port if not specified
        if self.config.local_port is None:
            import socket
            sock = socket.socket()
            sock.bind(("", 0))
            self.config.local_port = sock.getsockname()[1]
            sock.close()

        ssh_cmd = [
            "ssh",
            "-N",  # No remote commands
            "-L", f"{self.config.local_port}:127.0.0.1:{self.config.remote_port}",
            "-p", str(self.config.ssh_port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ]

        if self.config.ssh_key_path:
            ssh_cmd.extend(["-i", self.config.ssh_key_path])

        ssh_cmd.append(self.config.ssh_host)

        logger.info(f"Creating SSH tunnel: {self.config.ssh_host} -> localhost:{self.config.local_port}")

        self.tunnel_process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for tunnel to establish
        await asyncio.sleep(2)

        # Check if tunnel process is still running
        if self.tunnel_process.returncode is not None:
            stderr = await self.tunnel_process.stderr.read() if self.tunnel_process.stderr else b""
            raise ConnectionError(f"SSH tunnel failed: {stderr.decode()}")

    async def _close_ssh_tunnel(self):
        """Close SSH tunnel."""
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
                await asyncio.wait_for(self.tunnel_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.tunnel_process.kill()
                await self.tunnel_process.wait()
            except Exception as e:
                logger.warning(f"Failed to close SSH tunnel: {e}")
            finally:
                self.tunnel_process = None

    async def _deploy_and_start_host(self):
        """Deploy files and start remote service on host using deploy.sh.

        Stages:
        1. Prepare a local staging directory (remote_server.py + deploy.sh)
        2. Create remote session directory
        3. Upload everything in a single ``scp -r`` call
        4. Execute ``deploy.sh`` with port/token/tmux args on remote
        """
        for path, name in [(_REMOTE_SERVER_PATH, "remote_server.py"), (_DEPLOY_SCRIPT_PATH, "deploy.sh")]:
            if not path.exists():
                raise RuntimeError(f"{name} not found at {path}")

        remote_dir = f"/tmp/{self.session_id}"

        # -- 1. Stage files locally ------------------------------------------
        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            shutil.copy2(_REMOTE_SERVER_PATH, staging_path / "remote_server.py")
            shutil.copy2(_DEPLOY_SCRIPT_PATH, staging_path / "deploy.sh")

            logger.info(
                f"Deploying to {self.config.ssh_host}:{remote_dir} "
                f"(port={self.config.remote_port}, "
                f"token={'***' if self.config.auth_token else 'none'})"
            )

            # -- 2. Create remote directory -----------------------------------
            await self._ssh_exec(f"mkdir -p {remote_dir}")

            # -- 3. Upload all files in one scp call --------------------------
            await self._scp_upload(staging, remote_dir)

        # -- 4. Execute deploy script with args on remote ---------------------
        deploy_args = f"--port {self.config.remote_port}"
        if self.config.auth_token:
            deploy_args += f" --token '{self.config.auth_token}'"

        logger.info("Running deploy.sh on remote...")
        output = await self._ssh_exec(
            f"bash {remote_dir}/deploy.sh {deploy_args}",
            timeout=90.0,  # allow time for uv install + websockets download
        )
        logger.info(f"Deploy output: {output}")

    async def _scp_upload(self, local_dir: str, remote_dir: str):
        """Upload contents of a local directory to remote via scp.

        Uses a single ``scp -r`` with proper SSH options to avoid
        interactive prompts.
        """
        scp_cmd = [
            "scp", "-r",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",
        ]
        if self.config.ssh_port:
            scp_cmd.extend(["-P", str(self.config.ssh_port)])
        if self.config.ssh_key_path:
            scp_cmd.extend(["-i", self.config.ssh_key_path])

        # Upload contents: local_dir/* -> remote_dir/
        # We use glob to list files so scp places them inside remote_dir
        local_files = [str(p) for p in Path(local_dir).iterdir()]
        scp_cmd.extend(local_files)
        scp_cmd.append(f"{self.config.ssh_host}:{remote_dir}/")

        process = await asyncio.create_subprocess_exec(
            *scp_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"scp upload failed: {error_msg}")

    async def _get_remote_log(self, tail_lines: int = 50) -> str:
        """Get remote host server log."""
        if not self.session_id:
            return "No session ID"

        log_file = f"/tmp/{self.session_id}/remote_server.log"

        try:
            result = await self._ssh_exec(f"tail -{tail_lines} {log_file} 2>/dev/null || echo 'Log file not found'")
            return result
        except Exception as e:
            return f"Failed to get log: {e}"

    async def _request_shutdown(self) -> bool:
        """Ask remote_server to shut itself down via WebSocket.

        Returns True if the server acknowledged the shutdown.
        """
        if not self.websocket:
            return False

        try:
            await self.websocket.send(json.dumps({"type": "shutdown"}))

            # Wait for acknowledgement
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            data = json.loads(response)

            if data.get("type") == "shutdown_ack":
                logger.info("Server acknowledged shutdown, waiting for process to exit...")
                # Give it a moment to finish cleanup (tmux destroy, etc.)
                await asyncio.sleep(2.0)
                return True

            logger.warning(f"Unexpected shutdown response: {data}")
            return False

        except (asyncio.TimeoutError, ConnectionError):
            logger.warning("Shutdown request timed out or connection lost")
            return False
        except Exception as e:
            logger.warning(f"Shutdown request failed: {e}")
            return False
        finally:
            # Always close the websocket object on our side
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None

    async def _force_stop_host(self):
        """Force-stop the remote host via SSH. Fallback when graceful shutdown fails."""
        if not self.session_id:
            return

        remote_dir = f"/tmp/{self.session_id}"
        pid_file = f"{remote_dir}/server.pid"
        tmux_sock = f"{remote_dir}/tmux.sock"

        logger.info(f"Force-stopping host for session {self.session_id}")

        # 1. SIGTERM via PID file, wait, then SIGKILL if needed
        await self._ssh_exec(
            f"if [ -f {pid_file} ]; then "
            f"  pid=$(cat {pid_file}); "
            f"  kill $pid 2>/dev/null && sleep 1; "
            f"  kill -0 $pid 2>/dev/null && kill -9 $pid 2>/dev/null; "
            f"fi || true"
        )

        # 2. Fallback: kill by port
        await self._ssh_exec(
            f"fuser -k {self.config.remote_port}/tcp 2>/dev/null || true"
        )

        # 3. Clean up tmux session
        await self._ssh_exec(
            f"tmux -S '{tmux_sock}' kill-session -t nanobot 2>/dev/null || true"
        )

    async def _connect_websocket(self):
        """Connect to remote host via WebSocket."""
        ws_url = f"ws://127.0.0.1:{self.config.local_port}"

        logger.info(f"Connecting to WebSocket: {ws_url}")

        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(ws_url, max_size=50 * 1024 * 1024),  # 50MB
                timeout=10.0
            )
        except asyncio.TimeoutError:
            raise ConnectionError(f"WebSocket connection timeout: {ws_url}")
        except Exception as e:
            raise ConnectionError(f"WebSocket connection failed: {e}")

    async def _authenticate(self):
        """Authenticate with the remote host."""
        # Send authentication message (with or without token)
        auth_message = {
            "token": self.config.auth_token if self.config.auth_token else "",
        }
        await self.websocket.send(json.dumps(auth_message))

        # Wait for authentication response
        response = await asyncio.wait_for(
            self.websocket.recv(),
            timeout=5.0
        )

        data = json.loads(response)

        if data.get("type") == "authenticated":
            self._authenticated = True
        elif data.get("type") == "error":
            raise ConnectionError(f"Authentication failed: {data.get('message')}")
        else:
            raise ConnectionError(f"Unexpected authentication response: {data}")

    def _build_ssh_cmd(self) -> list[str]:
        """Build base SSH command with common options."""
        cmd = [
            "ssh",
            "-p", str(self.config.ssh_port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",
        ]
        if self.config.ssh_key_path:
            cmd.extend(["-i", self.config.ssh_key_path])
        return cmd

    async def _ssh_exec(self, command: str, timeout: float = 30.0) -> str:
        """Execute a command via SSH.

        All commands are executed with asyncio and awaited properly.
        The old Popen-for-background-commands approach is no longer needed
        because deploy.sh handles daemonization via setsid/disown.
        """
        ssh_cmd = self._build_ssh_cmd()
        ssh_cmd.extend([self.config.ssh_host, command])

        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"SSH command timed out after {timeout}s: {command[:80]}")

        if process.returncode != 0:
            stderr_text = stderr.decode() if stderr else ""
            # Log but don't fail on SSH warnings
            if "Warning: Permanently added" not in stderr_text:
                logger.warning(f"SSH command exited {process.returncode}: {stderr_text}")

        return stdout.decode().strip()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.teardown()
