#!/usr/bin/env bash
set -euo pipefail

# Simple update script for nanobot (systemd one-shot service)
# 1) pull origin/dev-combined
# 2) sync deps (keep tts extra)
# 3) restart user service

PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"

cd "$HOME/nanobot"

echo "[update] fetching origin/dev-combined ..."
git fetch origin dev-combined --prune

echo "[update] checking out dev-combined ..."
git checkout dev-combined

echo "[update] pulling latest commit (ff-only) ..."
git pull --ff-only origin dev-combined

echo "[update] syncing dependencies ..."
uv sync --extra tts

echo "[update] restarting nanobot.service ..."
systemctl --user restart nanobot.service

echo "[update] done"
