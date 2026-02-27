#!/usr/bin/env python3
"""nanobot node_server: Remote execution server for nanobot.

This script runs on remote servers and provides command execution
capabilities through WebSocket communication.

Usage:
    # Direct execution with command line args
    uv run --with websockets node_server.py --port 8765 --token secret

    # Using config file (recommended for automated deployment)
    uv run --with websockets node_server.py --config /path/to/config.json

Options:
    --config PATH         Path to JSON config file
    --port PORT           WebSocket port to listen on (default: 8765)
    --token TOKEN         Authentication token (optional)
    --no-tmux             Don't use tmux for session management
"""

import asyncio
import json
import subprocess
import sys
import signal
import argparse
import logging

try:
    import websockets
except ImportError:
    print("Error: websockets package not found.")
    print("Install with: pip install websockets")
    print("Or run with: uv run --with websockets node_server.py")
    sys.exit(1)

# Configuration defaults
DEFAULT_PORT = 8765
DEFAULT_SESSION_NAME = "nanobot"

logger = logging.getLogger(__name__)


class TmuxSession:
    """Manage a tmux session for maintaining context."""

    def __init__(self, session_name: str = DEFAULT_SESSION_NAME):
        self.session_name = session_name
        self.running = False

    async def create(self):
        """Create a new tmux session."""
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
        logger.info(f"Created tmux session: {self.session_name}")

    async def send(self, command: str) -> None:
        """Send command to tmux session."""
        # Escape single quotes in command
        escaped = command.replace("'", "'\\''")
        cmd = f"tmux send-keys -t {self.session_name} '{escaped}' Enter"
        subprocess.run(cmd, shell=True, check=True)
        logger.debug(f"Sent command to tmux: {command[:50]}...")

    async def capture(self) -> str:
        """Capture output from tmux session."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-p"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def kill(self):
        """Kill the tmux session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", self.session_name],
            capture_output=True,
        )
        self.running = False
        logger.info(f"Killed tmux session: {self.session_name}")


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

    def __init__(self, use_tmux: bool = True):
        self.use_tmux = use_tmux
        if use_tmux:
            self.tmux = TmuxSession()
        else:
            self.tmux = None

    async def execute(self, command: str) -> dict:
        """Execute a command and return the result."""
        if self.use_tmux:
            return await self._execute_tmux(command)
        else:
            return await self._execute_simple(command)

    async def _execute_tmux(self, command: str) -> dict:
        """Execute command using tmux session."""
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

    async def _execute_simple(self, command: str) -> dict:
        """Execute command without tmux."""
        executor = SimpleExecutor()
        return await executor.execute(command)

    def cleanup(self):
        """Clean up resources."""
        if self.tmux:
            self.tmux.kill()


async def handle_connection(websocket, path, auth_token: str, use_tmux: bool):
    """Handle WebSocket connection."""
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

    executor = CommandExecutor(use_tmux=use_tmux)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)

                if data.get("type") == "execute":
                    command = data.get("command")
                    if not command:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "No command provided"
                        }))
                        continue

                    logger.info(f"Executing: {command[:100]}...")
                    result = await executor.execute(command)
                    await websocket.send(json.dumps({
                        "type": "result",
                        "command": command,
                        **result
                    }))

                elif data.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))

                elif data.get("type") == "close":
                    logger.info("Received close message")
                    break

                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": f"Unknown message type: {data.get('type')}"
                    }))

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
    parser = argparse.ArgumentParser(description="nanobot remote node")
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
            use_tmux = not config.get("no_tmux", args.no_tmux)

            logger.info(f"Loaded config from: {args.config}")
            logger.info(f"Config: port={port}, token={'***' if token else 'none'}, tmux={use_tmux}")

        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            sys.exit(1)
    else:
        port = args.port
        token = args.token
        use_tmux = not args.no_tmux

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"Starting node_server on port {port}")
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
    handler = lambda ws, path: handle_connection(ws, path, token, use_tmux)

    async with websockets.serve(handler, "0.0.0.0", port):
        logger.info(f"Server listening on ws://0.0.0.0:{port}")
        await stop_event.wait()

    logger.info("node_server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
