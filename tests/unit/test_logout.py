"""`logout` (`nexora logout`): graphical sessions end now, later, or not at all; text and SSH logins stay."""

import json
import subprocess
from datetime import datetime

import pytest

from distrokit.build import stage
from distrokit.system import logout


class FakeRun:
    def __init__(self, sessions=(), types=None, timer_active=False):
        self.sessions = list(sessions)
        self.types = types or {}
        self.timer_active = timer_active
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        out, code = "", 0
        if cmd[:2] == ["loginctl", "list-sessions"]:
            out = json.dumps(self.sessions)
        elif cmd[:2] == ["loginctl", "show-session"]:
            out = self.types.get(cmd[2], "") + "\n"
        elif "show" in cmd and any(str(c).endswith(".timer") for c in cmd):
            out = "ActiveState=active\nNextElapseUSecRealtime=Sat 2026-11-21 01:30:00\n" if self.timer_active \
                else "ActiveState=inactive\nNextElapseUSecRealtime=\n"
        return subprocess.CompletedProcess(cmd, code, out, "")


def test_when():
    now = datetime(2026, 11, 21, 22, 0)
    assert logout.when("now", now) == 0
    assert logout.when("+5", now) == 300 and logout.when("10", now) == 600
    assert logout.when("22:30", now) == 1800
    assert logout.when("21:00", now) == 23 * 3600  # passed today: tomorrow
    with pytest.raises(logout.LogoutError):
        logout.when("soon", now)


def test_only_graphical_sessions_of_the_user_end():
    run = FakeRun(
        sessions=[{"session": "2", "uid": 1000, "user": "mason"}, {"session": "3", "uid": 1000, "user": "mason"},
                  {"session": "4", "uid": 1001, "user": "guest"}],
        types={"2": "wayland", "3": "tty", "4": "wayland"},
    )
    found = logout.sessions({"mason"}, run=run)
    assert [s.id for s in found] == ["2"]  # the TTY login stays, and another user's session is not touched
    assert logout.end(found, run=run) == []
    assert ["loginctl", "terminate-session", "2"] in run.calls
    assert ["loginctl", "terminate-session", "3"] not in run.calls
    assert len(logout.sessions(None, run=run)) == 2  # --all: every user's graphical sessions


def test_sudo_logs_out_the_user_who_ran_it(monkeypatch):
    monkeypatch.setattr(logout.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "mason")
    assert logout.target_users(False) == {"mason"}
    assert logout.target_users(True) is None


def test_all_needs_root(monkeypatch):
    monkeypatch.setattr(logout.os, "geteuid", lambda: 1000)
    with pytest.raises(logout.LogoutError):
        logout.target_users(True)


def test_schedule_and_stop(monkeypatch):
    monkeypatch.setattr(logout.os, "geteuid", lambda: 0)
    run = FakeRun()
    logout.schedule(60, "nexora", False, {"mason"}, run=run)
    timer = [c for c in run.calls if c[0] == "systemd-run"][0]
    assert "--unit=nexora-logout" in timer and "--on-active=60" in timer
    assert "--setenv=SUDO_USER=mason" in timer and timer[-3:] == ["logout", "now", "--quiet"]
    assert logout.cancel(run=FakeRun(timer_active=True)) is True
    assert logout.cancel(run=FakeRun()) is False


def test_a_user_schedules_with_their_own_systemd(monkeypatch):
    monkeypatch.setattr(logout.os, "geteuid", lambda: 1000)
    run = FakeRun()
    logout.schedule(300, "nexora", False, {"mason"}, run=run)
    assert any(c[:2] == ["systemd-run", "--user"] for c in run.calls)


def test_the_logout_command_is_installed():
    source = (stage.__file__)
    text = open(source, encoding="utf-8").read()
    assert '"/usr/bin/logout"' in text and 'logout "$@"' in text
