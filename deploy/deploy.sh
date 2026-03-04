#!/bin/bash
# Deploy nanobot systemd service

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/systemd/nanobot.service"
TARGET_DIR="$HOME/.config/systemd/user"

mkdir -p "$TARGET_DIR"
cp "$SCRIPT_DIR/systemd/nanobot.service" "$TARGET_DIR/nanobot.service"
cp "$SCRIPT_DIR/systemd/nanobot-update.service" "$TARGET_DIR/nanobot-update.service"

systemctl --user daemon-reload
systemctl --user enable nanobot
systemctl --user restart nanobot

echo "Done. Status:"
systemctl --user status nanobot --no-pager
