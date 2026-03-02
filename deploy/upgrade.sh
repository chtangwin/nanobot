#!/usr/bin/env bash
set -euo pipefail

# Upgrade script for nanobot (systemd one-shot service)
#
# Expected flow:
#   1) git pull latest code
#   2) install/update dependencies with uv
#   3) restart nanobot.service

APP_DIR="${APP_DIR:-/opt/nanobot}"
UV_BIN="${UV_BIN:-uv}"
SERVICE_NAME="${SERVICE_NAME:-nanobot.service}"

cd "$APP_DIR"

echo "[upgrade] app dir: $APP_DIR"
echo "[upgrade] fetching latest code..."
git fetch --all --prune

echo "[upgrade] pulling latest commit (ff-only)..."
git pull --ff-only

echo "[upgrade] syncing dependencies..."
"$UV_BIN" sync

echo "[upgrade] restarting $SERVICE_NAME ..."
systemctl restart "$SERVICE_NAME"

echo "[upgrade] done"
