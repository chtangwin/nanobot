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
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-dev-combined}"
UV_SYNC_ARGS="${UV_SYNC_ARGS:---extra tts}"

cd "$APP_DIR"

echo "[update] app dir: $APP_DIR"
echo "[update] fetching latest code from ${GIT_REMOTE}/${GIT_BRANCH} ..."
git fetch "$GIT_REMOTE" "$GIT_BRANCH" --prune

echo "[update] checking out ${GIT_BRANCH} ..."
git checkout "$GIT_BRANCH"

echo "[update] pulling latest commit (ff-only) from ${GIT_REMOTE}/${GIT_BRANCH} ..."
git pull --ff-only "$GIT_REMOTE" "$GIT_BRANCH"

echo "[update] syncing dependencies: $UV_BIN sync $UV_SYNC_ARGS"
read -r -a uv_sync_args_array <<< "$UV_SYNC_ARGS"
"$UV_BIN" sync "${uv_sync_args_array[@]}"

echo "[update] restarting $SERVICE_NAME ..."
$SYSTEMCTL_CMD restart "$SERVICE_NAME"

echo "[update] done"
