#!/usr/bin/env bash
set -euo pipefail

# Update script for nanobot (systemd one-shot service)
#
# Expected flow:
#   1) git pull latest code
#   2) install/update dependencies with uv
#   3) restart nanobot.service

APP_DIR="${APP_DIR:-$HOME/nanobot}"
UV_BIN="${UV_BIN:-uv}"
SERVICE_NAME="${SERVICE_NAME:-nanobot.service}"
SYSTEMCTL_CMD="${SYSTEMCTL_CMD:-systemctl --user}"

cd "$APP_DIR"

echo "[update] app dir: $APP_DIR"
echo "[update] fetching latest code..."
git fetch --all --prune

echo "[update] pulling latest commit (ff-only)..."
git pull --ff-only

echo "[update] syncing dependencies..."
"$UV_BIN" sync

echo "[update] restarting $SERVICE_NAME ..."
$SYSTEMCTL_CMD restart "$SERVICE_NAME"

echo "[update] done"
