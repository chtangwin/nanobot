"""Remote node connection implementation."""

import asyncio
import uuid
import json
import base64
import logging
from typing import Optional, Any
from pathlib import Path

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    websockets = None
    ConnectionClosed = Exception

from nanobot.nodes.config import NodeConfig

logger = logging.getLogger(__name__)


# The nanobot-node.py script that will be deployed to remote servers
NODE_SCRIPT = """#!/usr/bin/env python3
\"\"\"nanobot-node: Remote execution node for nanobot.

This script runs on remote servers and provides command execution
capabilities through WebSocket communication.
\"\"\"

import asyncio
import json
import subprocess
import sys
import signal

try:
    import websockets
except ImportError:
    print("Error: websockets package not found. Install with: pip install websockets")
    sys.exit(1)

SESSION_NAME = "nanobot"
PORT = {port}
AUTH_TOKEN = "{token}"


class TmuxSession:
    \"\"\"Manage a tmux session for maintaining context.\"\"\"

    def __init__(self, session_name: str = SESSION_NAME):
        self.session_name = session_name
        self.running = False

    async def create(self):
        \"\"\"Create a new tmux session.\"\"\"
        if self.running:
            return

        # Check if session already exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True,
        )
        if result.returncode == 0:
            # Session exists, kill it
            self.kill()

        # Create new session
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", self.session_name],
            check=True,
        )
        self.running = True

    async def send(self, command: str) -> None:
        \"\"\"Send command to tmux session.\"\"\"
        cmd = f"tmux send-keys -t {self.session_name} '{command.replace(\"'\", \"'\\\\''\")}' Enter"
        subprocess.run(cmd, shell=True, check=True)

    async def capture(self) -> str:
        \"\"\"Capture output from tmux session.\"\"\"
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-p"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def kill(self):
        \"\"\"Kill the tmux session.\"\"\"
        subprocess.run(
            ["tmux", "kill-session", "-t", self.session_name],
            capture_output=True,
        )
        self.running = False


class CommandExecutor:
    \"\"\"Execute commands and return results.\"\"\"

    def __init__(self):
        self.tmux = TmuxSession()

    async def execute(self, command: str) -> dict:
        \"\"\"Execute a command and return the result.\"\"\"
        try:
            # Ensure tmux session exists
            await self.tmux.create()

            # Send command
            await self.tmux.send(command)

            # Wait for command to execute
            await asyncio.sleep(0.5)

            # Capture output
            output = await self.tmux.capture()

            return {
                "success": True,
                "output": output,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": str(e),
            }

    def cleanup(self):
        \"\"\"Clean up resources.\"\"\"
        self.tmux.kill()


async def handle_connection(websocket, path):
    \"\"\"Handle WebSocket connection.\"\"\"
    # Authentication
    auth_message = await websocket.recv()
    auth_data = json.loads(auth_message)

    if AUTH_TOKEN and auth_data.get("token") != AUTH_TOKEN:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Authentication failed"
        }))
        return

    # Send success message
    await websocket.send(json.dumps({
        "type": "authenticated",
        "message": "Connection established"
    }))

    executor = CommandExecutor()

    try:
        async for message in websocket:
            data = json.loads(message)

            if data.get("type") == "execute":
                command = data.get("command")
                if not command:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No command provided"
                    }))
                    continue

                result = await executor.execute(command)
                await websocket.send(json.dumps({
                    "type": "result",
                    "command": command,
                    **result
                }))

            elif data.get("type") == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

            elif data.get("type") == "close":
                break

    finally:
        executor.cleanup()
        logger.info("Connection closed")


async def main():
    \"\"\"Start the WebSocket server.\"\"\"
    logger.info(f"Starting nanobot-node on port {PORT}")

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start server
    async with websockets.serve(handle_connection, "0.0.0.0", PORT):
        await stop_event.wait()

    logger.info("nanobot-node stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)
    asyncio.run(main())
"""


