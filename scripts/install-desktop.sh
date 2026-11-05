#!/usr/bin/env bash
# Install for the current user as a systemd user service. Needs no root.
# Sign in first with: claude auth login
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

install -Dm755 "$root/bin/claude-window-pinger" "$HOME/.local/bin/claude-window-pinger"
install -Dm644 "$root/systemd/claude-window-pinger.service" "$HOME/.config/systemd/user/claude-window-pinger.service"
systemctl --user daemon-reload
systemctl --user enable --now claude-window-pinger.service
systemctl --user --no-pager status claude-window-pinger.service | head -n 5
