import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# The script has no .py extension, so it is loaded by its explicit path.
path = str(Path(__file__).resolve().parent.parent / "bin" / "claude-window-pinger")
loader = importlib.machinery.SourceFileLoader("pinger", path)
spec = importlib.util.spec_from_loader("pinger", loader)
p = importlib.util.module_from_spec(spec)
loader.exec_module(p)

NOW = 1_000_000


def rl(status="allowed", resets=NOW + 3600, kind="five_hour", five=NOW + 3600, overage=False):
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": status, "resetsAt": resets, "rateLimitType": kind, "isUsingOverage": overage,
        "unifiedWindows": {"five_hour": {"utilization": 0.25, "resetsAt": five}}}})


def err(text, status=None):
    return json.dumps({"type": "result", "is_error": True, "result": text, "api_error_status": status})


OK = json.dumps({"type": "result", "is_error": False, "result": "ok"})


def kind_of(*lines, stderr=""):
    return p.classify(p.parse_stream(lines), stderr).kind


class Parse(unittest.TestCase):
    def test_normal(self):
        r = p.classify(p.parse_stream(["junk", "[1]", rl(), OK]))
        self.assertEqual(r.kind, p.OK)
        self.assertEqual(r.resets_at, NOW + 3600)
        self.assertEqual(r.utilization, 0.25)

    def test_weekly_block_uses_its_own_reset(self):
        r = p.classify(p.parse_stream([rl("rejected", NOW + 86400, "seven_day"), err("limit")]))
        self.assertEqual(r.kind, p.BLOCKED)
        self.assertEqual(r.blocked_until, NOW + 86400)


class Classify(unittest.TestCase):
    def test_fatal(self):
        for text, status in [("Not logged in · Please run /login", None),
                             ("Invalid API key", None),
                             ("OAuth token has expired", 401),
                             ("whatever", 403),
                             ("Your plan does not include Claude Code", None),
                             ("Your subscription does not support this", None),
                             ("Credit balance is too low", None),
                             ("Your account has been disabled", None),
                             ("This service is not available in your country", None)]:
            with self.subTest(text=text):
                self.assertEqual(kind_of(err(text, status)), p.FATAL)

    def test_overage_stops_even_when_the_ping_worked(self):
        self.assertEqual(kind_of(rl(overage=True), OK), p.FATAL)

    def test_limit_text_is_not_mistaken_for_a_plan_problem(self):
        self.assertEqual(kind_of(err("You've hit your usage limit on your subscription")), p.TRANSIENT)

    def test_model(self):
        self.assertEqual(kind_of(err("x", 404)), p.MODEL_ERROR)
        self.assertEqual(kind_of(err("model: claude-haiku-5-5 not found")), p.MODEL_ERROR)
        self.assertEqual(kind_of(err("You may not have access to this model")), p.MODEL_ERROR)

    def test_transient(self):
        for text, status in [("x", 529), ("x", 500), ("Connection error", None),
                             ("getaddrinfo ENOTFOUND api.anthropic.com", None), ("x", 429)]:
            with self.subTest(text=text, status=status):
                self.assertEqual(kind_of(err(text, status)), p.TRANSIENT)

    def test_unknown(self):
        self.assertEqual(kind_of(err("something odd happened")), p.UNKNOWN)

    def test_stderr_counts(self):
        self.assertEqual(kind_of(stderr="Not logged in"), p.FATAL)


class Wake(unittest.TestCase):
    def test_after_reset(self):
        r = p.PingResult(ok=True, kind=p.OK, resets_at=NOW + 100)
        self.assertEqual(p.next_wake(r, NOW, 0), NOW + 100 + p.RESET_MARGIN)

    def test_blocked_waits_for_reset(self):
        r = p.PingResult(ok=False, kind=p.BLOCKED, blocked_until=NOW + 500)
        self.assertEqual(p.next_wake(r, NOW, 0), NOW + 500 + p.RESET_MARGIN)

    def test_backoff_caps_differ(self):
        t = p.PingResult(ok=False, kind=p.TRANSIENT)
        u = p.PingResult(ok=False, kind=p.UNKNOWN)
        self.assertEqual([p.next_wake(t, 0, n) for n in (1, 2, 3, 500)], [60, 120, 240, 900])
        self.assertEqual(p.next_wake(u, 0, 500), 3600)

    def test_never_spins(self):
        self.assertEqual(p.next_wake(p.PingResult(ok=True, kind=p.OK), NOW, 0), NOW + p.NO_INFO_RECHECK)
        stale = p.PingResult(ok=True, kind=p.OK, resets_at=NOW - 5)
        self.assertEqual(p.next_wake(stale, NOW, 0), NOW + p.STALE_RECHECK)
        expired = p.PingResult(ok=False, kind=p.BLOCKED, blocked_until=NOW - 5)
        self.assertEqual(p.next_wake(expired, NOW, 0), NOW + p.STALE_RECHECK)

    def test_daily_cap(self):
        self.assertEqual(p.apply_daily_cap(NOW, [NOW - 10] * 5), NOW)
        pings = [NOW - 1000 + i for i in range(p.MAX_PINGS_PER_DAY)]
        wake = p.apply_daily_cap(NOW, pings)
        self.assertGreater(wake, NOW)
        self.assertEqual(p.apply_daily_cap(wake, pings), wake)


