#!/usr/bin/env bash
# Install on a server as a sandboxed system service with a dedicated user.
# Run as root. Afterwards, sign in with: claude-pinger-login
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }

U=claude-pinger
H=/var/lib/claude-pinger
root="$(cd "$(dirname "$0")/.." && pwd)"

# A system user with no login shell, no password and a private home.
if ! id "$U" >/dev/null 2>&1; then
    adduser --system --group --home "$H" --shell /usr/sbin/nologin --disabled-password "$U"
fi
chown "$U:$U" "$H"
chmod 700 "$H"

# Root-owned, so the service user cannot change its own code or sandbox.
install -m 755 -o root -g root "$root/bin/claude-window-pinger" /usr/local/bin/claude-window-pinger
install -m 644 -o root -g root "$root/systemd/claude-pinger.service" /etc/systemd/system/claude-pinger.service
install -m 755 -o root -g root "$root/scripts/claude-pinger-login" /usr/local/sbin/claude-pinger-login
install -m 755 -o root -g root "$root/scripts/uninstall-server.sh" /usr/local/sbin/claude-pinger-uninstall

# The CLI belongs to the service user, so its self-updates need no root.
if [ ! -x "$H/.local/bin/claude" ]; then
    curl -fsSL https://claude.ai/install.sh -o "$H/install.sh"
    chown "$U:$U" "$H/install.sh"
    runuser -u "$U" -- env -i HOME="$H" PATH="$H/.local/bin:/usr/bin:/bin" LANG=C.UTF-8 \
        bash -c "cd '$H' && bash ./install.sh </dev/null"
    rm -f "$H/install.sh"
fi

# Enabled but not started: it would only stop with "Not logged in" until sign-in.
systemctl daemon-reload
systemctl enable claude-pinger.service
echo "Installed. Now sign in with: /usr/local/sbin/claude-pinger-login"
