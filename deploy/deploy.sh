#!/bin/bash
# Deploy nanobot systemd service

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/systemd/nanobot.service"
TARGET_DIR="$HOME/.config/systemd/user"

mkdir -p "$TARGET_DIR"
cp "$SERVICE_FILE" "$TARGET_DIR/nanobot.service"

systemctl --user daemon-reload
systemctl --user enable nanobot
systemctl --user restart nanobot

echo "Done. Status:"
systemctl --user status nanobot --no-pager
