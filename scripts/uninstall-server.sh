#!/usr/bin/env bash
# Remove the server install: service, user and the stored Claude login. Run as root.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
systemctl disable --now claude-pinger.service 2>/dev/null || true
rm -f /etc/systemd/system/claude-pinger.service /usr/local/bin/claude-window-pinger /usr/local/sbin/claude-pinger-login /usr/local/sbin/claude-pinger-uninstall
systemctl daemon-reload
systemctl reset-failed claude-pinger.service 2>/dev/null || true
if id claude-pinger >/dev/null 2>&1; then
    pkill -u claude-pinger 2>/dev/null || true
    deluser --quiet claude-pinger
fi
rm -rf /var/lib/claude-pinger
echo "Removed. Also revoke the session in your Claude account settings if you no longer need it."
