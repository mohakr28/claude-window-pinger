# Claude Window Pinger

[العربية](README.ar.md)

Starts Claude's next 5-hour usage window automatically, as soon as the current one ends.

Claude subscriptions count usage in 5-hour windows, and a new window only starts when you send a message. This tool sends one tiny message through the official [Claude Code](https://code.claude.com/docs) CLI right after each reset, so the clock is already running when you sit down to work.

> **It does not give you more usage.** It only starts the countdown earlier, so your limit refreshes sooner. If you start work 2 hours after a ping, your usage resets 3 hours later instead of 5.

This is an independent project, not affiliated with or endorsed by Anthropic.

## How it works

```
ping ──> read the exact reset time from the reply ──> wait until reset + 60s ──┐
  ^                                                                            │
  └────────────────────────────────────────────────────────────────────────────┘
```

- **About 5 pings a day.** It uses the reset time the CLI reports, so it never guesses. If you already started the window yourself, it just waits for that window to end.
- **Very small.** Each ping uses `claude-haiku-5-5` at `low` effort with no tools, MCP servers or saved transcript: about 600 input tokens and 4 output tokens.
- **Official CLI only.** It never reads your tokens or calls private endpoints.
- **No dependencies.** One Python 3 script using only the standard library.

## Before you use it

- **Check the terms yourself.** Anthropic's terms restrict automated access in general. Headless mode (`claude -p`) is an official CLI feature, but this project does not claim that this particular use is permitted. Your account is your responsibility.
- **Run one copy per account.** The limit belongs to the account, so a second machine adds nothing.
- **The machine must be on.** After a sleep or power-off, the ping is sent on wake rather than on time.

## Requirements

- Linux with systemd and Python 3.9+
- A paid Claude plan that includes Claude Code

## Install on a desktop

Runs as a systemd user service. Sign in to Claude first.

```bash
git clone https://github.com/mohakr28/claude-window-pinger.git
cd claude-window-pinger
claude auth login
./scripts/install-desktop.sh
```

To keep it running after you log out:

```bash
loginctl enable-linger "$USER"
```

## Install on a server

Run as root. This creates a dedicated `claude-pinger` user and a sandboxed system service, and installs the Claude CLI for that user only.

```bash
git clone https://github.com/mohakr28/claude-window-pinger.git
cd claude-window-pinger
./scripts/install-server.sh
/usr/local/sbin/claude-pinger-login
```

The last command prints a link. Open it and sign in; your login is stored only in the service user's private home.

## Everyday commands

| Task | Desktop | Server (as root) |
|---|---|---|
| Follow the log | `journalctl --user -u claude-window-pinger -f` | `journalctl -u claude-pinger -f` |
| Show next ping | `claude-window-pinger status` | `runuser -u claude-pinger -- env HOME=/var/lib/claude-pinger /usr/local/bin/claude-window-pinger status` |
| Restart after a fix | `systemctl --user restart claude-window-pinger` | `systemctl restart claude-pinger` |
| Remove everything | `./scripts/uninstall-desktop.sh` | `/usr/local/sbin/claude-pinger-uninstall` |

## How errors are handled

| Situation | What it does |
|---|---|
| Not signed in, session expired, plan without Claude Code, billing or account problem | **Stops** with exit code 78 and logs the reason. systemd does not restart it. |
| Signed in with an API key or Console account | **Stops** before sending anything, so nothing is billed. |
| Reply reports paid overage in use | **Stops**, so nothing more is charged. |
| 5-hour or weekly limit reached | Waits for the reset time in the reply. |
| Network failure, overloaded servers, timeout | Retries after 1, 2, 4 and 8 minutes, then every 15 minutes. |
| Model unavailable | Tries the plan's default model once. |
| Unknown error | Retries with the same backoff, up to once an hour. |
| Reply has no reset time | Checks again in an hour. |
| Any bug causing a loop | Never more than 12 successful pings in 24 hours. |
| Second copy started | Refuses to run. |
| Restarted mid-window | Resumes waiting, with no extra ping. |

Error wording is matched by pattern, and the CLI's messages can change. A new message is treated as unknown, which is the slow, safe path.

## Server sandbox

The service in [`systemd/claude-pinger.service`](systemd/claude-pinger.service):

- runs as a user with no password, no login shell and no SSH access
- can write only to `/var/lib/claude-pinger`, and cannot see `/home` or `/root`
- cannot reach services on localhost, such as MariaDB or Redis, apart from the DNS stub
- cannot gain privileges: `NoNewPrivileges` blocks `sudo` even if a sudoers rule allows it
- is limited to 768 MB of memory and half a CPU core

**What this does not protect:** the Claude login is stored on the server, so anyone who gains root there can reach it. Run `sudo -l -U claude-pinger` to see whether your hosting panel grants all users any `sudo` rules; the sandbox blocks them inside the service, but not in other sessions.

## Project layout

```
bin/claude-window-pinger   the tool
systemd/                   service files for desktop and server
scripts/                   install, uninstall and sign-in scripts
tests/test_pinger.py       unit tests
```

## Development

The tests use a fake CLI, so they need no Claude account and use no quota.

```bash
python3 -m unittest discover -s tests -v
```

The server install has run on Ubuntu 24.04 with Claude Code 2.1.318. On a desktop, pings were tested on Parrot OS with Claude Code 2.1.309, but `install-desktop.sh` itself has not been run yet. The tool reads the CLI's `stream-json` output, so a future CLI change could affect it. If the reset time disappears, it falls back to checking once an hour.

## License

[MIT](LICENSE)
