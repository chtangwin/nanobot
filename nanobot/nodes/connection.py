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


def _get_node_script_path() -> Path:
    """Get the path to the node_server.py script.

    The script is located in the same directory as this module.
    """
    return Path(__file__).parent / "node_server.py"


# Load the node script at module import
_NODE_SCRIPT_PATH = _get_node_script_path()
if _NODE_SCRIPT_PATH.exists():
    _NODE_SCRIPT = _NODE_SCRIPT_PATH.read_text()
else:
    logger.warning(f"node_server.py not found at {_NODE_SCRIPT_PATH}")
    _NODE_SCRIPT = ""

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

    @property
    def is_connected(self) -> bool:
        """Check if the node is connected."""
        return self._running and self._authenticated

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
            # Try to get remote logs for debugging
            try:
                remote_log = await self._get_remote_log()
                logger.error(f"Remote node log:\n{remote_log}")
            except Exception:
                pass
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
        if not _NODE_SCRIPT:
            raise RuntimeError("node_server.py script not found. Cannot deploy node.")

        # Create remote temporary directory
        remote_dir = f"/tmp/{self.session_id}"
        logger.info(f"Creating remote directory: {remote_dir}")
        await self._ssh_exec(f"mkdir -p {remote_dir}")

        # Write node_server.py to a local temp file first
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(_NODE_SCRIPT)
            local_script_path = f.name

        # Upload node_server.py via scp
        logger.info(f"Uploading node_server.py to {remote_dir}")
        scp_cmd = ["scp"]
        if self.config.ssh_port:
            scp_cmd.extend(["-P", str(self.config.ssh_port)])
        if self.config.ssh_key_path:
            scp_cmd.extend(["-i", self.config.ssh_key_path])
        scp_cmd.extend([local_script_path, f"{self.config.ssh_host}:{remote_dir}/node_server.py"])

        process = await asyncio.create_subprocess_exec(
            *scp_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        # Clean up temp file
        import os
        os.unlink(local_script_path)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to upload node_server.py: {error_msg}")

        logger.info(f"Script uploaded successfully")

        # Create and upload config.json
        config = {
            "port": self.config.remote_port,
            "tmux": True,  # Enable tmux for session persistence
        }
        if self.config.auth_token:
            config["token"] = self.config.auth_token

        import json
        config_json = json.dumps(config, indent=2)

        # Write config to local temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(config_json)
            local_config_path = f.name

        # Upload config.json via scp
        logger.info(f"Uploading config.json to {remote_dir}")
        logger.info(f"Config: port={config['port']}, tmux={config['tmux']}, token={'***' if config.get('token') else 'none'}")

        scp_cmd = ["scp"]
        if self.config.ssh_port:
            scp_cmd.extend(["-P", str(self.config.ssh_port)])
        if self.config.ssh_key_path:
            scp_cmd.extend(["-i", self.config.ssh_key_path])
        scp_cmd.extend([local_config_path, f"{self.config.ssh_host}:{remote_dir}/config.json"])

        process = await asyncio.create_subprocess_exec(
            *scp_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        # Clean up temp file
        os.unlink(local_config_path)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to upload config.json: {error_msg}")

        logger.info(f"Config uploaded successfully")

    async def _start_node(self):
        """Start the node process on remote server."""
        remote_dir = f"/tmp/{self.session_id}"
        log_file = f"{remote_dir}/node_server.log"
        config_file = f"{remote_dir}/config.json"

        # Kill any existing node_server.py processes using this port
        logger.info(f"Cleaning up existing node_server processes on port {self.config.remote_port}")
        
        # Kill processes using the port first
        await self._ssh_exec(
            f"fuser -k {self.config.remote_port}/tcp 2>/dev/null || true"
        )
        
        # Also kill any node_server.py processes
        await self._ssh_exec(
            f"pkill -f 'node_server.py' || true"
        )
        
        await asyncio.sleep(1)

        # Build command using config file
        # Use setsid to fully detach from terminal
        cmd = f"cd {remote_dir} && setsid uv run --with websockets node_server.py --config {config_file} > {log_file} 2>&1 &"

        logger.info(f"Starting node on remote with config file")
        logger.info(f"Remote log: {log_file}")
        logger.info(f"Remote config: {config_file}")

        await self._ssh_exec(cmd)

        # Wait for node to start
        logger.info(f"Waiting 3s for node to start...")
        await asyncio.sleep(3)

    async def _get_remote_log(self, tail_lines: int = 50) -> str:
        """Get remote node server log."""
        if not self.session_id:
            return "No session ID"

        log_file = f"/tmp/{self.session_id}/node_server.log"

        try:
            result = await self._ssh_exec(f"tail -{tail_lines} {log_file} 2>/dev/null || echo 'Log file not found'")
            return result
        except Exception as e:
            return f"Failed to get log: {e}"

    async def _stop_node(self):
        """Stop the node process on remote server."""
        if self.session_id:
            remote_dir = f"/tmp/{self.session_id}"
            config_file = f"{remote_dir}/config.json"

            # Kill the node process using config file path
            logger.info(f"Stopping node process for session {self.session_id}")
            
            # Try multiple methods to ensure process is killed
            await self._ssh_exec(
                f"pkill -f 'node_server.py.*--config.*{config_file}' || true"
            )
            await asyncio.sleep(0.5)
            
            # Force kill if still running
            await self._ssh_exec(
                f"pkill -9 -f 'node_server.py.*--config.*{config_file}' || true"
            )
            
            # Also kill by port
            await self._ssh_exec(
                f"fuser -k {self.config.remote_port}/tcp 2>/dev/null || true"
            )

            # Kill tmux session for this node
            await self._ssh_exec(
                f"tmux -S /tmp/nanobot-tmux.sock kill-session -t nanobot 2>/dev/null || true"
            )

            await asyncio.sleep(0.5)

            # Clean up - use remote_dir variable
            await self._ssh_exec(f"rm -rf {remote_dir}")

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

    async def _ssh_exec(self, command: str) -> str:
        """Execute a command via SSH."""
        import subprocess
        
        ssh_cmd = [
            "ssh",
            "-p", str(self.config.ssh_port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",
        ]

        if self.config.ssh_key_path:
            ssh_cmd.extend(["-i", self.config.ssh_key_path])

        ssh_cmd.extend([self.config.ssh_host, command])

        # For background commands (& at end), use subprocess.Popen to avoid hanging
        if command.strip().endswith('&'):
            proc = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ""
            
        # For regular commands, use asyncio
        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode() if stderr else ""
            # Log but don't fail on warnings
            if "Warning: Permanently added" not in stderr_text:
                logger.warning(f"SSH failed (code {process.returncode}): {stderr_text}")

        return stdout.decode().strip()

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