class RemoteNode:
    """
    Remote node connection.

    Manages SSH tunnel, WebSocket connection, and command execution
    on a remote server.
    """

    def __init__(self, config: NodeConfig):
        self.config = config
        self.session_id: Optional[str] = None
        self.tunnel_process: Optional[asyncio.subprocess.Process] = None
        self.websocket: Optional[Any] = None
        self._running = False
        self._authenticated = False

    async def setup(self) -> str:
        """
        Establish connection to remote node.

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

            # Deploy node script
            await self._deploy_node()

            # Start node process
            await self._start_node()

            # Connect WebSocket
            await self._connect_websocket()

            # Authenticate
            await self._authenticate()

            self._running = True
            logger.info(f"Remote node {self.config.name} connected (session: {self.session_id})")
            return self.session_id

        except Exception as e:
            logger.error(f"Failed to setup remote node {self.config.name}: {e}")
            await self.teardown()
            raise ConnectionError(f"Failed to connect to {self.config.name}: {e}")

    async def teardown(self):
        """Clean up all resources."""
        self._running = False
        self._authenticated = False

        cleanup_steps = [
            ("WebSocket", self._close_websocket),
            ("remote node", self._stop_node),
            ("SSH tunnel", self._close_ssh_tunnel),
        ]

        for name, cleanup in cleanup_steps:
            try:
                await cleanup()
            except Exception as e:
                logger.warning(f"Failed to cleanup {name}: {e}")

        logger.info(f"Remote node {self.config.name} disconnected")

    async def execute(self, command: str, timeout: float = 30.0) -> dict:
        """
        Execute a command on the remote node.

        Args:
            command: Command to execute.
            timeout: Maximum time to wait for result.

        Returns:
            Dictionary with 'success', 'output', and 'error' keys.

        Raises:
            ConnectionError: If not connected or command fails.
        """
        if not self._running or not self._authenticated:
            # Try to reconnect
            await self.setup()

        try:
            message = {
                "type": "execute",
                "command": command,
            }

            await self.websocket.send(json.dumps(message))

            # Wait for response
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=timeout
            )

            result = json.loads(response)

            if result.get("type") == "result":
                return {
                    "success": result.get("success", False),
                    "output": result.get("output"),
                    "error": result.get("error"),
                }
            elif result.get("type") == "error":
                return {
                    "success": False,
                    "output": None,
                    "error": result.get("message", "Unknown error"),
                }
            else:
                return {
                    "success": False,
                    "output": None,
                    "error": f"Unexpected response type: {result.get('type')}",
                }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "output": None,
                "error": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            logger.error(f"Failed to execute command on {self.config.name}: {e}")
            return {
                "success": False,
                "output": None,
                "error": str(e),
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

    async def _deploy_node(self):
        """Deploy node script to remote server."""
        # Generate node script with configuration
        script = NODE_SCRIPT.format(
            port=self.config.remote_port,
            token=self.config.auth_token or "",
        )

        # Create remote temporary directory
        remote_dir = f"/tmp/{self.session_id}"
        await self._ssh_exec(f"mkdir -p {remote_dir}")

        # Upload script (base64 encoded to avoid shell escaping issues)
        encoded_script = base64.b64encode(script.encode()).decode()
        await self._ssh_exec(
            f"echo {encoded_script} | base64 -d > {remote_dir}/nanobot-node.py"
        )

    async def _start_node(self):
        """Start the node process on remote server."""
        remote_dir = f"/tmp/{self.session_id}"

        # Start node process with uv
        # Use nohup to keep it running after SSH disconnect
        cmd = f"cd {remote_dir} && nohup uv run --with websockets nanobot-node.py > /dev/null 2>&1 &"
        await self._ssh_exec(cmd)

        # Wait for node to start
        await asyncio.sleep(3)

    async def _stop_node(self):
        """Stop the node process on remote server."""
        if self.session_id:
            # Kill the node process
            await self._ssh_exec(
                f"pkill -f 'nanobot-node.py' || true"
            )

            # Clean up temporary directory
            await self._ssh_exec(
                f"rm -rf /tmp/{self.session_id}"
            )

    async def _connect_websocket(self):
        """Connect to remote node via WebSocket."""
        ws_url = f"ws://127.0.0.1:{self.config.local_port}"

        logger.info(f"Connecting to WebSocket: {ws_url}")

        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(ws_url),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            raise ConnectionError(f"WebSocket connection timeout: {ws_url}")
        except Exception as e:
            raise ConnectionError(f"WebSocket connection failed: {e}")

    async def _close_websocket(self):
        """Close WebSocket connection."""
        if self.websocket:
            try:
                # Send close message
                await self.websocket.send(json.dumps({"type": "close"}))
                await asyncio.sleep(0.5)
            except Exception:
                pass

            try:
                await self.websocket.close()
            except Exception:
                pass
            finally:
                self.websocket = None

    async def _authenticate(self):
        """Authenticate with the remote node."""
        if self.config.auth_token:
            auth_message = {
                "token": self.config.auth_token,
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

    async def _ssh_exec(self, command: str) -> str:
        """Execute a command via SSH."""
        ssh_cmd = [
            "ssh",
            "-p", str(self.config.ssh_port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ]

        if self.config.ssh_key_path:
            ssh_cmd.extend(["-i", self.config.ssh_key_path])

        ssh_cmd.extend([self.config.ssh_host, command])

        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"SSH command failed: {stderr.decode()}")

        return stdout.decode()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.teardown()

    @property
    def is_connected(self) -> bool:
        """Check if node is connected."""
        return self._running and self._authenticated
