#!/bin/bash
# nanobot remote host deploy script
# Uploaded to the remote host and executed there.
#
# The session directory (SCRIPT_DIR) contains:
#   - remote_server.py  (the WebSocket server)
#   - deploy.sh         (this script)
#
# All runtime files (PID, log, tmux socket) are written to SCRIPT_DIR
# which lives under /tmp/nanobot-<session_id>/.
#
# Usage:
#   bash deploy.sh --port PORT [--token TOKEN] [--no-tmux]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/remote_server.log"
PID_FILE="$SCRIPT_DIR/server.pid"

# ── Parse arguments ─────────────────────────────────────────────────
PORT=""
TOKEN=""
USE_TMUX=1

while [ $# -gt 0 ]; do
    case "$1" in
        --port)    PORT="$2";  shift 2 ;;
        --token)   TOKEN="$2"; shift 2 ;;
        --no-tmux) USE_TMUX=0; shift   ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [ -z "$PORT" ]; then
    echo "ERROR: --port is required" >&2
    echo "Usage: bash deploy.sh --port PORT [--token TOKEN] [--no-tmux]" >&2
    exit 1
fi

echo "Deploy: session_dir=$SCRIPT_DIR port=$PORT tmux=$USE_TMUX token=${TOKEN:+***}"

# ── Ensure uv is available ──────────────────────────────────────────
ensure_uv() {
    if command -v uv &>/dev/null; then
        echo "uv found: $(uv --version)"
        return 0
    fi

    echo "uv not found, installing..."
    if command -v curl &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget &>/dev/null; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "ERROR: Neither curl nor wget available. Cannot install uv." >&2
        exit 1
    fi

    # The installer puts uv in ~/.local/bin or ~/.cargo/bin
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        echo "ERROR: uv installation succeeded but uv not found in PATH" >&2
        echo "PATH=$PATH" >&2
        exit 1
    fi

    echo "uv installed: $(uv --version)"
}

ensure_uv

# ── Clean up old processes on this port ─────────────────────────────
echo "Cleaning up existing processes on port $PORT..."
fuser -k "$PORT/tcp" 2>/dev/null || true
sleep 0.5

# ── Build server command ────────────────────────────────────────────
SERVER_ARGS="--port $PORT"
if [ -n "$TOKEN" ]; then
    SERVER_ARGS="$SERVER_ARGS --token $TOKEN"
fi
if [ "$USE_TMUX" -eq 0 ]; then
    SERVER_ARGS="$SERVER_ARGS --no-tmux"
fi

# ── Start the server (detached) ─────────────────────────────────────
echo "Starting remote_server.py..."
cd "$SCRIPT_DIR"
setsid uv run --with websockets remote_server.py $SERVER_ARGS > "$LOG" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
# Disown so the process survives SSH session close
disown "$SERVER_PID" 2>/dev/null || true

echo "Server PID=$SERVER_PID, waiting for port $PORT to be ready..."

# ── Wait for port to be ready ───────────────────────────────────────
MAX_WAIT=60
for i in $(seq 1 $MAX_WAIT); do
    # Try multiple methods to check port (ss, netstat, /dev/tcp)
    if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        echo "Server ready on port $PORT (PID=$SERVER_PID) after ${i}s"
        exit 0
    elif netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        echo "Server ready on port $PORT (PID=$SERVER_PID) after ${i}s"
        exit 0
    elif (echo >/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
        echo "Server ready on port $PORT (PID=$SERVER_PID) after ${i}s"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Server failed to start within ${MAX_WAIT}s" >&2
echo "--- Last 30 lines of log ---" >&2
tail -30 "$LOG" 2>/dev/null >&2 || true
exit 1