class EndToEnd(unittest.TestCase):
    """Runs against a fake CLI, so these tests use no quota."""

    AUTH_OK = '{"loggedIn":true,"authMethod":"claude.ai","subscriptionType":"pro"}'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        p.STATE_DIR, p.STATE_FILE, p.WORK_DIR, p.LOCK_FILE = d, d / "state.json", d / "cwd", d / "lock"
        self.seen = d / "env.txt"
        self.args = d / "args.txt"
        self.fake = d / "claude"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("CLAUDE_BIN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def fake_cli(self, body, auth=None):
        auth = auth or self.AUTH_OK
        self.fake.write_text(
            f"#!/bin/sh\nif [ \"$1\" = auth ]; then echo '{auth}'; exit 0; fi\n"
            f"env > {self.seen}\necho \"$@\" >> {self.args}\n{body}\n")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        os.environ["CLAUDE_BIN"] = str(self.fake)

    def good_reply(self):
        future = int(time.time()) + 3600
        return future, f"echo '{rl(resets=future, five=future)}'\necho '{OK}'"

    def test_api_key_never_reaches_cli(self):
        self.fake_cli("exit 0")
        os.environ["ANTHROPIC_API_KEY"] = "test-value"
        p.ping()
        self.assertNotIn("ANTHROPIC_API_KEY", self.seen.read_text())

    def test_uses_requested_model_and_effort(self):
        _, reply = self.good_reply()
        self.fake_cli(reply)
        p.ping()
        args = self.args.read_text()
        self.assertIn("--model claude-haiku-5-5", args)
        self.assertIn("--effort low", args)

    def test_success_saves_state(self):
        future, reply = self.good_reply()
        self.fake_cli(reply)
        wake, fails, kind = p.run_once(0)
        self.assertEqual((wake, fails, kind), (future + p.RESET_MARGIN, 0, p.OK))
        state = p.load_state()
        self.assertEqual(state["next_ping"], wake)
        self.assertEqual(len(state["pings"]), 1)

    def test_crash_with_no_details_backs_off(self):
        self.fake_cli("echo boom >&2; exit 1")
        _, fails, kind = p.run_once(2)
        self.assertEqual((fails, kind), (3, p.UNKNOWN))
        self.assertEqual(p.load_state()["detail"], "boom")

    def test_logged_out_sends_no_message(self):
        self.fake_cli("exit 0", auth='{"loggedIn":false}')
        wake, _, kind = p.run_once(0)
        self.assertEqual((wake, kind), (0, p.FATAL))
        self.assertFalse(self.args.exists())

    def test_api_key_login_refused_without_a_message(self):
        self.fake_cli("exit 0", auth='{"loggedIn":true,"authMethod":"api_key"}')
        self.assertEqual(p.run_once(0)[2], p.FATAL)
        self.assertFalse(self.args.exists())

    def test_free_plan_refused(self):
        self.fake_cli("exit 0", auth='{"loggedIn":true,"authMethod":"claude.ai","subscriptionType":"free"}')
        self.assertEqual(p.run_once(0)[2], p.FATAL)

    def test_broken_auth_status_does_not_block_the_ping(self):
        future, reply = self.good_reply()
        self.fake_cli(reply, auth="not json")
        self.assertEqual(p.run_once(0)[2], p.OK)

    def test_model_fallback_tries_once_without_model(self):
        future, reply = self.good_reply()
        self.fake_cli(f'case "$*" in *--model*) echo \'{err("model not found", 404)}\';; *) {reply};; esac')
        self.assertEqual(p.run_once(0)[2], p.OK)
        lines = self.args.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("--model", lines[1])

    def test_model_failing_twice_does_not_loop(self):
        self.fake_cli(f"echo '{err('x', 404)}'")
        self.assertEqual(p.run_once(0)[2], p.UNKNOWN)
        self.assertEqual(len(self.args.read_text().splitlines()), 2)

    def test_second_copy_is_refused(self):
        held = p.acquire_lock()
        self.assertIsNotNone(held)
        self.assertIsNone(p.acquire_lock())
        held.close()

    def test_daemon_exits_78_when_stopped(self):
        self.fake_cli("exit 0", auth='{"loggedIn":false}')
        env = {**os.environ, "XDG_STATE_HOME": str(self.d / "xdg")}
        out = subprocess.run([sys.executable, "-B", path, "run"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 78)
        self.assertIn("STOPPED", out.stdout)


if __name__ == "__main__":
    unittest.main()
