#!/usr/bin/env bash
# Remove the desktop install and its state. Your Claude login is left alone.
set -euo pipefail

systemctl --user disable --now claude-window-pinger.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/claude-window-pinger.service" "$HOME/.local/bin/claude-window-pinger"
rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/claude-window-pinger"
systemctl --user daemon-reload
echo "Removed."
